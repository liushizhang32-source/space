"""v1.1.3 回归：安全时序、Video 事务发布、HTTP JSON/base64、Story 模型对齐。"""

from __future__ import annotations

import socket
import urllib.error
from pathlib import Path

import pytest

from agents.generation.config import Settings
from agents.generation.errors import AppError, ErrorCode, TTSFailed, TTSUnavailable, VideoError
from agents.generation.media import AudioProbe
from pydantic import ValidationError

from agents.generation.schemas import StoryDoc, VideoDoc
from agents.generation.story.builder import build_page_story
from agents.generation.tts.engine import HttpEngine
from agents.generation.video import compose_video


class FakeResponse:
    def __init__(self, payload: bytes, *, content_type: str = "application/json"):
        self._payload = payload
        self._pos = 0
        self.status = 200
        self.headers = {"Content-Type": content_type}

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk, self._pos = self._payload[self._pos :], len(self._payload)
            return chunk
        chunk = self._payload[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _http_settings(media_settings: Settings) -> Settings:
    return media_settings.replace(tts_engine="http", tts_http_url="http://fake.invalid/tts")


# ---------------- R112-01：安全检查早于 TTS ----------------

class _ForbiddenTTS:
    name = "forbidden"

    def __init__(self):
        self.calls = 0

    def synthesize(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("安全拦截前不应调用 TTS")


def test_fallback_scene_safety_blocks_before_tts(media_settings: Settings):
    """旁白干净、但兜底 scene 命中词表时，必须在 TTS 之前拦截。"""
    ocr = {
        "schema_version": "1.0",
        "book_id": "book01",
        "page_id": "book01_p03",
        "page_no": 3,
        "status": "ok",
        "image_width": 900,
        "image_height": 1200,
        "text_blocks": [
            {"block_id": "book01_p03_t01", "order": 1, "text": "从前有座山。", "bbox": [0, 0, 10, 10], "confidence": 0.9}
        ],
        "page_confidence": 0.9,
        "elapsed_ms": 10,
    }
    vlm = {
        "schema_version": "1.0",
        "book_id": "book01",
        "page_id": "book01_p03",
        "page_no": 3,
        "status": "ok",
        "image_width": 900,
        "image_height": 1200,
        "description": "",
        "objects": [
            {"object_id": "book01_p03_o01", "label": "兔子", "bbox": [0, 0, 10, 10], "confidence": 0.9}
        ],
        "scene_tags": [],
        "safety": {"pass": True, "flags": []},
        "elapsed_ms": 10,
    }
    settings = media_settings.replace(safety_enabled=True, safety_blocklist=("兔子",))
    client = _ForbiddenTTS()

    with pytest.raises(AppError) as info:
        build_page_story(
            "book01_p03", "3-6", settings, tts_client=client, ocr=ocr, vlm=vlm
        )

    assert info.value.code == ErrorCode.SAFETY_BLOCKED
    assert client.calls == 0, "兜底 scene 的安全检查必须早于 TTS"
    assert not (settings.json_dir / "book01_p03_story.json").is_file()
    assert list(settings.audios_dir.glob("tts_*.mp3")) == []


class _SafetyFailTTS:
    name = "safety-fail"

    def synthesize(self, *args, **kwargs):
        raise AppError(ErrorCode.SAFETY_BLOCKED, "TTS 阶段安全拒绝")


def test_tts_safety_error_propagates_not_degraded(
    media_settings: Settings, sample_ocr: dict, sample_vlm: dict
):
    with pytest.raises(AppError) as info:
        build_page_story(
            "book01_p03",
            "3-6",
            media_settings,
            tts_client=_SafetyFailTTS(),
            ocr=sample_ocr,
            vlm=sample_vlm,
        )
    assert info.value.code == ErrorCode.SAFETY_BLOCKED, "安全拒绝不能被当成 no_audio"
    assert not (media_settings.json_dir / "book01_p03_story.json").is_file()


def test_pipeline_video_safety_is_blocked(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict, monkeypatch
):
    from agents.generation import pipeline

    def boom(*args, **kwargs):
        raise AppError(ErrorCode.SAFETY_BLOCKED, "视频阶段安全拒绝")

    monkeypatch.setattr(pipeline, "compose_video", boom)
    result = pipeline.run_page("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=sample_vlm)

    assert result.status == "blocked"
    assert result.error and result.error["code"] == 3004
    assert "no_video" not in result.degraded


# ---------------- R112-02：Video 事务发布与回滚 ----------------

def _compose_once(settings: Settings, story: dict, image):
    return compose_video("book01_p03", story, settings)


def _story(settings: Settings, ocr: dict, vlm: dict) -> dict:
    return build_page_story("book01_p03", "3-6", settings, ocr=ocr, vlm=vlm).doc


def _debris(settings: Settings) -> list[str]:
    patterns = ("*.staged.*", "*.bak.*", "*.part", "*.tmp.*")
    found: list[str] = []
    for directory in (settings.videos_dir, settings.json_dir):
        for pattern in patterns:
            found.extend(str(p) for p in directory.glob(pattern))
    return found


def test_video_json_publish_failure_restores_old_pair(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict, monkeypatch
):
    import agents.generation.video as video_module

    story = _story(media_settings, sample_ocr, sample_vlm)
    first = _compose_once(media_settings, story, page_image)
    old_mp4 = first.path.read_bytes()
    old_json = (media_settings.json_dir / "book01_p03_video.json").read_bytes()

    real_replace = video_module.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 4:  # 第 4 次是 JSON 的正式替换
            raise PermissionError("模拟 JSON 发布失败")
        return real_replace(src, dst)

    monkeypatch.setattr(video_module.os, "replace", flaky)

    with pytest.raises(PermissionError):
        _compose_once(media_settings, story, page_image)

    assert first.path.read_bytes() == old_mp4, "失败必须恢复旧 MP4"
    assert (media_settings.json_dir / "book01_p03_video.json").read_bytes() == old_json, "失败必须恢复旧 JSON"
    assert _debris(media_settings) == []


def test_video_failure_without_old_pair_leaves_nothing(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict, monkeypatch
):
    import agents.generation.video as video_module

    story = _story(media_settings, sample_ocr, sample_vlm)
    real_replace = video_module.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:  # 第一次正式替换就失败（无旧文件）
            raise PermissionError("模拟 MP4 发布失败")
        return real_replace(src, dst)

    monkeypatch.setattr(video_module.os, "replace", flaky)

    with pytest.raises(PermissionError):
        _compose_once(media_settings, story, page_image)

    assert not (media_settings.videos_dir / "book01_p03_video.mp4").exists()
    assert not (media_settings.json_dir / "book01_p03_video.json").exists()
    assert _debris(media_settings) == []


def test_video_missing_audio_file_raises(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict
):
    story = _story(media_settings, sample_ocr, sample_vlm)
    story["segments"][0]["audio_url"] = "http://test.local/audios/does-not-exist.mp3"

    with pytest.raises(VideoError) as info:
        compose_video("book01_p03", story, media_settings)
    assert "缺失" in info.value.msg
    assert not (media_settings.videos_dir / "book01_p03_video.mp4").exists()


# ---------------- R112-03：HTTP JSON/base64/类型 ----------------

def test_http_json_array_rejected(media_settings: Settings, monkeypatch):
    settings = _http_settings(media_settings)
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: FakeResponse(b"[]", content_type="application/json")
    )
    with pytest.raises(TTSFailed) as info:
        HttpEngine(settings).synthesize("数组", "female_warm", 1.0, "mp3", settings.audios_dir / "x.mp3")
    assert "不是对象" in info.value.msg


def test_http_json_missing_base64_rejected(media_settings: Settings, monkeypatch):
    settings = _http_settings(media_settings)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: FakeResponse(b'{"foo": 1}', content_type="application/json"),
    )
    with pytest.raises(TTSFailed) as info:
        HttpEngine(settings).synthesize("缺字段", "female_warm", 1.0, "mp3", settings.audios_dir / "x.mp3")
    assert "audio_base64" in info.value.msg


def test_http_json_bad_base64_rejected(media_settings: Settings, monkeypatch):
    settings = _http_settings(media_settings)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: FakeResponse(b'{"audio_base64": "!!!"}', content_type="application/json"),
    )
    with pytest.raises(TTSFailed) as info:
        HttpEngine(settings).synthesize("坏 base64", "female_warm", 1.0, "mp3", settings.audios_dir / "x.mp3")
    assert "base64" in info.value.msg


