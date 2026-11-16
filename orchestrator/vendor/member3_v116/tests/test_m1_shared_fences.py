"""SharedFences 共享生命周期验证：双实例、跨实例取消/换代、重启与跨进程。

使用 M1 指定的 `SharedFences(authority)`（不是第一轮的进程内 Fences），
Generation 与 SharedFences 共享同一个 Authority/SQLite/anchor。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from agents.generation.m1_generation import GenerationDenied
from orchestrator.services.integration_reference import Authority, OfflineKMS
from orchestrator.services.vision_supervisor.shared import SharedFences
from tests.m1_offline_rig import KIT_ROOT, begin, make_rig, page_id, result_payload

STAGE_OWNER = "m3-offline-fixture"


def _other_instance(rig) -> tuple[Authority, SharedFences]:
    """第二个 M1 实例：同一 SQLite + 同一 anchor + 同一离线密钥根。"""
    other = Authority(
        rig.db_path, rig.anchor_path, rig.keys, lambda: rig.clock[0], offline_test=True
    )
    return other, SharedFences(other)


def _code(fn, *args, **kwargs) -> str:
    with pytest.raises(GenerationDenied) as info:
        fn(*args, **kwargs)
    return info.value.m1_code


@pytest.fixture
def rig(tmp_path):
    return make_rig(tmp_path / "shared")


def test_two_instances_share_the_same_current(rig):
    attempt = begin(rig, request="shared-begin")
    node = rig.page(3)
    other, fences_b = _other_instance(rig)
    restored = fences_b.restore(node.page_id)

    assert restored is not None
    assert restored.generation_id == node.identity.generation_id
    assert restored.epoch == node.identity.epoch
    assert restored.identity == node.identity
    # 权威侧快照与 A 的内存视图一致
    snap = other.vision_snapshot(node.page_id)
    assert json.loads(snap["lineage"])["generation_id"] == node.identity.generation_id
    assert json.loads(snap["identity"])["attempt_id"] == node.identity.attempt_id
    # B 用同一个 request_id 重放：拿到同一 attempt，不新增预留
    consumer_b = rig.consumer_for(3, service_token=rig.service_token)
    consumer_b.fences, consumer_b.authority, consumer_b.record = fences_b, other, restored
    same = consumer_b.begin(
        page_id=node.page_id,
        request_id="shared-begin",
        amount=attempt.amount,
        c1=node.c1,
        c2=node.c2,
        size=(96, 128),
        image=rig.image,
        final_messages=[{"role": "user", "content": "为这一页生成儿童故事"}],
    )
    assert same.attempt_id == attempt.attempt_id
    assert rig.authority.totals()["held"] == 1000


def test_b_cancel_revokes_a_token_and_submit(rig):
    attempt = begin(rig, request="cancel-me")
    node = rig.page(3)
    other, fences_b = _other_instance(rig)
    fences_b.cancel(fences_b.restore(node.page_id))

    consumer_a = rig.consumer_for(3)
    assert _code(consumer_a.read_asset, attempt, attempt.assets[0]) == "TOKEN_REVOKED"
    assert _code(consumer_a.submit, attempt, result_payload({"c1.json": node.c1.documents["c1"]})) in {
        "TOKEN_REVOKED",
        "STALE_ATTEMPT",
    }
    # 未提交的预留随上游撤销释放
    assert rig.authority.totals() == {"spent": 0, "held": 0, "available": 15000}


def test_b_replacement_changes_epoch_and_old_attempt_cannot_return(rig):
    attempt = begin(rig, request="old-generation")
    node = rig.page(3)
    other, fences_b = _other_instance(rig)
    old = fences_b.restore(node.page_id)
    fences_b.cancel(old)
    # 旧 stage 必须先由 M1 侧确认终止，才允许换代
    other.reconcile_stage(node.identity, STAGE_OWNER, outcome="CANCELLED", terminal_confirmed=True)
    new, created = fences_b.begin("job-replacement", node.page_id, force=True)
    assert created and new.epoch == old.epoch + 1 and new.generation_id != old.generation_id

    consumer_a = rig.consumer_for(3)
    assert _code(consumer_a.read_asset, attempt, attempt.assets[0]) == "TOKEN_REVOKED"
    assert _code(consumer_a.submit, attempt, b"late-result") in {"TOKEN_REVOKED", "STALE_ATTEMPT"}
    # 旧 request_id 重放不能恢复旧分配（旧 token 已撤销 / 当前 generation 已换代）
    assert _code(begin, rig, page_no=3, request="old-generation", amount=1000) in {
        "TOKEN_REVOKED",
        "STALE_ATTEMPT",
    }
    # 旧 generation 也没有把预算占住
    assert rig.authority.totals()["held"] == 0


def test_restart_keeps_current_and_active_token(rig):
    attempt = begin(rig, request="restart-keep")
    node = rig.page(3)
    restarted = rig.reopen()
    restored = restarted.fences.restore(node.page_id)

    assert restored is not None
    assert restored.generation_id == node.identity.generation_id
    assert restored.identity == node.identity
    snap = restarted.authority.vision_snapshot(node.page_id)
    assert json.loads(snap["lineage"])["epoch"] == node.identity.epoch
    # 未取消：旧 token 在重启后仍可用，账本不变
    consumer = restarted.consumer_for(3)
    assert consumer.read_asset(attempt, attempt.assets[0])
    assert restarted.authority.totals() == {"spent": 0, "held": 1000, "available": 14000}


def test_cross_process_instance_sees_same_current(rig):
    node = rig.page(3)
    script = (
        "import json,sys\n"
        "from orchestrator.services.integration_reference import Authority,OfflineKMS\n"
        "from orchestrator.services.vision_supervisor.shared import SharedFences\n"
        "path,anchor,page=sys.argv[1],sys.argv[2],sys.argv[3]\n"
        "a=Authority(path,anchor,OfflineKMS(seed=b'm3-m1-offline-integration-fixture-seed'),lambda:1000,offline_test=True)\n"
        "f=SharedFences(a);r=f.restore(page)\n"
        "row=a.vision_snapshot(page)\n"
        "print(json.dumps({'generation_id':r.generation_id,'epoch':r.epoch,"
        "'identity':json.loads(row['identity']),'status':row['status']}))\n"
    )
    env = dict(os.environ, PYTHONPATH=str(KIT_ROOT))
    guard = os.environ.get("CI_M1_CHILD_GUARD")
    command = ([sys.executable, guard, "m1-current"] if guard else
               [sys.executable, "-c", script])
    proc = subprocess.run(
        [*command, str(rig.db_path), str(rig.anchor_path), node.page_id],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert data["generation_id"] == node.identity.generation_id
    assert data["epoch"] == node.identity.epoch
    assert data["identity"]["attempt_id"] == node.identity.attempt_id
    assert data["status"] == "RUNNING"
    # 跨进程实例只读当前，不会创建新 generation
    assert rig.authority.vision_snapshot(node.page_id)["serial"] == node.identity.epoch
