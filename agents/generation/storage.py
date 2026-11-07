"""存储：DATA_DIR 下的文件布局（对齐 API v1.0 §1.15）。

  json/{page_id}_{ocr|vlm|story|video}.json
  audios/tts_{sha1_12}.mp3
  videos/{page_id}_video.mp4
  uploads/{page_id}_orig.{jpg|png|webp}
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .config import Settings


@dataclass(frozen=True)
class PageFiles:
    settings: Settings
    page_id: str

    @property
    def ocr(self) -> Path:
        return self.settings.json_dir / f"{self.page_id}_ocr.json"

    @property
    def vlm(self) -> Path:
        return self.settings.json_dir / f"{self.page_id}_vlm.json"

    @property
    def story(self) -> Path:
        return self.settings.json_dir / f"{self.page_id}_story.json"

    @property
    def video_json(self) -> Path:
        return self.settings.json_dir / f"{self.page_id}_video.json"

    @property
    def video(self) -> Path:
        return self.settings.videos_dir / f"{self.page_id}_video.mp4"

    def audio(self, cache_key: str, fmt: str = "mp3") -> Path:
        return self.settings.audios_dir / f"tts_{cache_key}.{fmt}"

    def source_image(self) -> Path | None:
        for ext in ("jpg", "jpeg", "png", "webp"):
            candidate = self.settings.uploads_dir / f"{self.page_id}_orig.{ext}"
            if candidate.is_file():
                return candidate
        return None


def read_json(path: Path) -> dict | None:
    """读 JSON；文件不存在或损坏都返回 None（由调用方决定降级方式）。"""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_json(path: Path, data: dict) -> None:
    """原子写：先写 .tmp 再 os.replace，避免中枢/评测读到半个文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def asset_url(settings: Settings, path: Path) -> str:
    """相对路径存盘、绝对 URL 出接口（§1.15 规则 3）。

    JSON 产物里的 audio_url / video_url 写绝对 URL，因为成员 5 直接读 json/ 做评测。
    """
    try:
        rel = path.resolve().relative_to(settings.data_dir.resolve())
    except ValueError:
        rel = Path(path.name)
    return f"{settings.asset_base_url}/{rel.as_posix()}"


def rel_path(settings: Settings, path: Path) -> str:
    try:
        return path.resolve().relative_to(settings.data_dir.resolve()).as_posix()
    except ValueError:
        return path.name
