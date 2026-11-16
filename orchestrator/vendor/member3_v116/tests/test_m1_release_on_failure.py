"""M3-P1-01 / P1-02 / P1-03：失败路径的授权释放与 release 错误上报。

覆盖：Token 撤销、授权读取失败、页身份不一致、故事失败时释放、story.json 读取失败、
释放失败不被吞掉、重复 release 幂等、已提交的 attempt 不得由 M3 释放。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.vendor.member3_v116.agents.generation import pipeline as pipeline_module
from orchestrator.vendor.member3_v116.agents.generation.config import Settings
from orchestrator.vendor.member3_v116.agents.generation.errors import AppError, ErrorCode, StoryInputError
from orchestrator.vendor.member3_v116.agents.generation.m1_generation import GenerationDenied
from orchestrator.vendor.member3_v116.agents.generation.m1_pipeline import M1ReleaseError, open_session
from orchestrator.vendor.member3_v116.agents.generation.pipeline import run_page
from orchestrator.services.integration_reference import Authority
from orchestrator.services.vision_supervisor.shared import SharedFences
from orchestrator.vendor.member3_v116.tests.m1_offline_rig import make_rig


@pytest.fixture
def rig(tmp_path):
    return make_rig(tmp_path / "release")


def _session(rig, *, request="req-release", amount=1000, page=3):
    node = rig.page(page)
    consumer = rig.consumer_for(page)
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


def _revoke_upstream(rig, node):
    other = Authority(
        rig.db_path, rig.anchor_path, rig.keys, lambda: rig.clock[0], offline_test=True
    )
    SharedFences(other).cancel(SharedFences(other).restore(node.page_id))


def _requests_count(rig) -> int:
    with sqlite3.connect(rig.db_path) as db:
        return db.execute("SELECT count(*) FROM requests").fetchone()[0]


def test_token_revoked_releases_and_reports(rig, tmp_path):
    node, consumer, session = _session(rig, request="revoked")
    _revoke_upstream(rig, node)
    assert consumer.totals()["held"] == 0  # 上游撤销已释放预留

    result = run_page(node.page_id, "3-6", _settings(tmp_path), make_video=False, m1=session)

    assert result.status == "failed"
    assert result.error and result.error["code"] == 1005
    assert result.budget_release_error is None
    assert session.released is True
    assert consumer.totals() == {"spent": 0, "held": 0, "available": 15000}
    assert _requests_count(rig) == 1  # 没有自动创建新 request_id


def test_asset_read_failure_releases_reservation(rig, tmp_path):
    node, consumer, session = _session(rig, request="asset-version")
    name = session.attempt.assets[0]
    rig.authority.put_asset("M1", name, b"replaced-between-begin-and-read")

    result = run_page(node.page_id, "3-6", _settings(tmp_path), make_video=False, m1=session)

    assert result.status == "failed"
    assert result.error and result.error["code"] == 1005
    assert "ASSET_VERSION" in result.error["msg"]
    assert result.budget_release_error is None
    assert consumer.totals() == {"spent": 0, "held": 0, "available": 15000}
    assert _requests_count(rig) == 1


def test_page_mismatch_releases_reservation(rig, tmp_path):
    node, consumer, session = _session(rig, request="page-mismatch")
    other = rig.page(4)

    result = run_page(other.page_id, "3-6", _settings(tmp_path), make_video=False, m1=session)

    assert result.status == "failed"
    assert result.error and result.error["code"] == 1002
    assert result.budget_release_error is None
    assert consumer.totals() == {"spent": 0, "held": 0, "available": 15000}
    assert _requests_count(rig) == 1


def test_story_failure_reports_release_failure(rig, tmp_path, monkeypatch):
    node, consumer, session = _session(rig, request="release-broken")

    def broken_cancel(attempt):
        raise GenerationDenied("MAINTENANCE")

    def boom(*args, **kwargs):
        raise StoryInputError("模拟故事失败")

    monkeypatch.setattr(session.consumer, "cancel", broken_cancel)
    monkeypatch.setattr(pipeline_module, "build_page_story", boom)

    result = run_page(node.page_id, "3-6", _settings(tmp_path), make_video=False, m1=session)

    assert result.status == "failed"
    assert result.error and result.error["code"] == 3001
    assert result.budget_release_error is not None
    assert result.budget_release_error["m1_code"] == "MAINTENANCE"
    # 释放失败不得伪装成成功：预算仍被占用
    assert consumer.totals() == {"spent": 0, "held": 1000, "available": 14000}
    assert session.release_error == "MAINTENANCE"
    assert session.released is False


@pytest.mark.parametrize("code", ["MAINTENANCE", "CORRUPT", "CLOCK_ROLLBACK"])
def test_release_surfaces_non_terminal_denials(rig, monkeypatch, code):
    node, consumer, session = _session(rig, request=f"release-{code.lower()}")

    def broken_cancel(attempt):
        raise GenerationDenied(code)

    monkeypatch.setattr(session.consumer, "cancel", broken_cancel)
    with pytest.raises(M1ReleaseError) as info:
        session.release()
    assert info.value.m1_code == code
    assert session.release_error == code
    assert session.released is False


def test_release_is_idempotent_when_already_cancelled(rig):
    node, consumer, session = _session(rig, request="release-twice")
    session.release()
    assert session.released is True
    session.release()  # 重复释放安全
    session.release()
    assert consumer.totals() == {"spent": 0, "held": 0, "available": 15000}


def test_release_treats_revoked_token_as_terminal(rig):
    node, consumer, session = _session(rig, request="release-revoked")
    _revoke_upstream(rig, node)
    session.release()
    assert session.released is True
    assert session.release_error is None
    assert consumer.totals()["held"] == 0


def test_submitted_attempt_is_never_released(rig, tmp_path):
    node, consumer, session = _session(rig, request="submitted")
    story = json.dumps(
        {"page_id": node.page_id, "segments": [{"scene": "x", "narration": "y"}]},
        ensure_ascii=False,
    ).encode()
    session.submit_story_bytes(story)
    assert session.submitted is True

    session.release()
    assert session.released is False
    assert consumer.totals() == {"spent": 0, "held": 1000, "available": 14000}


# ---------------------------------------------------------------- M3-P1-03
def test_missing_story_file_releases_reserved_budget(rig, tmp_path, monkeypatch):
    """故事“成功”但 story.json 不存在：读取失败必须释放 RESERVED。"""
    node, consumer, session = _session(rig, request="story-missing")

    def fake_story(*args, **kwargs):
        return SimpleNamespace(degraded=[], doc={"page_id": node.page_id})

    monkeypatch.setattr(pipeline_module, "build_page_story", fake_story)
    settings = _settings(tmp_path)
    # 确认文件确实不存在（fake_story 不会落盘）
    assert not (settings.data_dir / "json" / f"{node.page_id}_story.json").exists()

    result = run_page(node.page_id, "3-6", settings, make_video=False, m1=session)

    assert result.status == "failed"
    assert result.error and result.error["code"] == int(ErrorCode.NOT_FOUND)
    assert result.budget_release_error is None
    assert session.released is True
    assert consumer.totals() == {"spent": 0, "held": 0, "available": 15000}
    assert _requests_count(rig) == 1


def test_story_read_oserror_releases_reserved_budget(rig, tmp_path, monkeypatch):
    """read_bytes 抛 OSError：仍属于提交前失败，必须释放。"""
    node, consumer, session = _session(rig, request="story-oserror")
    settings = _settings(tmp_path)
    original = Path.read_bytes

    def failing_read(self):
        if self.name.endswith("_story.json"):
            raise OSError("simulated disk failure")
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", failing_read)

    result = run_page(node.page_id, "3-6", settings, make_video=False, m1=session)

    assert result.status == "failed"
    assert result.error and result.error["code"] == int(ErrorCode.UNAVAILABLE)
    assert result.budget_release_error is None
    assert session.released is True
    assert consumer.totals() == {"spent": 0, "held": 0, "available": 15000}
    assert _requests_count(rig) == 1


def test_story_read_failure_reports_release_failure(rig, tmp_path, monkeypatch):
    """读取失败且释放也失败：预算占用必须显式暴露。"""
    node, consumer, session = _session(rig, request="story-read-release-fail")

    def fake_story(*args, **kwargs):
        return SimpleNamespace(degraded=[], doc={"page_id": node.page_id})

    def broken_cancel(attempt):
        raise GenerationDenied("CORRUPT")

    monkeypatch.setattr(pipeline_module, "build_page_story", fake_story)
    monkeypatch.setattr(session.consumer, "cancel", broken_cancel)

    result = run_page(node.page_id, "3-6", _settings(tmp_path), make_video=False, m1=session)

    assert result.status == "failed"
    assert result.error and result.error["code"] == int(ErrorCode.NOT_FOUND)
    assert result.budget_release_error is not None
    assert result.budget_release_error["m1_code"] == "CORRUPT"
    assert consumer.totals() == {"spent": 0, "held": 1000, "available": 14000}
    assert session.released is False


def test_submit_failure_is_not_treated_as_unsubmitted(rig, tmp_path, monkeypatch):
    """submit 抛错时不得假定未提交、不得释放可能已进入 UNKNOWN 的预算。"""
    node, consumer, session = _session(rig, request="submit-failure")

    def broken_submit(payload):
        raise AppError(ErrorCode.UNAUTHORIZED, "submit rejected", detail="TOKEN_EXPIRED")

    monkeypatch.setattr(session, "submit_story_bytes", broken_submit)

    result = run_page(node.page_id, "3-6", _settings(tmp_path), make_video=False, m1=session)

    assert result.status == "failed"
    assert result.error and result.error["code"] == int(ErrorCode.UNAUTHORIZED)
    assert result.budget_release_error is None
    assert session.released is False
    assert consumer.totals() == {"spent": 0, "held": 1000, "available": 14000}


def test_story_read_does_not_swallow_base_exceptions(rig, tmp_path, monkeypatch):
    """不得用 BaseException 宽泛捕获掩盖系统错误。"""
    node, consumer, session = _session(rig, request="story-read-baseexception")
    original = Path.read_bytes

    def interrupted(self):
        if self.name.endswith("_story.json"):
            raise KeyboardInterrupt()
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_page(node.page_id, "3-6", _settings(tmp_path), make_video=False, m1=session)
    # 未进入释放路径，预算仍被持有，交由调用方/进程恢复处理
    assert consumer.totals() == {"spent": 0, "held": 1000, "available": 14000}
