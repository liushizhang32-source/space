"""v1.1.4 回归：Video 发布提交点/回滚失败/锁范围，以及 MIME 精确判定。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from agents.generation.config import Settings
from agents.generation.errors import TTSFailed, VideoPublishError
from agents.generation.storage import PageFiles
from agents.generation.tts.client import TTSClient
from agents.generation.tts.engine import HttpEngine
from agents.generation.video import _publish_pair


def _files(settings: Settings) -> PageFiles:
    return PageFiles(settings, "book01_p03")


def _seed_old(files: PageFiles) -> tuple[bytes, bytes]:
    files.video.parent.mkdir(parents=True, exist_ok=True)
    files.video_json.parent.mkdir(parents=True, exist_ok=True)
    files.video.write_bytes(b"OLD-MP4")
    files.video_json.write_text('{"v": "OLD"}', encoding="utf-8")
    return files.video.read_bytes(), files.video_json.read_bytes()


def _merged(settings: Settings, payload: bytes, name: str = "merged.mp4") -> Path:
    path = settings.tmp_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _backups(files: PageFiles) -> list[Path]:
    return list(files.video.parent.glob("*.bak.*")) + list(files.video_json.parent.glob("*.bak.*"))


def test_backup_cleanup_failure_does_not_rollback(media_settings: Settings, monkeypatch, caplog):
    """F01：提交成功后的备份清理失败，不能回滚已发布的新版本。"""
    files = _files(media_settings)
    _seed_old(files)
    merged = _merged(media_settings, b"NEW-MP4")

    real_unlink = Path.unlink

    def flaky_unlink(self, missing_ok: bool = False):
        if ".json.bak." in self.name:
            raise PermissionError("backup locked")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    with caplog.at_level("WARNING"):
        _publish_pair(merged, {"v": "NEW"}, files)

    assert files.video.read_bytes() == b"NEW-MP4", "提交后清理失败不得回滚新 MP4"
    assert json.loads(files.video_json.read_text(encoding="utf-8"))["v"] == "NEW"
    assert any("清理失败" in record.message for record in caplog.records)
    # 清理失败的备份允许保留，但它不再是唯一有效副本
    assert any(".json.bak." in path.name for path in _backups(files))


def test_rollback_failure_keeps_recovery_backup(media_settings: Settings, monkeypatch):
    """F02：回滚恢复失败时保留备份，并报明确的 VideoPublishError。"""
    import agents.generation.video as video_module

    files = _files(media_settings)
    _seed_old(files)
    merged = _merged(media_settings, b"NEW-MP4")

    real_replace = video_module.os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 4:  # JSON 正式提交失败
            raise PermissionError("json publish failed")
        if calls["n"] == 5:  # 回滚恢复旧 MP4 失败
            raise PermissionError("restore mp4 failed")
        return real_replace(src, dst)

    monkeypatch.setattr(video_module.os, "replace", flaky_replace)

    with pytest.raises(VideoPublishError) as info:
        _publish_pair(merged, {"v": "NEW"}, files)

    detail = info.value.detail or ""
    assert ".mp4.bak." in detail, "错误里必须给出恢复备份路径"
    kept = [p for p in _backups(files) if ".mp4.bak." in p.name]
    assert kept, "回滚失败必须保留旧 MP4 备份"
    assert kept[0].read_bytes() == b"OLD-MP4"
    assert not files.video.exists()
    # 旧 JSON 已成功恢复
    assert json.loads(files.video_json.read_text(encoding="utf-8"))["v"] == "OLD"


def test_rollback_lock_blocks_other_publisher(media_settings: Settings, monkeypatch):
    """F03：A 失败回滚期间 B 不能插入；回滚结束后 B 发布的结果不能被 A 覆盖。"""
    import agents.generation.video as video_module

    files = _files(media_settings)
    _seed_old(files)
    a_merged = _merged(media_settings, b"AAA", "a.mp4")
    b_merged = _merged(media_settings, b"BBB", "b.mp4")

    real_replace = video_module.os.replace
    calls = {"a": 0}
    started = threading.Event()
    b_errors: list[BaseException] = []

    def run_b():
        try:
            _publish_pair(b_merged, {"v": "B"}, files)
        except BaseException as exc:  # pragma: no cover - 失败时用于诊断
            b_errors.append(exc)

    def flaky_replace(src, dst):
        name = threading.current_thread().name
        if name == "A":
            calls["a"] += 1
            if calls["a"] == 4:  # A 的 JSON 提交失败
                threading.Thread(target=run_b, name="B").start()
                started.set()
                time.sleep(0.3)  # 留出 B 尝试获取锁的窗口
                raise PermissionError("A json publish failed")
        return real_replace(src, dst)

    monkeypatch.setattr(video_module.os, "replace", flaky_replace)

    def run_a():
        try:
            _publish_pair(a_merged, {"v": "A"}, files)
        except BaseException:
            pass

    thread_a = threading.Thread(target=run_a, name="A")
    thread_a.start()
    thread_a.join(timeout=15)
    assert started.is_set(), "测试前提：A 必须走到失败点"
    time.sleep(0.2)
    thread_a.join(timeout=5)
    # 等 B 完成
    for _ in range(100):
        if files.video.exists() and files.video.read_bytes() == b"BBB":
            break
        time.sleep(0.05)

    assert not b_errors, f"B 发布不应失败: {b_errors}"
    assert files.video.read_bytes() == b"BBB", "A 的回滚不能覆盖 B 已发布的新版本"
    assert json.loads(files.video_json.read_text(encoding="utf-8"))["v"] == "B"
    assert _backups(files) == []


def test_mime_with_parameters_rejected_for_html(media_settings: Settings, monkeypatch):
    class Resp:
        status = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}
        _body = b'{"audio_base64": "AAAA"}'
        _pos = 0

        def read(self, size: int = -1) -> bytes:
            if size is None or size < 0:
                chunk, self._pos = self._body[self._pos :], len(self._body)
                return chunk
            chunk = self._body[self._pos : self._pos + size]
            self._pos += len(chunk)
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    settings = media_settings.replace(tts_engine="http", tts_http_url="http://fake.invalid/tts")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Resp())

    with pytest.raises(TTSFailed):
        HttpEngine(settings).synthesize("mime", "female_warm", 1.0, "mp3", settings.audios_dir / "x.mp3")


def test_mime_json_with_charset_accepted(media_settings: Settings, monkeypatch):
    audio = TTSClient(media_settings).synthesize("MIME 样例。").audio_path.read_bytes()
    import base64

    body = json.dumps({"audio_base64": base64.b64encode(audio).decode(), "sample_rate": 24000}).encode()

    class Resp:
        status = 200
        headers = {"Content-Type": "application/json; charset=utf-8"}
        _body = body
        _pos = 0

        def read(self, size: int = -1) -> bytes:
            if size is None or size < 0:
                chunk, self._pos = self._body[self._pos :], len(self._body)
                return chunk
            chunk = self._body[self._pos : self._pos + size]
            self._pos += len(chunk)
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    settings = media_settings.replace(tts_engine="http", tts_http_url="http://fake.invalid/tts")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Resp())

    outcome = HttpEngine(settings).synthesize("mime ok", "female_warm", 1.0, "mp3", settings.audios_dir / "ok.mp3")
    assert outcome.duration_ms > 0