def test_http_html_json_body_rejected(media_settings: Settings, monkeypatch):
    settings = _http_settings(media_settings)
    body = b'{"audio_base64": "AAAA"}'
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: FakeResponse(body, content_type="text/html")
    )
    with pytest.raises(TTSFailed) as info:
        HttpEngine(settings).synthesize("HTML JSON", "female_warm", 1.0, "mp3", settings.audios_dir / "x.mp3")
    assert "不是音频" in info.value.msg


def test_wav_container_must_be_wav():
    pcm = AudioProbe(duration_ms=1000, sample_rate=24000, channels=1, codec="pcm_s16le", format_name="w64")
    assert HttpEngine.format_matches(pcm, "wav") is False
    empty = AudioProbe(duration_ms=1000, sample_rate=24000, channels=1, codec="mp3", format_name="")
    assert HttpEngine.format_matches(empty, "mp3") is False
    ok = AudioProbe(duration_ms=1000, sample_rate=24000, channels=1, codec="pcm_s16le", format_name="wav")
    assert HttpEngine.format_matches(ok, "wav") is True


def test_urlerror_timeout_maps_to_2002(media_settings: Settings, monkeypatch):
    settings = _http_settings(media_settings)

    def boom(*args, **kwargs):
        raise urllib.error.URLError(socket.timeout("timed out"))

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(AppError) as info:
        HttpEngine(settings).synthesize("包装超时", "female_warm", 1.0, "mp3", settings.audios_dir / "x.mp3")
    assert info.value.code == ErrorCode.TIMEOUT


