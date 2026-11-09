from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI

from agents.generation.config import Settings
from agents.generation.errors import AppError, ErrorCode, TTSFailed, TTSUnavailable
from agents.generation.tts.api import TTSRequest, synthesize_tts
from agents.generation.tts.client import TTSClient
from agents.generation.tts.engine import estimate_duration_sec
from agents.generation.tts.service import create_app


class FailingEngine:
    name = "failing"

    def synthesize(self, *args, **kwargs):
        raise TTSFailed("合成失败")


def test_missing_text_returns_1001(settings: Settings):
    with pytest.raises(AppError) as info:
        TTSClient(settings).synthesize(None)
    assert info.value.code == ErrorCode.MISSING_PARAM


def test_blank_text_returns_1001(settings: Settings):
    with pytest.raises(AppError) as info:
        TTSClient(settings).synthesize("   ")
    assert info.value.code == ErrorCode.MISSING_PARAM


def test_text_over_120_chars_returns_1002(settings: Settings):
    with pytest.raises(AppError) as info:
        TTSClient(settings).synthesize("字" * 121)
    assert info.value.code == ErrorCode.INVALID_PARAM


@pytest.mark.parametrize("speed", [0.4, 2.1])
def test_speed_out_of_range_returns_1002(settings: Settings, speed: float):
    with pytest.raises(AppError) as info:
        TTSClient(settings).synthesize("你好", speed=speed)
    assert info.value.code == ErrorCode.INVALID_PARAM


def test_unknown_format_returns_1002(settings: Settings):
    with pytest.raises(AppError) as info:
        TTSClient(settings).synthesize("你好", fmt="ogg")
    assert info.value.code == ErrorCode.INVALID_PARAM


def test_silent_engine_writes_file_and_measures(media_settings: Settings):
    client = TTSClient(media_settings)
    call = client.synthesize("从前有只小兔子，住在森林边上。")
    assert call.audio_path.is_file()
    assert call.audio_path.name.startswith("tts_") and call.audio_path.suffix == ".mp3"
    assert call.duration_source == "tts"
    assert abs(call.duration_ms / 1000 - estimate_duration_sec(call.text)) < 0.2
    assert call.audio_url.startswith(media_settings.asset_base_url + "/audios/")


def test_second_call_hits_content_hash_cache(media_settings: Settings):
    client = TTSClient(media_settings)
    first = client.synthesize("同一句话")
    second = client.synthesize("同一句话")
    assert first.cached is False
    assert second.cached is True
    assert first.audio_path == second.audio_path
    assert len(list(media_settings.audios_dir.glob("tts_*.mp3"))) == 1


def test_different_speed_produces_different_file(media_settings: Settings):
    client = TTSClient(media_settings)
    normal = client.synthesize("同一句话")
    faster = client.synthesize("同一句话", speed=1.4)
    assert normal.audio_path != faster.audio_path
    assert faster.duration_ms < normal.duration_ms


def test_engine_failure_maps_to_3008(media_settings: Settings):
    client = TTSClient(media_settings, engine=FailingEngine())
    with pytest.raises(AppError) as info:
        client.synthesize("你好")
    assert info.value.code == ErrorCode.TTS_FAILED


def test_missing_ffmpeg_maps_to_2004(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        ffmpeg_path="definitely-not-an-ffmpeg",
        ffprobe_path="definitely-not-an-ffprobe",
        tts_engine="silent",
    )
    settings.ensure_dirs()
    with pytest.raises(TTSUnavailable) as info:
        TTSClient(settings).synthesize("你好")
    assert info.value.code == ErrorCode.UNAVAILABLE


class _StubRequest:
    def __init__(self, app: FastAPI):
        self.app = app


def _call(app: FastAPI, body: TTSRequest) -> dict:
    response = asyncio.run(synthesize_tts(_StubRequest(app), body))
    assert response.status_code == 200, "统一响应必须 HTTP 200"
    return json.loads(response.body)


def test_api_success_envelope(media_settings: Settings):
    app = create_app(media_settings)
    payload = _call(app, TTSRequest(text="你好，小朋友。"))
    assert payload["code"] == 0
    assert payload["msg"] == "ok"
    assert set(payload["data"]) == {"audio_url", "duration_ms", "sample_rate"}
    assert payload["trace_id"].startswith("tr_")


def test_api_missing_text_envelope(media_settings: Settings):
    app = create_app(media_settings)
    payload = _call(app, TTSRequest(text=None))
    assert payload["code"] == 1001 and payload["data"] is None


def test_api_overlong_text_envelope(media_settings: Settings):
    app = create_app(media_settings)
    payload = _call(app, TTSRequest(text="字" * 200))
    assert payload["code"] == 1002


def test_api_engine_failure_envelope(media_settings: Settings):
    app = create_app(media_settings)
    app.state.tts_client = TTSClient(media_settings, engine=FailingEngine())
    payload = _call(app, TTSRequest(text="你好"))
    assert payload["code"] == 3008


def test_router_is_mounted_under_v1(media_settings: Settings):
    app = create_app(media_settings)
    assert "/api/v1/tts" in app.openapi()["paths"]
