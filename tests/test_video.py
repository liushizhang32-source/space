from __future__ import annotations

import pytest

from agents.generation.config import Settings
from agents.generation.errors import VideoError
from agents.generation.schemas import VideoDoc
from agents.generation.story.builder import build_page_story
from agents.generation.video import compose_video


def _build_story(settings: Settings, ocr: dict, vlm: dict) -> dict:
    return build_page_story("book01_p03", "3-6", settings, ocr=ocr, vlm=vlm).doc


def test_compose_video_end_to_end(media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict):
    story = _build_story(media_settings, sample_ocr, sample_vlm)
    result = compose_video("book01_p03", story, media_settings)

    assert result.path.is_file() and result.path.stat().st_size > 0
    doc = VideoDoc.model_validate(result.doc)
    assert doc.status == "ok"
    assert doc.resolution == f"{media_settings.video_width}x{media_settings.video_height}"
    assert doc.fps == media_settings.video_fps
    assert doc.segments[0].start_sec == 0
    assert abs(doc.segments[-1].end_sec - doc.duration_sec) < 0.01
    assert abs(doc.duration_sec - story["total_duration_sec"]) < 0.2
    assert (media_settings.json_dir / "book01_p03_video.json").is_file()


def test_silent_video_when_tts_failed(media_settings: Settings, page_image, sample_vlm: dict):
    story = {
        "schema_version": "1.0",
        "book_id": "book01",
        "page_id": "book01_p03",
        "page_no": 3,
        "title": "静音测试",
        "age_level": "3-6",
        "status": "ok",
        "segments": [
            {
                "segment_id": "book01_p03_s01",
                "order": 1,
                "narration": "没有配音的一段。",
                "scene": "画面",
                "duration_sec": 2.0,
                "duration_source": "estimate",
            }
        ],
        "total_duration_sec": 2.0,
        "safety_pass": True,
        "safety_flags": [],
        "model": {"name": "mock-template", "version": "1.0"},
        "elapsed_ms": 10,
    }
    result = compose_video("book01_p03", story, media_settings)
    assert result.path.is_file()
    assert 1.8 <= result.doc["duration_sec"] <= 2.4


def test_missing_source_image_raises(media_settings: Settings, sample_ocr: dict, sample_vlm: dict):
    story = _build_story(media_settings, sample_ocr, sample_vlm)
    with pytest.raises(VideoError):
        compose_video("book01_p07", story, media_settings)


def test_retry_once_then_fail(media_settings: Settings, page_image, monkeypatch, sample_ocr: dict, sample_vlm: dict):
    story = _build_story(media_settings, sample_ocr, sample_vlm)
    settings = media_settings.replace(max_retry=1, retry_backoff_sec=0.0)
    calls = {"n": 0}

    def boom(*args, **kwargs):
        calls["n"] += 1
        raise VideoError("故意失败")

    monkeypatch.setattr("agents.generation.video._render_once", boom)
    with pytest.raises(VideoError):
        compose_video("book01_p03", story, settings)
    assert calls["n"] == 2, "契约要求 Video 重试 1 次"


def test_video_json_not_written_on_failure(media_settings: Settings, monkeypatch, sample_ocr: dict, sample_vlm: dict):
    story = _build_story(media_settings, sample_ocr, sample_vlm)
    settings = media_settings.replace(max_retry=0)

    def boom(*args, **kwargs):
        raise VideoError("故意失败")

    monkeypatch.setattr("agents.generation.video._render_once", boom)
    with pytest.raises(VideoError):
        compose_video("book01_p03", story, settings)
    assert not (settings.json_dir / "book01_p03_video.json").is_file()
