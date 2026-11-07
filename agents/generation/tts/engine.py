"""TTS 引擎。

v1 提供两种，均通过 TTS_ENGINE 选择（auto 时：配了 TTS_HTTP_URL 走 http，否则 silent）：
  - silent：本地 mock，用 ffmpeg 生成与“220 字/分钟”等长的静音 mp3。演示必须明确它不是真实语音。
  - http  ：真实 TTS 服务的接入点，POST JSON 拿音频字节（或 base64），由 TTS_HTTP_URL 指定。
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..errors import AppError, ErrorCode, TTSFailed, TTSUnavailable
from ..media import probe_duration_ms, probe_sample_rate
from ..proc import run, tail

#: §1.14 降级口径：TTS 失败时时长按 220 字/分钟估算，视频用静音 + 字幕
CHARS_PER_MINUTE = 220
MIN_DURATION_SEC = 1.5


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

        duration_sec = estimate_duration_sec(text) / max(0.5, min(2.0, speed))
        sample_rate = self.settings.tts_sample_rate
        tmp = out_path.with_name(f"{out_path.name}.{os.getpid()}.part")
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
        proc = run(cmd, timeout=60)
        if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            raise TTSFailed("mock 音频生成失败", detail=tail(proc))
        os.replace(tmp, out_path)
        measured_ms = probe_duration_ms(out_path, self.settings) or int(round(duration_sec * 1000))
        return SynthOutcome(out_path, measured_ms, sample_rate, True, self.name)


class HttpEngine:
    """真实 TTS 服务接入点。

    请求：POST TTS_HTTP_URL，JSON {"text","voice_id","speed","format"}，可带 Authorization: Bearer TTS_API_KEY
    响应：音频字节（Content-Type: audio/*），或 JSON {"audio_base64": "...", "sample_rate": 24000}
    """

    name = "http"

    def __init__(self, settings: Settings):
        if not settings.tts_http_url:
            raise TTSUnavailable("未配置 TTS_HTTP_URL", detail="TTS_ENGINE=http 时必须提供 TTS_HTTP_URL")
        self.settings = settings

    def synthesize(self, text: str, voice_id: str, speed: float, fmt: str, out_path: Path) -> SynthOutcome:
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
                raw = response.read()
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            raise TTSFailed(f"TTS 服务返回 HTTP {exc.code}", detail=exc.read()[:400].decode("utf-8", "replace")) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TTSUnavailable("TTS 服务未启动或不可达", detail=str(exc)) from exc

        declared_rate: int | None = None
        if "json" in content_type.lower() or raw[:1] == b"{":
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TTSFailed("TTS 返回了无法解析的 JSON") from exc
            b64 = payload.get("audio_base64") or ""
            if not b64:
                raise TTSFailed("TTS 返回 JSON 但缺少 audio_base64")
            raw = base64.b64decode(b64)
            declared_rate = payload.get("sample_rate")

        if not raw:
            raise TTSFailed("TTS 返回空音频")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_name(f"{out_path.name}.{os.getpid()}.part")
        tmp.write_bytes(raw)
        os.replace(tmp, out_path)

        measured_ms = probe_duration_ms(out_path, self.settings)
        sample_rate = probe_sample_rate(out_path, self.settings) or declared_rate or self.settings.tts_sample_rate
        return SynthOutcome(
            path=out_path,
            duration_ms=measured_ms or estimate_duration_ms(text),
            sample_rate=int(sample_rate),
            measured=measured_ms is not None,
            engine=self.name,
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