# ---------------- R112-04：Story 模型对齐公共契约 ----------------

def _minimal_story(**overrides) -> dict:
    doc = {
        "schema_version": "1.0",
        "book_id": "book01",
        "page_id": "book01_p03",
        "page_no": 3,
        "title": "最小样例",
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
            }
        ],
        "total_duration_sec": 2.0,
        "safety_pass": True,
        "model": {"name": "mock-template", "version": "1.0"},
        "elapsed_ms": 10,
    }
    doc.update(overrides)
    return doc


def test_story_status_failed_rejected():
    with pytest.raises(ValidationError):
        StoryDoc.model_validate(_minimal_story(status="failed"))


def test_highlight_null_rejected():
    doc = _minimal_story()
    doc["segments"][0]["highlight_object_ids"] = None
    with pytest.raises(ValidationError):
        StoryDoc.model_validate(doc)


def test_malformed_object_id_rejected():
    doc = _minimal_story()
    doc["segments"][0]["highlight_object_ids"] = ["book01_p03_oBAD_o01"]
    with pytest.raises(ValidationError):
        StoryDoc.model_validate(doc)


def test_optional_defaults_are_empty_lists():
    """highlight / safety_flags 省略时应为 []，与公共 StoryData 一致。"""
    doc = StoryDoc.model_validate(_minimal_story())
    assert doc.safety_flags == []
    assert doc.segments[0].highlight_object_ids == []


def test_video_status_failed_rejected():
    doc = {
        "schema_version": "1.0",
        "book_id": "book01",
        "page_id": "book01_p03",
        "page_no": 3,
        "status": "failed",
        "duration_sec": 2.0,
        "resolution": "720x1280",
        "fps": 25,
        "segments": [{"segment_id": "book01_p03_s01", "start_sec": 0, "end_sec": 2.0}],
        "elapsed_ms": 10,
    }
    with pytest.raises(ValidationError):
        VideoDoc.model_validate(doc)
