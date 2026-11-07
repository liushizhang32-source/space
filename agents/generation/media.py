"""音视频探测：ffprobe 封装，失败返回 None 由调用方决定降级。"""

from __future__ import annotations

from pathlib import Path

from .config import Settings
from .proc import run


def probe_duration_ms(path: Path, settings: Settings) -> int | None:
    ffprobe = settings.ffprobe
    if not ffprobe or not path.is_file():
        return None
    proc = run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        timeout=20,
    )
    if proc.returncode != 0:
        return None
    raw = (proc.stdout or b"").decode("utf-8", "replace").strip()
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return int(round(seconds * 1000))


def probe_sample_rate(path: Path, settings: Settings) -> int | None:
    ffprobe = settings.ffprobe
    if not ffprobe or not path.is_file():
        return None
    proc = run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        timeout=20,
    )
    if proc.returncode != 0:
        return None
    raw = (proc.stdout or b"").decode("utf-8", "replace").strip()
    try:
        return int(raw)
    except ValueError:
        return None
