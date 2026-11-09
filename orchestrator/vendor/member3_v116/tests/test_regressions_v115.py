"""v1.1.5 回归：发布恢复错误不重试 + pipeline 记录恢复诊断。"""

from __future__ import annotations

import json

import pytest

from agents.generation.config import Settings
from agents.generation.errors import VideoPublishError
from agents.generation.story.builder import build_page_story
from agents.generation.video import compose_video


def _story(settings: Settings, ocr: dict, vlm: dict) -> dict:
    return build_page_story("book01_p03", "3-6", settings, ocr=ocr, vlm=vlm).doc


def test_video_publish_error_is_not_retryable():
    error = VideoPublishError("需要人工恢复", detail="backup=/tmp/x.bak")
    assert error.retryable is False
    assert error.code == 3007  # 契约错误码不变


def test_compose_does_not_retry_publish_error(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict, monkeypatch
):
    """RT-01：需要人工恢复的发布错误只能尝试一次，不能自动重试覆盖备份。"""
    import agents.generation.video as video_module

    story = _story(media_settings, sample_ocr, sample_vlm)
    calls = {"n": 0}

    def boom(*args, **kwargs):
        calls["n"] += 1
        raise VideoPublishError(
            "视频发布失败且回滚未完成：旧产物已保留为备份，需要人工恢复",
            detail="MOCK_RECOVERY_BACKUP_PATH=/tmp/book01_p03_video.mp4.bak.1",
        )

    monkeypatch.setattr(video_module, "_render_once", boom)
    settings = media_settings.replace(max_retry=1, retry_backoff_sec=0.0)

    with pytest.raises(VideoPublishError):
        compose_video("book01_p03", story, settings)

    assert calls["n"] == 1, "需要人工恢复的发布错误不得自动重试"


def test_pipeline_records_recovery_diagnostics(
    media_settings: Settings, page_image, sample_ocr: dict, sample_vlm: dict, monkeypatch, caplog
):
    """RT-02：pipeline 要把恢复详情写进内部日志，公共响应不泄漏路径。"""
    import agents.generation.pipeline as pipeline

    def boom(*args, **kwargs):
        raise VideoPublishError(
            "视频发布失败且回滚未完成：旧产物已保留为备份，需要人工恢复",
            detail="MOCK_RECOVERY_BACKUP_PATH=C:/tmp/book01_p03_video.mp4.bak.1",
        )

    monkeypatch.setattr(pipeline, "compose_video", boom)

    with caplog.at_level("WARNING"):
        result = pipeline.run_page(
            "book01_p03", "3-6", media_settings, ocr=sample_ocr, vlm=sample_vlm
        )

    assert result.status == "partial"
    assert result.video_error is not None
    recovery_id = result.video_error["recovery_id"]
    assert recovery_id.startswith("rec_")

    public_payload = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "MOCK_RECOVERY_BACKUP_PATH" not in public_payload, "公共响应不能出现本机路径"

    log_path = media_settings.logs_dir / "book01_p03_publish_errors.jsonl"
    assert log_path.is_file(), "必须写出结构化恢复日志"
    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["event"] == "video_publish_recovery_required"
    assert record["recovery_id"] == recovery_id
    assert record["page_id"] == "book01_p03"
    assert "MOCK_RECOVERY_BACKUP_PATH" in record["detail"]

    assert any("视频发布需要人工恢复" in r.message for r in caplog.records), "必须有 WARNING 级诊断"
