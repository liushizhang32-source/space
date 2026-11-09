"""TTS 引擎。

v1 提供两种，均通过 TTS_ENGINE 选择（auto 时：配了 TTS_HTTP_URL 走 http，否则 silent）：
  - silent：本地 mock，用 ffmpeg 生成与“220 字/分钟”等长的静音 mp3。演示必须明确它不是真实语音。
  - http  ：真实 TTS 服务的接入点，POST JSON 拿音频字节（或 base64），由 TTS_HTTP_URL 指定。
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..errors import AppError, ErrorCode, TTSFailed, TTSUnavailable
from ..media import AudioProbe, MediaStatus, validate_audio
from ..proc import run, tail

#: §1.14 降级口径：TTS 失败时时长按 220 字/分钟估算，视频用静音 + 字幕
CHARS_PER_MINUTE = 220
MIN_DURATION_SEC = 1.5


def _tmp_path(out_path: Path) -> Path:
    """进程 + 线程 + 随机后缀：同一句话并发生成时不会共用临时文件。"""
    suffix = f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.part"
    return out_path.with_name(f"{out_path.name}.{suffix}")


def replace_with_retry(src: Path, dst: Path, attempts: int = 6) -> None:
    """Windows 上并发替换同一目标可能报共享冲突，短暂退避重试。"""
    last: OSError | None = None
    for index in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:  # WinError 5 / 32：目标正被探测或替换
            last = exc
            time.sleep(0.05 * (index + 1))
    raise last or PermissionError(f"无法替换 {dst}")


def estimate_duration_sec(text: str) -> float:
    return max(MIN_DURATION_SEC, len(text) * 60.0 / CHARS_PER_MINUTE)


def estimate_duration_ms(text: str) -> int:
    return int(round(estimate_duration_sec(text) * 1000))


@dataclass(frozen=True)
class SynthOutcome:
    path: Path
    duration_ms: int
    sample_rate: int
    measured: bool  # True 表示时长是实测的（duration_source="tts"）
    engine: str


class SilentEngine:
    """mock 引擎：生成静音音轨，时长按字数估算。产物一定是“假语音”，不要拿去演示真实音色。"""

    name = "silent"

    def __init__(self, settings: Settings):
        self.settings = settings

    def synthesize(self, text: str, voice_id: str, speed: float, fmt: str, out_path: Path) -> SynthOutcome:
        ffmpeg = self.settings.ffmpeg
        if not ffmpeg:
            raise TTSUnavailable("ffmpeg 不可用，无法生成 mock 音频", detail="FFMPEG_PATH 未找到可执行文件")
        if not self.settings.ffprobe:
            raise TTSUnavailable("ffprobe 不可用，无法校验音频", detail="FFPROBE_PATH 未找到可执行文件")

        duration_sec = estimate_duration_sec(text) / max(0.5, min(2.0, speed))
        sample_rate = self.settings.tts_sample_rate
        tmp = _tmp_path(out_path)
        if fmt == "mp3":
            fmt_args = ["-c:a", "libmp3lame", "-b:a", "48k", "-f", "mp3"]
        else:
            fmt_args = ["-c:a", "pcm_s16le", "-f", "wav"]
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={sample_rate}:cl=mono",
            "-t",
            f"{duration_sec:.3f}",
            *fmt_args,
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            str(tmp),
        ]
        try:
            proc = run(cmd, timeout=60)
            if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
                raise TTSFailed("mock 音频生成失败", detail=tail(proc))

            # 先验证临时文件，通过后才发布为正式产物；失败不碰已有文件
            check = validate_audio(tmp, self.settings, deep=True)
            if check.status is MediaStatus.UNAVAILABLE:
                raise TTSUnavailable("mock 音频无法验证（缺少 ffmpeg/ffprobe）", detail=check.reason)
            if check.status is MediaStatus.INVALID:
                raise TTSFailed(f"mock 音频生成后校验失败：{check.reason}")
            probe = check.probe
            assert isinstance(probe, AudioProbe)

            replace_with_retry(tmp, out_path)
        finally:
            tmp.unlink(missing_ok=True)

        return SynthOutcome(out_path, probe.duration_ms, probe.sample_rate, True, self.name)


def _safe_error_body(exc: urllib.error.HTTPError, limit: int = 400) -> str:
    """只读有限字节并关闭句柄，避免错误页本身很大时吃满内存/连接。"""
    try:
        raw = exc.read(limit) or b""
    except Exception:  # pragma: no cover - 连接可能已断开
        return ""
    finally:
        try:
            exc.close()
        except Exception:  # pragma: no cover
            pass
    return raw.decode("utf-8", "replace")[:limit]


class HttpEngine:
    """真实 TTS 服务接入点。

    请求：POST TTS_HTTP_URL，JSON {"text","voice_id","speed","format"}，可带 Authorization: Bearer TTS_API_KEY
    响应：音频字节（Content-Type: audio/*），或 JSON {"audio_base64": "...", "sample_rate": 24000}

    下载侧强制校验：HTTP 状态、Content-Type、Content-Length/实际大小、真实编码格式；
    失败路径必须清理临时文件，未验证的音频绝不发布。
    """

    name = "http"

    #: 允许的响应类型；text/html 之类直接判失败（常见于网关错误页）
    ALLOWED_BINARY_TYPES = frozenset({"application/octet-stream", "binary/octet-stream"})
    CHUNK_SIZE = 64 * 1024

    def __init__(self, settings: Settings):
        if not settings.tts_http_url:
            raise TTSUnavailable("未配置 TTS_HTTP_URL", detail="TTS_ENGINE=http 时必须提供 TTS_HTTP_URL")
        self.settings = settings

    def synthesize(self, text: str, voice_id: str, speed: float, fmt: str, out_path: Path) -> SynthOutcome:
        raw, declared_rate = self._download(text, voice_id, speed, fmt)

        if not raw:
            raise TTSFailed("TTS 返回空音频")
        if len(raw) > self.settings.tts_max_audio_bytes:
            raise TTSFailed(
                f"TTS 音频超过大小上限（{len(raw)} > {self.settings.tts_max_audio_bytes} 字节）"
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = _tmp_path(out_path)
        try:
            tmp.write_bytes(raw)
            # 先验证临时文件（含容器格式），通过后才替换；失败不碰已有产出
            check = validate_audio(tmp, self.settings, deep=True)
            if check.status is MediaStatus.UNAVAILABLE:
                raise TTSUnavailable(
                    "TTS 音频无法验证（缺少 ffmpeg/ffprobe）",
                    detail=check.reason,
                )
            if check.status is MediaStatus.INVALID:
                raise TTSFailed(f"TTS 返回的音频不可用：{check.reason}", detail=f"url={self.settings.tts_http_url}")

            probe = check.probe
            assert isinstance(probe, AudioProbe)
            self._check_format(probe, fmt)

            replace_with_retry(tmp, out_path)
        finally:
            tmp.unlink(missing_ok=True)

        return SynthOutcome(
            path=out_path,
            duration_ms=probe.duration_ms,
            sample_rate=probe.sample_rate or int(declared_rate or self.settings.tts_sample_rate),
            measured=True,
            engine=self.name,
        )

    def _download(self, text: str, voice_id: str, speed: float, fmt: str) -> tuple[bytes, int | None]:
        body = json.dumps(
            {"text": text, "voice_id": voice_id, "speed": speed, "format": fmt},
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        api_key = getattr(self.settings, "tts_api_key", "") or ""
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(self.settings.tts_http_url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(request, timeout=self.settings.tts_timeout_sec) as response:
                status = int(getattr(response, "status", 200) or 200)
                if status != 200:
                    raise TTSFailed(f"TTS 服务返回 HTTP {status}")

                content_type = (response.headers.get("Content-Type") or "").lower()
                raw = self._read_limited(response)
        except urllib.error.HTTPError as exc:
            raise TTSFailed(
                f"TTS 服务返回 HTTP {exc.code}",
                detail=_safe_error_body(exc),
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise AppError(ErrorCode.TIMEOUT, "TTS 请求超时", detail=str(exc)) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise AppError(ErrorCode.TIMEOUT, "TTS 请求超时", detail=str(reason)) from exc
            raise TTSUnavailable("TTS 服务未启动或不可达", detail=str(exc)) from exc

        # 先按声明的 Content-Type（取裸 MIME，忽略 charset 等参数）决定是否允许。
        # text/html 之类一律拒绝，不能因为 body 恰好以 "{" 开头就绕过类型检查。
        mime = content_type.split(";", 1)[0].strip()
        is_json = mime == "application/json" or mime.endswith("+json")
        is_binary_audio = mime.startswith("audio/") or mime in self.ALLOWED_BINARY_TYPES
        if mime and not is_json and not is_binary_audio:
            raise TTSFailed(f"TTS 返回的不是音频（Content-Type: {mime}）")

        if is_json:
            return self._parse_json_audio(raw)

        if not mime and raw[:1] == b"{":
            # 未声明类型但 body 是 JSON：按 JSON 处理，仍然做严格结构校验
            return self._parse_json_audio(raw)

        return raw, None

    @staticmethod
    def _parse_json_audio(raw: bytes) -> tuple[bytes, int | None]:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TTSFailed("TTS 返回了无法解析的 JSON") from exc
        if not isinstance(payload, dict):
            raise TTSFailed("TTS 返回的 JSON 不是对象")

        b64 = payload.get("audio_base64")
        if not isinstance(b64, str) or not b64.strip():
            raise TTSFailed("TTS 返回 JSON 但缺少非空字符串 audio_base64")

        try:
            audio = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise TTSFailed("TTS 返回的 base64 音频非法") from exc
        if not audio:
            raise TTSFailed("TTS 返回的 base64 解码后为空")

        declared_rate = payload.get("sample_rate")
        try:
            rate = int(declared_rate) if declared_rate is not None else None
        except (TypeError, ValueError):
            rate = None
        return audio, rate

    def _read_limited(self, response) -> bytes:
        max_bytes = self.settings.tts_max_audio_bytes
        declared = response.headers.get("Content-Length")
        if declared:
            try:
                if int(declared) > max_bytes:
                    raise TTSFailed(
                        f"TTS 响应头声明的大小超过上限（{declared} > {max_bytes} 字节）"
                    )
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        while True:
            try:
                chunk = response.read(self.CHUNK_SIZE)
            except (TimeoutError, socket.timeout) as exc:
                raise AppError(ErrorCode.TIMEOUT, "TTS 下载超时", detail=str(exc)) from exc
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise TTSFailed(f"TTS 音频超过大小上限（>{max_bytes} 字节）")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def format_matches(probe: AudioProbe, fmt: str) -> bool:
        """编码 + 容器都要对：mp3 必须是 mp3 容器里的 mp3 流；wav 只接受 wav 容器。"""
        containers = {name.strip() for name in probe.format_name.split(",") if name.strip()}
        if not containers:
            return False
        if fmt == "mp3":
            return probe.codec == "mp3" and containers == {"mp3"}
        if fmt == "wav":
            return probe.codec.startswith("pcm_") and containers == {"wav"}
        return False

    @classmethod
    def _check_format(cls, probe: AudioProbe, fmt: str) -> None:
        if cls.format_matches(probe, fmt):
            return
        raise TTSFailed(
            f"音频格式不匹配：请求 {fmt}，实际编码={probe.codec} 容器={probe.format_name or '未知'}"
        )


def build_engine(settings: Settings) -> SilentEngine | HttpEngine:
    name = (settings.tts_engine or "auto").strip().lower()
    if name == "auto":
        name = "http" if settings.tts_http_url else "silent"
    if name == "silent":
        return SilentEngine(settings)
    if name == "http":
        return HttpEngine(settings)
    raise AppError(ErrorCode.INVALID_PARAM, f"未知 TTS_ENGINE: {name}")
