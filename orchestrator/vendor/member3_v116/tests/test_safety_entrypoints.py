"""独立入口的安全检查：TTS / Video 单独调用也不能绕过。"""

from __future__ import annotations

import asyncio
import json

import pytest

from agents.generation.config import Settings
from agents.generation.errors import AppError, ErrorCode
from agents.generation.story.builder import build_page_story
from agents.generation.storage import PageFiles
from agents.generation.tts.api import TTSRequest, synthesize_tts
from agents.generation.tts.client import TTSClient
from agents.generation.tts.service import create_app
from agents.generation.video import compose_video

BLOCKED_TERM = "打架"


def _guarded(settings: Settings) -> Settings:
    return settings.replace(safety_enabled=True, safety_blocklist=(BLOCKED_TERM,))


class _StubRequest:
    def __init__(self, app):
        self.app = app


def test_tts_client_blocks_unsafe_text(media_settings: Settings):
    with pytest.raises(AppError) as info:
        TTSClient(_guarded(media_settings)).synthesize("小兔子们在森林里打架。")
    assert info.value.code == ErrorCode.SAFETY_BLOCKED
    assert "TTS 输入" in info.value.msg


def test_tts_client_allows_safe_text(media_settings: Settings):
    call = TTSClient(_guarded(media_settings)).synthesize("小兔子们在森林里散步。")
    assert call.audio_path.is_file()


def test_a6_route_blocks_unsafe_text(media_settings: Settings):
    app = create_app(_guarded(media_settings))
    response = asyncio.run(
        synthesize_tts(_StubRequest(app), TTSRequest(text="小兔子们在森林里打架。"))
    )
    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["code"] == 3004
    assert payload["data"] is None


def test_video_entry_blocks_unsafe_story(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict
):
    story = build_page_story("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=sample_vlm).doc
    story["segments"][0]["narration"] = "小兔子们在森林里打架。"
    settings = _guarded(media_settings)

    with pytest.raises(AppError) as info:
        compose_video("book01_p03", story, settings)

    assert info.value.code == ErrorCode.SAFETY_BLOCKED
    assert "视频输入" in info.value.msg
    assert not (settings.json_dir / "book01_p03_video.json").is_file()
    assert not PageFiles(settings, "book01_p03").video.exists()


def test_video_entry_rejects_foreign_highlight(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict
):
    story = build_page_story("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=sample_vlm).doc
    story["segments"][0]["highlight_object_ids"] = ["book99_p09_o01"]

    with pytest.raises(AppError) as info:
        compose_video("book01_p03", story, media_settings)

    assert info.value.code == ErrorCode.UNEXPECTED, "越页引用应判契约不合法"
    assert not (media_settings.json_dir / "book01_p03_video.json").is_file()


def test_video_entry_rejects_wrong_page_id(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict
):
    story = build_page_story("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=sample_vlm).doc

    with pytest.raises(AppError) as info:
        compose_video("book01_p07", story, media_settings)

    assert info.value.code == ErrorCode.VIDEO_FAILED
