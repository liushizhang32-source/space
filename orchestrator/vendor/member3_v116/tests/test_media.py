"""产物有效性校验：三态（ok / invalid / unavailable）与“缺 ffmpeg 不得算通过”。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.generation.config import Settings
from agents.generation.errors import AppError, ErrorCode, VideoError
from agents.generation.media import MediaStatus, probe_audio, probe_video, validate_audio, validate_video
from agents.generation.story.builder import build_page_story
from agents.generation.tts.client import TTSClient
from agents.generation.video import compose_video


def test_probe_audio_accepts_generated_mp3(media_settings: Settings):
    call = TTSClient(media_settings).synthesize("校验用的一句话。")
    probe = probe_audio(call.audio_path, media_settings, deep=True)

    assert probe is not None
    assert probe.codec == "mp3"
    assert probe.sample_rate == media_settings.tts_sample_rate
    assert probe.channels == 1
    assert probe.duration_ms > 0


def test_probe_audio_rejects_text_file(media_settings: Settings):
    fake = media_settings.audios_dir / "tts_deadbeef0000.mp3"
    fake.write_text("这不是音频", encoding="utf-8")
    check = validate_audio(fake, media_settings)
    assert check.status is MediaStatus.INVALID
    assert "没有音频流" in check.reason or "无法解析" in check.reason


def test_probe_audio_rejects_empty_file(media_settings: Settings):
    fake = media_settings.audios_dir / "tts_000000000000.mp3"
    fake.write_bytes(b"")
    assert validate_audio(fake, media_settings).status is MediaStatus.INVALID


def test_probe_audio_rejects_missing_file(media_settings: Settings):
    check = validate_audio(media_settings.audios_dir / "nope.mp3", media_settings)
    assert check.status is MediaStatus.INVALID


def test_probe_video_rejects_non_video(media_settings: Settings):
    fake = media_settings.videos_dir / "broken.mp4"
    fake.write_bytes(b"not a video at all")
    check = validate_video(fake, media_settings)
    assert check.status is MediaStatus.INVALID
    assert check.probe is None


def test_deep_audio_check_is_unavailable_without_ffmpeg(media_settings: Settings):
    call = TTSClient(media_settings).synthesize("深检需要 ffmpeg。")
    settings = media_settings.replace(ffmpeg_path="definitely-missing-ffmpeg")

    check = validate_audio(call.audio_path, settings, deep=True)
    assert check.status is MediaStatus.UNAVAILABLE, "缺 ffmpeg 不能被判定为验证成功"
    assert check.probe is None
    assert "ffmpeg" in check.reason


def test_deep_video_check_is_unavailable_without_ffmpeg(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict
):
    story = build_page_story("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=sample_vlm).doc
    result = compose_video("book01_p03", story, media_settings)
    settings = media_settings.replace(ffmpeg_path="definitely-missing-ffmpeg")

    check = validate_video(result.path, settings, deep=True)
    assert check.status is MediaStatus.UNAVAILABLE
    assert check.probe is None


def test_tts_without_ffmpeg_returns_2004(media_settings: Settings):
    settings = media_settings.replace(ffmpeg_path="definitely-missing-ffmpeg")

    with pytest.raises(AppError) as info:
        TTSClient(settings).synthesize("没有 ffmpeg。")
    assert info.value.code == ErrorCode.UNAVAILABLE


def test_video_without_ffmpeg_fails(media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict):
    story = build_page_story("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=sample_vlm).doc
    settings = media_settings.replace(ffmpeg_path="definitely-missing-ffmpeg", max_retry=0)

    with pytest.raises(VideoError):
        compose_video("book01_p03", story, settings)
