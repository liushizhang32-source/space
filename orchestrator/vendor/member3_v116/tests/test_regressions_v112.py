"""v1.1.2 回归：安全字段、输入身份、容器格式、缓存、发布顺序、并发、错误体。"""

from __future__ import annotations

import io
import subprocess
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agents.generation.config import Settings
from agents.generation.errors import AppError, ErrorCode, TTSFailed, VideoError
from agents.generation.media import MediaCheck, MediaStatus, probe_audio
from agents.generation.story.builder import build_page_story
from agents.generation.tts.client import TTSClient
from agents.generation.tts.engine import HttpEngine
from agents.generation.video import compose_video


def _story(settings: Settings, ocr: dict, vlm: dict) -> dict:
    return build_page_story("book01_p03", "3-6", settings, ocr=ocr, vlm=vlm).doc


class FakeResponse:
    def __init__(self, payload: bytes, *, content_type: str = "audio/mpeg"):
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


# ---------- 安全字段 ----------

def test_video_rejects_story_with_safety_pass_false(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict
):
    story = _story(media_settings, sample_ocr, sample_vlm)
    story["safety_pass"] = False

    with pytest.raises(AppError) as info:
        compose_video("book01_p03", story, media_settings)

    assert info.value.code == ErrorCode.SAFETY_BLOCKED
    assert "safety_pass=false" in info.value.msg
    assert not (media_settings.json_dir / "book01_p03_video.json").is_file()


# ---------- 输入页身份 ----------

def test_story_rejects_mismatched_ocr_page(media_settings: Settings, sample_ocr: dict, sample_vlm: dict):
    bad_ocr = dict(sample_ocr, page_id="book01_p09")
    with pytest.raises(AppError) as info:
        build_page_story("book01_p03", "3-6", media_settings, ocr=bad_ocr, vlm=sample_vlm)
    assert info.value.code == ErrorCode.INVALID_PARAM
    assert "page_id" in info.value.msg


def test_story_rejects_mismatched_vlm_page_no(media_settings: Settings, sample_ocr: dict, sample_vlm: dict):
    bad_vlm = dict(sample_vlm, page_no=9)
    with pytest.raises(AppError) as info:
        build_page_story("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=bad_vlm)
    assert info.value.code == ErrorCode.INVALID_PARAM


def test_unknown_status_falls_back_to_failed(media_settings: Settings, sample_ocr: dict, sample_vlm: dict):
    """§1.2.6：未知枚举走 default 分支，按 failed 处理而不是误判成功。"""
    result = build_page_story(
        "book01_p03", "3-6", media_settings, ocr=dict(sample_ocr, status="weird"), vlm=sample_vlm
    )
    assert "no_ocr" in result.degraded


# ---------- 容器格式 / 缓存 ----------

def test_mp3_in_mp4_container_rejected(media_settings: Settings, monkeypatch):
    ffmpeg = media_settings.ffmpeg
    assert ffmpeg
    source = TTSClient(media_settings).synthesize("容器测试素材。").audio_path
    bad_container = media_settings.audios_dir / "bad_container.mp4"
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(source), "-c", "copy", "-f", "mp4", str(bad_container)],
        check=True,
    )
    payload = bad_container.read_bytes()

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResponse(payload, content_type="audio/mp4"))
    settings = media_settings.replace(tts_engine="http", tts_http_url="http://fake.invalid/tts")

    with pytest.raises(TTSFailed) as info:
        TTSClient(settings).synthesize("容器格式测试。")
    assert "格式不匹配" in info.value.msg
    assert "容器" in info.value.msg


def test_cache_with_wrong_container_is_rebuilt(media_settings: Settings):
    client = TTSClient(media_settings)
    wav_call = client.synthesize("缓存容器测试。", fmt="wav")
    mp3_bytes = client.synthesize("缓存容器测试。", fmt="mp3").audio_path.read_bytes()
    # 把 mp3 字节塞进 .wav 缓存：容器与请求不符，必须被识别并重建
    wav_call.audio_path.write_bytes(mp3_bytes)

    rebuilt = client.synthesize("缓存容器测试。", fmt="wav")
    assert rebuilt.cached is False
    check = probe_audio(rebuilt.audio_path, media_settings)
    assert check is not None
    assert check.format_name in {"wav", "w64"}


