"""音视频探测与“产物有效性”校验。

三态，绝不含糊：
  - OK          ：文件存在、容器/编码/时长正常，deep 时已真正解码；
  - INVALID     ：文件坏、类型不对、解码失败；
  - UNAVAILABLE ：缺少 ffprobe/ffmpeg，**无法验证**——调用方必须按失败处理，
                  不能把未验证的文件当成合格产物。

`probe_*` 保留“拿数据”的语义；`validate_*` 是安全/质量闸门，返回三态。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .config import Settings
from .proc import run

#: 契约允许的音轨编码（A6 默认 mp3；真实 TTS 可能回 wav/aac/opus）
AUDIO_CODECS = frozenset(
    {
        "mp3",
        "aac",
        "opus",
        "vorbis",
        "flac",
        "pcm_s16le",
        "pcm_s24le",
        "pcm_s32le",
        "pcm_f32le",
        "pcm_u8",
    }
)

VIDEO_CODECS = frozenset({"h264", "hevc", "vp9", "av1"})


class MediaStatus(str, Enum):
    OK = "ok"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class AudioProbe:
    duration_ms: int
    sample_rate: int
    channels: int
    codec: str
    format_name: str = ""


@dataclass(frozen=True)
class VideoProbe:
    duration_ms: int
    width: int
    height: int
    fps: float
    has_audio: bool


@dataclass(frozen=True)
class MediaCheck:
    status: MediaStatus
    probe: AudioProbe | VideoProbe | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status is MediaStatus.OK


def _probe_json(path: Path, settings: Settings) -> dict | None:
    ffprobe = settings.ffprobe
    if not ffprobe or not path.is_file() or path.stat().st_size == 0:
        return None
    proc = run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,codec_type,width,height,r_frame_rate,sample_rate,channels"
            ":format=duration,format_name",
            "-of",
            "json",
            str(path),
        ],
        timeout=20,
    )
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads((proc.stdout or b"").decode("utf-8", "replace"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _format_duration_ms(payload: dict) -> int | None:
    raw = (payload.get("format") or {}).get("duration")
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return int(round(seconds * 1000))


def _decode_ok(path: Path, settings: Settings, timeout: int = 60) -> bool | None:
    """真正解码一遍。

    返回 None 表示“没有 ffmpeg，无法验证”——调用方必须当失败处理，
    不能按 True（成功）对待。
    """
    ffmpeg = settings.ffmpeg
    if not ffmpeg:
        return None
    proc = run(
        [ffmpeg, "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
        timeout=timeout,
    )
    return proc.returncode == 0


def validate_audio(path: Path, settings: Settings, *, deep: bool = False) -> MediaCheck:
    if not path.is_file() or path.stat().st_size == 0:
        return MediaCheck(MediaStatus.INVALID, None, "音频文件不存在或为空")
    if not settings.ffprobe:
        return MediaCheck(MediaStatus.UNAVAILABLE, None, "ffprobe 不可用，无法校验音频")

    payload = _probe_json(path, settings)
    if payload is None:
        return MediaCheck(MediaStatus.INVALID, None, "无法解析音频容器")

    streams = [s for s in payload.get("streams") or [] if s.get("codec_type") == "audio"]
    if not streams:
        return MediaCheck(MediaStatus.INVALID, None, "文件里没有音频流")

    stream = streams[0]
    codec = str(stream.get("codec_name") or "")
    if codec not in AUDIO_CODECS:
        return MediaCheck(MediaStatus.INVALID, None, f"不支持的音频编码: {codec or '未知'}")

    try:
        sample_rate = int(stream.get("sample_rate") or 0)
        channels = int(stream.get("channels") or 0)
    except (TypeError, ValueError):
        return MediaCheck(MediaStatus.INVALID, None, "音频采样率/声道数不合法")
    if sample_rate <= 0:
        return MediaCheck(MediaStatus.INVALID, None, "音频采样率不合法")

    duration_ms = _format_duration_ms(payload)
    if duration_ms is None:
        return MediaCheck(MediaStatus.INVALID, None, "音频时长为 0 或不可读")

    format_name = str((payload.get("format") or {}).get("format_name") or "")

    if deep:
        decoded = _decode_ok(path, settings)
        if decoded is None:
            return MediaCheck(MediaStatus.UNAVAILABLE, None, "ffmpeg 不可用，无法解码校验音频")
        if not decoded:
            return MediaCheck(MediaStatus.INVALID, None, "音频解码失败")

    return MediaCheck(
        MediaStatus.OK,
        AudioProbe(
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            channels=channels,
            codec=codec,
            format_name=format_name,
        ),
    )


def validate_video(path: Path, settings: Settings, *, deep: bool = False) -> MediaCheck:
    if not path.is_file() or path.stat().st_size == 0:
        return MediaCheck(MediaStatus.INVALID, None, "视频文件不存在或为空")
    if not settings.ffprobe:
        return MediaCheck(MediaStatus.UNAVAILABLE, None, "ffprobe 不可用，无法校验视频")

    payload = _probe_json(path, settings)
    if payload is None:
        return MediaCheck(MediaStatus.INVALID, None, "无法解析视频容器")

    streams = [s for s in payload.get("streams") or [] if s.get("codec_type") == "video"]
    if not streams:
        return MediaCheck(MediaStatus.INVALID, None, "文件里没有视频流")
    stream = streams[0]

    codec = str(stream.get("codec_name") or "")
    if codec not in VIDEO_CODECS:
        return MediaCheck(MediaStatus.INVALID, None, f"不支持的视频编码: {codec or '未知'}")

    try:
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
    except (TypeError, ValueError):
        return MediaCheck(MediaStatus.INVALID, None, "视频分辨率不合法")
    if width <= 0 or height <= 0:
        return MediaCheck(MediaStatus.INVALID, None, "视频分辨率不合法")

    fps = 0.0
    raw_rate = str(stream.get("r_frame_rate") or "")
    if "/" in raw_rate:
        num, _, den = raw_rate.partition("/")
        try:
            fps = float(num) / float(den) if float(den) else 0.0
        except ValueError:
            fps = 0.0

    duration_ms = _format_duration_ms(payload)
    if duration_ms is None:
        return MediaCheck(MediaStatus.INVALID, None, "视频时长为 0 或不可读")

    if deep:
        decoded = _decode_ok(path, settings)
        if decoded is None:
            return MediaCheck(MediaStatus.UNAVAILABLE, None, "ffmpeg 不可用，无法解码校验视频")
        if not decoded:
            return MediaCheck(MediaStatus.INVALID, None, "视频解码失败")

    has_audio = any(s.get("codec_type") == "audio" for s in payload.get("streams") or [])
    return MediaCheck(
        MediaStatus.OK,
        VideoProbe(duration_ms=duration_ms, width=width, height=height, fps=fps, has_audio=has_audio),
    )


def probe_audio(path: Path, settings: Settings, *, deep: bool = False) -> AudioProbe | None:
    check = validate_audio(path, settings, deep=deep)
    return check.probe if check.ok and isinstance(check.probe, AudioProbe) else None


def probe_video(path: Path, settings: Settings, *, deep: bool = False) -> VideoProbe | None:
    check = validate_video(path, settings, deep=deep)
    return check.probe if check.ok and isinstance(check.probe, VideoProbe) else None


def probe_duration_ms(path: Path, settings: Settings) -> int | None:
    probe = probe_audio(path, settings) or probe_video(path, settings)
    return probe.duration_ms if probe else None
