"""Pydantic 模型：story.json（C3）与 video.json（C4）。

冻结规则（§1.2.5 / §1.2.6）：
  - 顶层必带 schema_version = "1.0"；
  - 消费方必须忽略未知字段，因此模型一律 extra="allow"，导出的 JSON Schema 里
    additionalProperties 永远是 true（禁止 false）；
  - 枚举全部 lower_snake_case 字符串。

这些模型只做“产物自检”，不做请求校验；请求校验在 tts/api.py。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ids import OBJECT_ID_RE, SEGMENT_ID_RE, book_id_of, is_page_id, page_no_of

SCHEMA_VERSION = "1.0"

#: TTS 单次请求上限（§1.10），逐段旁白必须留出余量，否则故事生成出来也念不了。
MAX_NARRATION_CHARS = 120
DURATION_TOLERANCE_SEC = 0.1


class _Model(BaseModel):
    # 忽略未知字段（契约要求），同时保留它们以便调试时能 dump 回去
    model_config = ConfigDict(extra="allow", protected_namespaces=(), str_strip_whitespace=False)


class ModelInfo(_Model):
    name: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)


class StorySegment(_Model):
    segment_id: str = Field(pattern=SEGMENT_ID_RE.pattern)
    order: int = Field(ge=1, le=99)
    narration: str = Field(min_length=1, max_length=MAX_NARRATION_CHARS)
    scene: str = Field(default="", max_length=400)
    image_prompt: str | None = Field(default=None, max_length=600)
    duration_sec: float = Field(gt=0)
    duration_source: Literal["tts", "estimate"]
    audio_url: str | None = None
    highlight_object_ids: list[str] | None = None

    @field_validator("highlight_object_ids")
    @classmethod
    def _check_object_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        for item in value:
            if not OBJECT_ID_RE.match(item):
                raise ValueError(f"object_id 格式非法: {item!r}")
        return value

    @model_validator(mode="after")
    def _audio_rule(self) -> "StorySegment":
        if self.duration_source == "tts" and not self.audio_url:
            raise ValueError("duration_source=tts 时 audio_url 必填（C3 字段表）")
        return self


class StoryDoc(_Model):
    schema_version: Literal["1.0"]
    book_id: str
    page_id: str
    page_no: int = Field(ge=1, le=99)
    title: str = Field(min_length=1, max_length=80)
    age_level: Literal["3-6", "6-9"]
    status: Literal["ok", "failed"]
    segments: list[StorySegment] = Field(min_length=1, max_length=20)
    total_duration_sec: float = Field(gt=0)
    safety_pass: bool
    safety_flags: list[str]
    model: ModelInfo
    elapsed_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_structure(self) -> "StoryDoc":
        if not is_page_id(self.page_id):
            raise ValueError(f"page_id 格式非法: {self.page_id!r}")
        if self.book_id != book_id_of(self.page_id):
            raise ValueError("book_id 与 page_id 不一致")
        if self.page_no != page_no_of(self.page_id):
            raise ValueError("page_no 与 page_id 不一致")

        expected_orders = list(range(1, len(self.segments) + 1))
        if [seg.order for seg in self.segments] != expected_orders:
            raise ValueError("segments[].order 必须是 1..n 连续递增")
        ids = [seg.segment_id for seg in self.segments]
        if len(set(ids)) != len(ids):
            raise ValueError("segment_id 必须全局唯一")
        prefix = f"{self.page_id}_s"
        for seg in self.segments:
            if not seg.segment_id.startswith(prefix):
                raise ValueError(f"segment_id 必须以 {prefix} 开头: {seg.segment_id}")

        total = sum(seg.duration_sec for seg in self.segments)
        if abs(total - self.total_duration_sec) > DURATION_TOLERANCE_SEC:
            raise ValueError(
                f"total_duration_sec({self.total_duration_sec}) 与分段之和({total:.3f}) 不一致"
            )
        return self

    @classmethod
    def from_dict(cls, data: dict) -> "StoryDoc":
        return cls.model_validate(data)


class VideoSegment(_Model):
    segment_id: str = Field(pattern=SEGMENT_ID_RE.pattern)
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)

    @model_validator(mode="after")
    def _order(self) -> "VideoSegment":
        if self.end_sec <= self.start_sec:
            raise ValueError("end_sec 必须大于 start_sec")
        return self


class VideoDoc(_Model):
    schema_version: Literal["1.0"]
    book_id: str
    page_id: str
    page_no: int = Field(ge=1, le=99)
    status: Literal["ok", "failed"]
    video_url: str | None = None
    duration_sec: float = Field(gt=0)
    resolution: str = Field(pattern=r"^\d{3,4}x\d{3,4}$")
    fps: int = Field(ge=1, le=120)
    segments: list[VideoSegment] = Field(min_length=1)
    elapsed_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_structure(self) -> "VideoDoc":
        if not is_page_id(self.page_id):
            raise ValueError(f"page_id 格式非法: {self.page_id!r}")
        if self.book_id != book_id_of(self.page_id):
            raise ValueError("book_id 与 page_id 不一致")
        if self.page_no != page_no_of(self.page_id):
            raise ValueError("page_no 与 page_id 不一致")
        if self.status == "ok" and not self.video_url:
            raise ValueError("status=ok 时 video_url 必填")

        previous_end = 0.0
        for seg in self.segments:
            if abs(seg.start_sec - previous_end) > DURATION_TOLERANCE_SEC:
                raise ValueError("video segments 必须首尾相接且从 0 开始")
            previous_end = seg.end_sec
        if abs(previous_end - self.duration_sec) > DURATION_TOLERANCE_SEC:
            raise ValueError("duration_sec 必须等于最后一段的 end_sec")
        return self

    @classmethod
    def from_dict(cls, data: dict) -> "VideoDoc":
        return cls.model_validate(data)


def validate_story(data: dict) -> StoryDoc:
    return StoryDoc.model_validate(data)


def validate_video(data: dict) -> VideoDoc:
    return VideoDoc.model_validate(data)


def export_json_schemas(out_dir: Path) -> list[Path]:
    """导出 JSON Schema 供成员 1/5 对齐（additionalProperties 必须为 true）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, model in (("story.schema.json", StoryDoc), ("video.schema.json", VideoDoc)):
        schema = model.model_json_schema()
        schema.setdefault("additionalProperties", True)
        path = out_dir / name
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written
