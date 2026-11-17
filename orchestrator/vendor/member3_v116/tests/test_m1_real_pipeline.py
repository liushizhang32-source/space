"""真实 M3 业务入口（pipeline.run_page）接入 M1 授权输入的端到端验证。

覆盖：入口调用 consumer、故事生成只消费授权 C1/C2、结果按落盘字节提交、
无本地 ocr/vlm 也能成功（不存在绕过授权的读盘路径）、失败不提交且释放预留。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from orchestrator.vendor.member3_v116.agents.generation import pipeline as pipeline_module
from orchestrator.vendor.member3_v116.agents.generation.config import Settings
from orchestrator.vendor.member3_v116.agents.generation.errors import StoryInputError
from orchestrator.vendor.member3_v116.agents.generation.m1_pipeline import open_session
from orchestrator.vendor.member3_v116.agents.generation.pipeline import run_page
from orchestrator.vendor.member3_v116.tests.m1_offline_rig import make_rig


@pytest.fixture
def rig(tmp_path):
    return make_rig(tmp_path / "real")


def _session(rig, *, request="req-real", amount=1000):
    node = rig.page(3)
    consumer = rig.consumer_for(3)
    session = open_session(
        consumer,
        page_id=node.page_id,
        request_id=request,
        amount=amount,
        c1=node.c1,
        c2=node.c2,
        size=(96, 128),
        image=rig.image,
        final_messages=[{"role": "user", "content": "为这一页生成儿童故事"}],
    )
    return node, consumer, session


def _settings(tmp_path) -> Settings:
    data = tmp_path / "products"
    data.mkdir(parents=True, exist_ok=True)
    return Settings(data_dir=data)


def test_run_page_entry_generates_and_submits(rig, tmp_path):
    node, consumer, session = _session(rig)
    settings = _settings(tmp_path)
    # 运行前 data 目录里没有任何 ocr/vlm 输入文件
    assert not (settings.data_dir / "json").exists()

    result = run_page(node.page_id, "3-6", settings, make_video=False, m1=session)

    assert result.status in {"done", "partial"}
    assert result.generation_mode == "m1_authorized"
    assert result.m1_attempt_id == session.attempt_id
    story_file = settings.data_dir / "json" / f"{node.page_id}_story.json"
    assert story_file.is_file()
    # 提交的是落盘 story.json 的原始字节
    assert result.m1_result_sha256 == hashlib.sha256(story_file.read_bytes()).hexdigest()
    # 预留仍在，等待 M1 可信账单结算
    assert consumer.totals() == {"spent": 0, "held": 1000, "available": 14000}
    doc = json.loads(story_file.read_bytes())
    assert doc["page_id"] == node.page_id and doc["segments"]


def test_no_bypass_read_of_local_ocr_vlm(rig, tmp_path, monkeypatch):
    node, consumer, session = _session(rig, request="no-bypass")
    settings = _settings(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("授权模式下不得读取本地 ocr/vlm 输入")

    # builder 只在 ocr/vlm 参数缺失时才会读盘；一旦读盘就说明存在绕过路径
    monkeypatch.setattr("orchestrator.vendor.member3_v116.agents.generation.story.builder.read_json", forbidden)

    result = run_page(node.page_id, "3-6", settings, make_video=False, m1=session)
    assert result.status in {"done", "partial"}
    assert result.m1_result_sha256
    assert not (settings.data_dir / "json" / f"{node.page_id}_ocr.json").exists()
    assert not (settings.data_dir / "json" / f"{node.page_id}_vlm.json").exists()


def test_without_m1_authorization_the_entry_needs_local_inputs(rig, tmp_path):
    node, consumer, session = _session(rig, request="legacy-empty")
    settings = _settings(tmp_path)
    result = run_page(node.page_id, "3-6", settings, make_video=False)
    assert result.status == "failed"
    assert result.m1_result_sha256 is None
    assert consumer.totals()["held"] == 1000  # 会话尚未释放，仍由调用方负责
    session.release()
    assert consumer.totals()["held"] == 0


def test_legacy_flow_with_local_files_still_works(rig, tmp_path):
    node, consumer, session = _session(rig, request="legacy-files")
    settings = _settings(tmp_path)
    json_dir = settings.data_dir / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    (json_dir / f"{node.page_id}_ocr.json").write_bytes(node.c1.documents["c1"])
    (json_dir / f"{node.page_id}_vlm.json").write_bytes(node.c2.documents["c2"])

    result = run_page(node.page_id, "3-6", settings, make_video=False)
    assert result.status in {"done", "partial"}
    assert result.generation_mode == "mock_static"
    assert result.m1_attempt_id is None
    assert consumer.totals()["held"] == 1000
    session.release()


def test_story_failure_does_not_submit_and_releases(rig, tmp_path, monkeypatch):
    node, consumer, session = _session(rig, request="fail-release")
    settings = _settings(tmp_path)

    def boom(*args, **kwargs):
        raise StoryInputError("模拟故事失败")

    monkeypatch.setattr(pipeline_module, "build_page_story", boom)
    result = run_page(node.page_id, "3-6", settings, make_video=False, m1=session)

    assert result.status == "failed"
    assert result.error and result.error["code"] == 3001
    assert session.submitted is False
    assert consumer.totals() == {"spent": 0, "held": 0, "available": 15000}
