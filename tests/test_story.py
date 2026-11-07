from __future__ import annotations

from pathlib import Path

import pytest

from agents.generation.config import Settings
from agents.generation.errors import AppError, ErrorCode, StoryInputError
from agents.generation.schemas import StoryDoc
from agents.generation.story.builder import build_page_story
from agents.generation.tts.client import TTSClient
from agents.generation.tts.engine import estimate_duration_sec


class FailingEngine:
    name = "failing"

    def synthesize(self, *args, **kwargs):
        from agents.generation.errors import TTSFailed

        raise TTSFailed("合成失败")


def test_story_ok_path(media_settings: Settings, sample_ocr: dict, sample_vlm: dict):
    result = build_page_story("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=sample_vlm)
    doc = StoryDoc.model_validate(result.doc)

    assert doc.schema_version == "1.0"
    assert doc.page_id == "book01_p03" and doc.page_no == 3
    assert doc.book_id == "book01"
    assert [seg.order for seg in doc.segments] == [1, 2]
    assert [seg.segment_id for seg in doc.segments] == ["book01_p03_s01", "book01_p03_s02"]
    assert result.degraded == []
    assert result.model_name == "mock-template"
    assert all(seg.duration_source == "tts" for seg in doc.segments)
    assert all(seg.audio_url for seg in doc.segments)
    assert abs(doc.total_duration_sec - sum(s.duration_sec for s in doc.segments)) < 0.01
    assert (media_settings.json_dir / "book01_p03_story.json").is_file()


def test_narration_never_exceeds_tts_limit(media_settings: Settings, sample_vlm: dict):
    long_text = "这是一句很长很长的绘本文字，" * 20
    ocr = {
        "status": "ok",
        "text_blocks": [{"order": 1, "text": long_text}],
    }
    result = build_page_story("book01_p03", "3-6", media_settings, ocr=ocr, vlm=sample_vlm)
    assert all(len(seg["narration"]) <= 120 for seg in result.doc["segments"])
    assert len(result.doc["segments"]) > 1


def test_ocr_failed_but_vlm_ok_degrades_to_no_ocr(media_settings: Settings, sample_vlm: dict):
    result = build_page_story("book01_p03", "3-6", media_settings, ocr={"status": "failed"}, vlm=sample_vlm)
    assert result.degraded == ["no_ocr"]
    assert result.doc["segments"]
    assert "兔子" in "".join(seg["narration"] for seg in result.doc["segments"])


def test_vlm_failed_but_ocr_ok_degrades_to_no_scene(media_settings: Settings, sample_ocr: dict):
    result = build_page_story("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm={"status": "failed"})
    assert result.degraded == ["no_scene"]
    assert "小兔子" in result.doc["segments"][0]["narration"]


def test_wordless_page_is_not_a_failure(media_settings: Settings, sample_vlm: dict):
    result = build_page_story("book01_p03", "3-6", media_settings, ocr={"status": "empty"}, vlm=sample_vlm)
    assert result.degraded == []
    assert result.doc["status"] == "ok"


def test_both_inputs_missing_raises_3001(media_settings: Settings):
    with pytest.raises(StoryInputError) as info:
        build_page_story("book01_p03", "3-6", media_settings, ocr=None, vlm=None)
    assert info.value.code == ErrorCode.OCR_EMPTY


def test_highlight_ids_only_reference_existing_objects(
    media_settings: Settings, sample_ocr: dict, sample_vlm: dict
):
    result = build_page_story("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=sample_vlm)
    valid = {obj["object_id"] for obj in sample_vlm["objects"]}
    for segment in result.doc["segments"]:
        for object_id in segment.get("highlight_object_ids", []):
            assert object_id in valid


def test_tts_failure_falls_back_to_estimate(media_settings: Settings, sample_ocr: dict, sample_vlm: dict):
    client = TTSClient(media_settings, engine=FailingEngine())
    result = build_page_story(
        "book01_p03", "3-6", media_settings, tts_client=client, ocr=sample_ocr, vlm=sample_vlm
    )
    assert "no_audio" in result.degraded
    for segment in result.doc["segments"]:
        assert segment["duration_source"] == "estimate"
        assert "audio_url" not in segment
        expected = estimate_duration_sec(segment["narration"])
        assert abs(segment["duration_sec"] - expected) < 0.05


def test_safety_block_raises_3004(media_settings: Settings, sample_ocr: dict, sample_vlm: dict):
    settings = media_settings.replace(safety_enabled=True, safety_blocklist=("兔子",))
    with pytest.raises(AppError) as info:
        build_page_story("book01_p03", "3-6", settings, ocr=sample_ocr, vlm=sample_vlm)
    assert info.value.code == ErrorCode.SAFETY_BLOCKED


def test_invalid_age_level_returns_1002(media_settings: Settings, sample_ocr: dict, sample_vlm: dict):
    with pytest.raises(AppError) as info:
        build_page_story("book01_p03", "0-3", media_settings, ocr=sample_ocr, vlm=sample_vlm)
    assert info.value.code == ErrorCode.INVALID_PARAM


def _llm_settings(settings: Settings) -> Settings:
    return settings.replace(
        llm_base_url="http://127.0.0.1:9",  # 必然连不上的端口
        llm_model="test-model",
        llm_api_key="test-key",
        max_retry=0,
        story_timeout_sec=1,
    )


def test_vlm_safety_false_blocks_page(media_settings: Settings, sample_ocr: dict, sample_vlm: dict):
    vlm = dict(sample_vlm, safety={"pass": False, "flags": ["violence"]})
    with pytest.raises(AppError) as info:
        build_page_story("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=vlm)
    assert info.value.code == ErrorCode.SAFETY_BLOCKED
    assert not (media_settings.json_dir / "book01_p03_story.json").is_file()


def test_llm_unreachable_fails_without_writing_story(
    media_settings: Settings, sample_ocr: dict, sample_vlm: dict
):
    settings = _llm_settings(media_settings)
    with pytest.raises(AppError) as info:
        build_page_story("book01_p03", "3-6", settings, ocr=sample_ocr, vlm=sample_vlm)
    assert int(info.value.code) in (2001, 2002)
    assert not (settings.json_dir / "book01_p03_story.json").is_file(), "故事失败不该留半成品"


def test_llm_failure_can_fall_back_to_template(
    media_settings: Settings, sample_ocr: dict, sample_vlm: dict
):
    settings = _llm_settings(media_settings).replace(story_fallback_on_error=True)
    result = build_page_story("book01_p03", "3-6", settings, ocr=sample_ocr, vlm=sample_vlm)
    assert result.model_name == "mock-template"
    assert (settings.json_dir / "book01_p03_story.json").is_file()
