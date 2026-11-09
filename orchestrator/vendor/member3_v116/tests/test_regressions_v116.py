"""v1.1.6 回归：恢复日志 I/O 失败不能遮蔽原有的恢复错误结果（F115-01）。"""

from __future__ import annotations

import json
from pathlib import Path

from agents.generation.config import Settings
from agents.generation.errors import VideoPublishError
from agents.generation.pipeline import run_page

MARKER = "MOCK_RECOVERY_BACKUP_PATH=C:/tmp/book01_p03_video.mp4.bak.1"


def _inject_publish_error(monkeypatch):
    import agents.generation.pipeline as pipeline

    def boom(*args, **kwargs):
        raise VideoPublishError(
            "视频发布失败且回滚未完成：旧产物已保留为备份，需要人工恢复",
            detail=MARKER,
        )

    monkeypatch.setattr(pipeline, "compose_video", boom)


def _settings(settings: Settings) -> Settings:
    return settings


def test_primary_log_io_failure_uses_fallback(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict, monkeypatch, caplog
):
    """F115-01：主 JSONL 不可写时，退到备用日志，仍返回结构化恢复结果。"""
    real_open = Path.open

    def flaky_open(self, *args, **kwargs):
        if self.name == "book01_p03_publish_errors.jsonl":
            raise PermissionError("MOCK diagnostic storage denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)
    _inject_publish_error(monkeypatch)

    with caplog.at_level("WARNING"):
        result = run_page("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=sample_vlm)

    assert result.status == "partial", "诊断失败不能改变页面降级结果"
    assert result.video_error and result.video_error["code"] == 3007
    assert result.video_error["recovery_id"].startswith("rec_")
    assert MARKER not in json.dumps(result.to_dict(), ensure_ascii=False)

    fallback = media_settings.logs_dir / "publish_errors_fallback.jsonl"
    assert fallback.is_file(), "主日志失败必须写备用日志"
    record = json.loads(fallback.read_text(encoding="utf-8").splitlines()[-1])
    assert record["recovery_id"] == result.video_error["recovery_id"]
    assert MARKER in record["detail"]
    assert any("视频发布需要人工恢复" in r.message for r in caplog.records)


def test_all_log_targets_fail_but_result_preserved(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict, monkeypatch, caplog
):
    """主日志与备用日志都写不进去，也不能抛异常或丢恢复码。"""
    real_open = Path.open

    def flaky_open(self, *args, **kwargs):
        if self.name in {"book01_p03_publish_errors.jsonl", "publish_errors_fallback.jsonl"}:
            raise PermissionError("MOCK diagnostic storage denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)
    _inject_publish_error(monkeypatch)

    with caplog.at_level("WARNING"):
        result = run_page("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=sample_vlm)

    assert result.status == "partial"
    assert result.video_error["recovery_id"].startswith("rec_")
    assert MARKER not in json.dumps(result.to_dict(), ensure_ascii=False)
    assert any("恢复信息未能持久化" in r.message for r in caplog.records)


def test_log_dir_creation_failure_does_not_raise(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict, monkeypatch, caplog
):
    """mkdir 失败（只影响 logs/）时仍要返回恢复结果。"""
    real_mkdir = Path.mkdir

    def flaky_mkdir(self, *args, **kwargs):
        if self.name == "logs":
            raise PermissionError("MOCK log dir denied")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", flaky_mkdir)
    _inject_publish_error(monkeypatch)

    with caplog.at_level("WARNING"):
        result = run_page("book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=sample_vlm)

    assert result.status == "partial"
    assert result.video_error["recovery_id"].startswith("rec_")
