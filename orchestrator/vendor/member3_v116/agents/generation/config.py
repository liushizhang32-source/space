"""配置：环境变量 -> Settings（对齐 API v1.0 §1.16）。

所有可调参数走环境变量，代码里不硬编码路径/密钥。
成员 3 关心的段落：LLM_* / TTS_* / FFMPEG_PATH / DATA_DIR / ASSET_BASE_URL，
另有本模块新增的 VIDEO_* / STORY_* / SAFETY_*（见 .env.example）。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from os import environ
from pathlib import Path
from typing import Mapping

DEFAULT_ASSET_BASE_URL = "http://127.0.0.1:8000"

#: Q4「1080×1920 还是 720×1280」未拍板。默认取建议值 720×1280（render 更快、演示更稳），
#: 需要 1080×1920 时只改 VIDEO_RESOLUTION，不动代码。
DEFAULT_VIDEO_RESOLUTION = "720x1280"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def load_dotenv(path: str | Path = ".env") -> int:
    """最简 .env 加载：仅补齐尚未存在的环境变量，不覆盖已有值。

    这样 README 里“复制 .env.example 为 .env”才真的生效；返回值是载入的键数。
    """
    candidate = Path(path)
    if not candidate.is_file():
        return 0
    loaded = 0
    for line in candidate.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


def _float(value: str | None, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    asset_base_url: str = DEFAULT_ASSET_BASE_URL

    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"

    video_width: int = 720
    video_height: int = 1280
    video_fps: int = 25
    video_timeout_sec: int = 180
    video_font: str = ""

    max_retry: int = 1          # §1.13：Video 重试 1 次，Story 重试 1 次
    retry_backoff_sec: float = 2.0

    tts_engine: str = "auto"    # auto | silent | http
    tts_http_url: str = ""
    tts_api_key: str = ""
    tts_voice_id: str = "female_warm"
    tts_speed: float = 1.0
    tts_sample_rate: int = 24000
    tts_timeout_sec: int = 20   # §1.13：TTS 单段 20s
    tts_max_audio_bytes: int = 10 * 1024 * 1024  # HTTP 音频响应上限，防超大文件

    story_timeout_sec: int = 60  # §1.13：Story 60s
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    story_fallback_on_error: bool = False

    safety_blocklist: tuple[str, ...] = ()
    safety_enabled: bool = False  # Q8：v1 开关默认关，字段与分支必须实现

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        e = environ if env is None else env
        resolution = (e.get("VIDEO_RESOLUTION") or DEFAULT_VIDEO_RESOLUTION).lower()
        try:
            width, height = (int(x) for x in resolution.split("x", 1))
            if width <= 0 or height <= 0:
                raise ValueError
        except ValueError as exc:
            raise ValueError(f"VIDEO_RESOLUTION 格式应为 宽x高，例如 720x1280，收到 {resolution!r}") from exc

        blocklist = tuple(
            item.strip() for item in (e.get("SAFETY_BLOCKLIST") or "").split(",") if item.strip()
        )
        return cls(
            data_dir=Path(e.get("DATA_DIR") or "data"),
            asset_base_url=(e.get("ASSET_BASE_URL") or DEFAULT_ASSET_BASE_URL).rstrip("/"),
            ffmpeg_path=e.get("FFMPEG_PATH") or "ffmpeg",
            ffprobe_path=e.get("FFPROBE_PATH") or "ffprobe",
            video_width=width,
            video_height=height,
            video_fps=_int(e.get("VIDEO_FPS"), 25),
            video_timeout_sec=_int(e.get("VIDEO_TIMEOUT_SEC"), 180),
            video_font=e.get("VIDEO_FONT") or "",
            max_retry=_int(e.get("MAX_RETRY"), 1),
            tts_engine=(e.get("TTS_ENGINE") or "auto").strip().lower(),
            tts_http_url=(e.get("TTS_HTTP_URL") or "").strip(),
            tts_api_key=(e.get("TTS_API_KEY") or "").strip(),
            tts_voice_id=e.get("TTS_VOICE_ID") or "female_warm",
            tts_speed=_float(e.get("TTS_SPEED"), 1.0),
            tts_sample_rate=_int(e.get("TTS_SAMPLE_RATE"), 24000),
            tts_timeout_sec=_int(e.get("TTS_TIMEOUT_SEC"), 20),
            tts_max_audio_bytes=_int(e.get("TTS_MAX_AUDIO_BYTES"), 10 * 1024 * 1024),
            story_timeout_sec=_int(e.get("STORY_TIMEOUT_SEC"), 60),
            llm_base_url=(e.get("LLM_BASE_URL") or "").strip(),
            llm_api_key=(e.get("LLM_API_KEY") or "").strip(),
            llm_model=(e.get("LLM_MODEL") or "").strip(),
            story_fallback_on_error=_truthy(e.get("STORY_FALLBACK_ON_ERROR")),
            safety_blocklist=blocklist,
            safety_enabled=_truthy(e.get("SAFETY_ENABLED")),
        )

    # ---- 目录 ----
    @property
    def json_dir(self) -> Path:
        return self.data_dir / "json"

    @property
    def audios_dir(self) -> Path:
        return self.data_dir / "audios"

    @property
    def videos_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def ensure_dirs(self) -> None:
        for path in (
            self.json_dir,
            self.audios_dir,
            self.videos_dir,
            self.uploads_dir,
            self.logs_dir,
            self.tmp_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    # ---- 可执行文件 ----
    @staticmethod
    def _resolve(name_or_path: str) -> str | None:
        candidate = Path(name_or_path)
        if candidate.is_file():
            return str(candidate)
        return shutil.which(name_or_path)

    @property
    def ffmpeg(self) -> str | None:
        return self._resolve(self.ffmpeg_path)

    @property
    def ffprobe(self) -> str | None:
        return self._resolve(self.ffprobe_path)

    def replace(self, **kwargs) -> "Settings":
        from dataclasses import replace

        return replace(self, **kwargs)
