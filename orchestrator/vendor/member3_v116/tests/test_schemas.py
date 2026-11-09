from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agents.generation.schemas import StoryDoc, VideoDoc, export_json_schemas


def _story(**overrides) -> dict:
    doc = {
        "schema_version": "1.0",
        "book_id": "book01",
        "page_id": "book01_p03",
        "page_no": 3,
        "title": "小兔子的冒险",
        "age_level": "3-6",
        "status": "ok",
        "segments": [
            {
                "segment_id": "book01_p03_s01",
                "order": 1,
                "narration": "从前有只小兔子，住在森林边上。",
                "scene": "夜晚的森林",
                "image_prompt": "night forest",
                "duration_sec": 4.0,
                "duration_source": "tts",
                "audio_url": "http://test.local/audios/tts_2e36d97e5cd9.mp3",
                "highlight_object_ids": ["book01_p03_o01"],
            }
        ],
        "total_duration_sec": 4.0,
        "safety_pass": True,
        "safety_flags": [],
        "model": {"name": "mock-template", "version": "1.0"},
        "elapsed_ms": 8600,
    }
    doc.update(overrides)
    return doc


def test_contract_story_example_passes():
    doc = StoryDoc.model_validate(_story())
    assert doc.page_no == 3
    assert doc.segments[0].segment_id == "book01_p03_s01"


def test_unknown_fields_are_ignored_not_rejected():
    """契约 §1.2.5：消费方必须忽略未知字段。"""
    doc = StoryDoc.model_validate(_story(future_field={"a": 1}))
    assert doc.page_no == 3


def test_page_no_must_match_page_id():
    with pytest.raises(ValidationError):
        StoryDoc.model_validate(_story(page_no=4))
    with pytest.raises(ValidationError):
        StoryDoc.model_validate(_story(page_id="book01-03"))


def test_narration_over_120_chars_rejected():
    segment = dict(_story()["segments"][0], narration="长" * 121)
    with pytest.raises(ValidationError):
        StoryDoc.model_validate(_story(segments=[segment], total_duration_sec=4.0))


def test_tts_duration_requires_audio_url():
    segment = dict(_story()["segments"][0])
    segment.pop("audio_url")
    with pytest.raises(ValidationError):
        StoryDoc.model_validate(_story(segments=[segment]))


def test_estimate_duration_may_omit_audio_url():
    segment = dict(_story()["segments"][0], duration_source="estimate")
    segment.pop("audio_url")
    doc = StoryDoc.model_validate(_story(segments=[segment], total_duration_sec=4.0))
    assert doc.segments[0].duration_source == "estimate"


def test_total_duration_must_equal_segments_sum():
    with pytest.raises(ValidationError):
        StoryDoc.model_validate(_story(total_duration_sec=9.0))


def test_orders_must_be_sequential():
    first = dict(_story()["segments"][0])
    second = dict(first, segment_id="book01_p03_s02", order=3)
    with pytest.raises(ValidationError):
        StoryDoc.model_validate(_story(segments=[first, second], total_duration_sec=8.0))


def _video(**overrides) -> dict:
    doc = {
        "schema_version": "1.0",
        "book_id": "book01",
        "page_id": "book01_p03",
        "page_no": 3,
        "status": "ok",
        "video_url": "http://test.local/videos/book01_p03_video.mp4",
        "duration_sec": 8.0,
        "resolution": "720x1280",
        "fps": 25,
        "segments": [
            {"segment_id": "book01_p03_s01", "start_sec": 0, "end_sec": 4},
            {"segment_id": "book01_p03_s02", "start_sec": 4, "end_sec": 8},
        ],
        "elapsed_ms": 128000,
    }
    doc.update(overrides)
    return doc


def test_video_contract_example_passes():
    assert VideoDoc.model_validate(_video()).fps == 25


def test_video_segments_must_be_contiguous():
    broken = [
        {"segment_id": "book01_p03_s01", "start_sec": 0, "end_sec": 3},
        {"segment_id": "book01_p03_s02", "start_sec": 4, "end_sec": 8},
    ]
    with pytest.raises(ValidationError):
        VideoDoc.model_validate(_video(segments=broken, duration_sec=8))


def test_video_ok_requires_url():
    with pytest.raises(ValidationError):
        VideoDoc.model_validate(_video(video_url=None))


def test_exported_schema_allows_additional_properties(tmp_path):
    for path in export_json_schemas(tmp_path):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema.get("additionalProperties") is True, path.name


def test_empty_scene_is_rejected():
    segment = dict(_story()["segments"][0], scene="   ")
    with pytest.raises(ValidationError):
        StoryDoc.model_validate(_story(segments=[segment]))