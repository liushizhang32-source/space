from __future__ import annotations

from agents.generation.config import Settings
from agents.generation.pipeline import run_page
from agents.generation.schemas import StoryDoc, VideoDoc
from agents.generation.tts.client import TTSClient


class FailingEngine:
    name = "failing"

    def synthesize(self, *args, **kwargs):
        from agents.generation.errors import TTSFailed

        raise TTSFailed("合成失败")


def test_run_page_done(media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict):
    result = run_page("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=sample_vlm)
    payload = result.to_dict()

    assert payload["status"] == "done"
    assert payload["degraded"] == []
    assert payload["video_url"].endswith("/videos/book01_p03_video.mp4")
    assert payload["story_url"].endswith("/json/book01_p03_story.json")
    assert payload["error"] is None

    story = (media_settings.json_dir / "book01_p03_story.json").read_text(encoding="utf-8")
    video = (media_settings.json_dir / "book01_p03_video.json").read_text(encoding="utf-8")
    StoryDoc.model_validate_json(story)
    VideoDoc.model_validate_json(video)


def test_run_page_without_video(media_settings: Settings, sample_ocr: dict, sample_vlm: dict):
    result = run_page("book01_p03", "3-6", media_settings, make_video=False, ocr=sample_ocr, vlm=sample_vlm)
    assert result.status == "done"
    assert result.video_url is None
    assert not (media_settings.json_dir / "book01_p03_video.json").is_file()


def test_run_page_no_audio_still_renders_video(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict
):
    client = TTSClient(media_settings, engine=FailingEngine())
    result = run_page("book01_p03", "3-6", media_settings, tts_client=client, ocr=sample_ocr, vlm=sample_vlm)
    assert result.status == "partial"
    assert "no_audio" in result.degraded
    assert result.video_url is not None, "TTS 挂了但视频要照出（静音+字幕）"


def test_run_page_video_failure_degrades_not_fails(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict
):
    settings = media_settings.replace(ffmpeg_path="definitely-not-ffmpeg", max_retry=0)
    result = run_page("book01_p03", "3-6", settings, ocr=sample_ocr, vlm=sample_vlm)
    assert result.status == "partial"
    assert "no_video" in result.degraded
    assert result.video_url is None
    assert result.story_url is not None, "视频失败时仍要返回图文分页数据"
    assert result.video_error and result.video_error["code"] == 3007


def test_run_page_failed_when_no_input(media_settings: Settings):
    result = run_page("book01_p03", "3-6", media_settings)
    assert result.status == "failed"
    assert result.error["code"] == 3001
    assert result.video_url is None