# ---------- 发布顺序：先验证，后发布 ----------

def test_silent_tts_validates_before_publish(media_settings: Settings, monkeypatch):
    from agents.generation.tts import engine as engine_module

    monkeypatch.setattr(
        engine_module,
        "validate_audio",
        lambda *a, **k: MediaCheck(MediaStatus.INVALID, None, "强制失败"),
    )
    text = "发布顺序测试。"
    client = TTSClient(media_settings)

    with pytest.raises(TTSFailed):
        client.synthesize(text)

    from agents.generation.ids import tts_cache_key

    target = media_settings.audios_dir / f"tts_{tts_cache_key(text, 'female_warm', 1.0)}.mp3"
    assert not target.exists(), "验证失败不能留下正式文件"
    assert list(media_settings.audios_dir.glob("*.part")) == []


def test_video_validates_before_publish(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict, monkeypatch
):
    from agents.generation import video as video_module

    story = _story(media_settings, sample_ocr, sample_vlm)
    monkeypatch.setattr(
        video_module,
        "validate_video",
        lambda *a, **k: MediaCheck(MediaStatus.INVALID, None, "强制失败"),
    )

    with pytest.raises(VideoError):
        compose_video("book01_p03", story, media_settings)

    assert not (media_settings.json_dir / "book01_p03_video.json").is_file()
    assert not (media_settings.videos_dir / "book01_p03_video.mp4").exists()
    assert list(media_settings.tmp_dir.glob("*")) == [], "临时目录必须清理"


# ---------- 不误删已有有效文件 / 并发 ----------

def test_http_failure_keeps_existing_valid_audio(media_settings: Settings, monkeypatch):
    settings = media_settings.replace(tts_engine="http", tts_http_url="http://fake.invalid/tts")
    text = "旧文件保护测试。"
    from agents.generation.ids import tts_cache_key

    target = settings.audios_dir / f"tts_{tts_cache_key(text, 'female_warm', 1.0)}.mp3"
    good = TTSClient(media_settings).synthesize("旧文件保护素材。").audio_path.read_bytes()
    target.write_bytes(good)

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResponse(b"GARBAGE"))
    with pytest.raises(TTSFailed):
        HttpEngine(settings).synthesize(text, "female_warm", 1.0, "mp3", target)

    assert target.read_bytes() == good, "失败路径不能删除/破坏已有有效文件"


def test_concurrent_same_text_shares_cache_safely(media_settings: Settings):
    client = TTSClient(media_settings)
    text = "并发合成测试。"

    with ThreadPoolExecutor(max_workers=4) as pool:
        calls = list(pool.map(lambda _: client.synthesize(text), range(4)))

    paths = {call.audio_path for call in calls}
    assert len(paths) == 1
    assert all(call.audio_path.is_file() for call in calls)
    assert list(media_settings.audios_dir.glob("*.part")) == []
    check = probe_audio(calls[0].audio_path, media_settings)
    assert check is not None


# ---------- HTTP 错误体读取 ----------

def test_http_error_body_read_is_bounded(media_settings: Settings, monkeypatch):
    settings = media_settings.replace(tts_engine="http", tts_http_url="http://fake.invalid/tts")
    huge = io.BytesIO(b"E" * 100_000)

    def boom(*args, **kwargs):
        raise urllib.error.HTTPError("http://fake.invalid/tts", 502, "Bad Gateway", {}, huge)

    monkeypatch.setattr("urllib.request.urlopen", boom)

    with pytest.raises(TTSFailed) as info:
        TTSClient(settings).synthesize("错误体读取测试。")
    detail = info.value.detail or ""
    assert len(detail) <= 400, "错误响应只允许读有限字节"
