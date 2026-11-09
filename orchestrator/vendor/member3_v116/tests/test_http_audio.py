"""HTTP TTS 下载侧校验：状态码、Content-Type、大小、格式、超时、临时文件清理。"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from agents.generation.config import Settings
from agents.generation.errors import AppError, ErrorCode, TTSFailed, TTSUnavailable
from agents.generation.ids import tts_cache_key
from agents.generation.tts.client import TTSClient


class FakeResponse:
    def __init__(
        self,
        payload: bytes = b"",
        *,
        status: int = 200,
        content_type: str = "audio/mpeg",
        content_length: int | None = None,
        read_error: Exception | None = None,
    ):
        self._payload = payload
        self._pos = 0
        self.status = status
        self._read_error = read_error
        self.headers = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def read(self, size: int = -1) -> bytes:
        if self._read_error is not None:
            raise self._read_error
        if size is None or size < 0:
            chunk = self._payload[self._pos :]
            self._pos = len(self._payload)
            return chunk
        chunk = self._payload[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _http_settings(settings: Settings, **overrides) -> Settings:
    base = settings.replace(tts_engine="http", tts_http_url="http://fake.invalid/tts")
    return base.replace(**overrides) if overrides else base


def _patch(monkeypatch, response: FakeResponse) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: response)


def _target(settings: Settings, text: str, fmt: str = "mp3") -> Path:
    return settings.audios_dir / f"tts_{tts_cache_key(text, settings.tts_voice_id, 1.0)}.{fmt}"


def _assert_no_debris(settings: Settings) -> None:
    assert list(settings.audios_dir.glob("*.part")) == [], "失败路径必须清理临时文件"
    assert list(settings.audios_dir.glob("*.tmp")) == []


def _valid_mp3(media_settings: Settings) -> bytes:
    return TTSClient(media_settings).synthesize("给 HTTP 引擎的样例。").audio_path.read_bytes()


def _valid_wav(media_settings: Settings) -> bytes:
    return TTSClient(media_settings).synthesize("给 HTTP 引擎的 WAV。", fmt="wav").audio_path.read_bytes()


def test_http_rejects_html_error_page(media_settings: Settings, monkeypatch):
    settings = _http_settings(media_settings)
    _patch(monkeypatch, FakeResponse(b"<html><body>502 Bad Gateway</body></html>", content_type="text/html"))

    with pytest.raises(TTSFailed) as info:
        TTSClient(settings).synthesize("错误页测试。")
    assert "不是音频" in info.value.msg
    assert not _target(settings, "错误页测试。").exists()
    _assert_no_debris(settings)


def test_http_rejects_non_200_status(media_settings: Settings, monkeypatch):
    settings = _http_settings(media_settings)
    _patch(monkeypatch, FakeResponse(_valid_mp3(media_settings), status=500))

    with pytest.raises(TTSFailed) as info:
        TTSClient(settings).synthesize("状态码测试。")
    assert "HTTP 500" in info.value.msg
    _assert_no_debris(settings)


def test_http_rejects_format_mismatch(media_settings: Settings, monkeypatch):
    settings = _http_settings(media_settings)
    _patch(monkeypatch, FakeResponse(_valid_wav(media_settings), content_type="audio/wav"))

    with pytest.raises(TTSFailed) as info:
        TTSClient(settings).synthesize("格式不匹配测试。")
    assert "格式不匹配" in info.value.msg
    assert not _target(settings, "格式不匹配测试。").exists()
    _assert_no_debris(settings)


def test_http_rejects_oversized_content_length(media_settings: Settings, monkeypatch):
    settings = _http_settings(media_settings, tts_max_audio_bytes=4096)
    _patch(monkeypatch, FakeResponse(b"x", content_length=10 * 1024 * 1024))

    with pytest.raises(TTSFailed) as info:
        TTSClient(settings).synthesize("超大响应测试。")
    assert "超过上限" in info.value.msg
    _assert_no_debris(settings)


def test_http_rejects_oversized_body(media_settings: Settings, monkeypatch):
    settings = _http_settings(media_settings, tts_max_audio_bytes=1024)
    payload = _valid_mp3(media_settings) * 4
    _patch(monkeypatch, FakeResponse(payload))

    with pytest.raises(TTSFailed) as info:
        TTSClient(settings).synthesize("超大响应体测试。")
    assert "大小上限" in info.value.msg
    _assert_no_debris(settings)


def test_http_timeout_cleans_up(media_settings: Settings, monkeypatch):
    settings = _http_settings(media_settings)
    _patch(monkeypatch, FakeResponse(b"", read_error=socket.timeout("timed out")))

    with pytest.raises(AppError) as info:
        TTSClient(settings).synthesize("超时测试。")
    assert info.value.code == ErrorCode.TIMEOUT
    assert not _target(settings, "超时测试。").exists()
    _assert_no_debris(settings)


def test_http_garbage_audio_cleans_temp(media_settings: Settings, monkeypatch):
    settings = _http_settings(media_settings)
    _patch(monkeypatch, FakeResponse(b"GARBAGE-NOT-AUDIO"))

    with pytest.raises(TTSFailed) as info:
        TTSClient(settings).synthesize("坏音频测试。")
    assert int(info.value.code) == ErrorCode.TTS_FAILED
    assert not _target(settings, "坏音频测试。").exists()
    _assert_no_debris(settings)


def test_http_valid_audio_succeeds(media_settings: Settings, monkeypatch):
    settings = _http_settings(media_settings)
    _patch(monkeypatch, FakeResponse(_valid_mp3(media_settings)))

    call = TTSClient(settings).synthesize("有效音频测试。")
    assert call.audio_path.is_file()
    assert call.duration_source == "tts"
    assert call.cached is False


def test_http_without_ffmpeg_is_unavailable_not_success(media_settings: Settings, monkeypatch):
    """没有 ffmpeg 时深检不可用，必须报 2004，不能把未验证音频当成功。"""
    settings = _http_settings(media_settings, ffmpeg_path="definitely-missing-ffmpeg")
    _patch(monkeypatch, FakeResponse(_valid_mp3(media_settings)))

    with pytest.raises(TTSUnavailable) as info:
        TTSClient(settings).synthesize("无法验证测试。")
    assert info.value.code == ErrorCode.UNAVAILABLE
    assert not _target(settings, "无法验证测试。").exists()
    _assert_no_debris(settings)
