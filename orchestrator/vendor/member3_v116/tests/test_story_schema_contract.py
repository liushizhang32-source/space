"""Story 模型 ↔ 导出的 JSON Schema ↔ 契约字段 三者一致性。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.generation.schemas import StoryDoc, export_json_schemas

ROOT = Path(__file__).resolve().parents[1]

#: C3 契约里的顶层字段（§1.12 C3 + 字段表）
CONTRACT_FIELDS = {
    "schema_version",
    "book_id",
    "page_id",
    "page_no",
    "title",
    "age_level",
    "status",
    "segments",
    "total_duration_sec",
    "safety_pass",
    "safety_flags",
    "model",
    "elapsed_ms",
}

#: required 字段；safety_flags 与公共模型一样有默认 []
REQUIRED_FIELDS = CONTRACT_FIELDS - {"safety_flags"}

SEGMENT_FIELDS = {
    "segment_id",
    "order",
    "narration",
    "scene",
    "image_prompt",
    "duration_sec",
    "duration_source",
    "audio_url",
    "highlight_object_ids",
}


def test_exported_schema_matches_model(tmp_path: Path):
    """导出文件必须与当前模型完全一致，不能是历史残留。"""
    written = export_json_schemas(tmp_path)
    fresh = json.loads((tmp_path / "story.schema.json").read_text(encoding="utf-8"))
    committed = json.loads((ROOT / "docs" / "schemas" / "story.schema.json").read_text(encoding="utf-8"))
    assert fresh == committed, "docs/schemas/story.schema.json 过期，请重新导出"
    assert {p.name for p in written} == {"story.schema.json", "video.schema.json"}


def test_schema_top_level_fields_match_contract():
    schema = StoryDoc.model_json_schema()
    assert set(schema["properties"]) == CONTRACT_FIELDS
    assert set(schema["required"]) == REQUIRED_FIELDS
    assert schema.get("additionalProperties") is True


def test_schema_segment_fields_match_contract():
    schema = StoryDoc.model_json_schema()
    segment = schema["$defs"]["StorySegment"]
    assert set(segment["properties"]) == SEGMENT_FIELDS
    assert segment.get("additionalProperties") is True
    assert segment["properties"]["scene"]["minLength"] == 1


def test_schema_version_is_frozen_to_1_0():
    schema = StoryDoc.model_json_schema()
    version_schema = schema["properties"]["schema_version"]
    assert version_schema.get("const") == "1.0"


def test_highlight_object_must_belong_to_page():
    doc = {
        "schema_version": "1.0",
        "book_id": "book01",
        "page_id": "book01_p03",
        "page_no": 3,
        "title": "越页引用",
        "age_level": "3-6",
        "status": "ok",
        "segments": [
            {
                "segment_id": "book01_p03_s01",
                "order": 1,
                "narration": "一句话。",
                "scene": "画面",
                "duration_sec": 2.0,
                "duration_source": "tts",
                "audio_url": "http://test.local/audios/x.mp3",
                "highlight_object_ids": ["book99_p09_o01"],
            }
        ],
        "total_duration_sec": 2.0,
        "safety_pass": True,
        "safety_flags": [],
        "model": {"name": "mock-template", "version": "1.0"},
        "elapsed_ms": 10,
    }
    with pytest.raises(ValidationError) as info:
        StoryDoc.model_validate(doc)
    assert "highlight_object_ids" in str(info.value)
