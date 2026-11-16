"""M3 对 M1 离线预算账本的专项验证：预留 / 结算 / 释放 / UNKNOWN / 重启。

项目总预算固定 15000 minor units；全部为离线 fixture，不产生真实费用。
"""

from __future__ import annotations

import pytest

from agents.generation.m1_generation import GenerationDenied
from tests.m1_offline_rig import begin, make_rig, result_payload


@pytest.fixture
def rig(tmp_path):
    return make_rig(tmp_path / "m1-budget")


def _code(fn, *args, **kwargs) -> str:
    with pytest.raises(GenerationDenied) as info:
        fn(*args, **kwargs)
    return info.value.m1_code


def test_budget_insufficient_is_rejected(rig):
    begin(rig, page_no=3, request="req-a", amount=14000)
    assert rig.authority.totals() == {"spent": 0, "held": 14000, "available": 1000}

    assert _code(begin, rig, page_no=4, request="req-b", amount=1001) == "BUDGET_EXHAUSTED"
    assert rig.authority.totals() == {"spent": 0, "held": 14000, "available": 1000}
    # 恰好用满仍允许
    assert begin(rig, page_no=4, request="req-c", amount=1000).amount == 1000
    assert rig.authority.totals() == {"spent": 0, "held": 15000, "available": 0}


def test_invalid_amounts_never_reserve(rig):
    node = rig.page(3)
    consumer = rig.consumer_for(3)
    for bad in (True, False, 0, -1, 15001, 1.0, "1000", None):
        with pytest.raises(GenerationDenied) as info:
            consumer.begin(
                page_id=node.page_id,
                request_id=f"bad-{bad!r}",
                amount=bad,
                c1=node.c1,
                c2=node.c2,
                size=(96, 128),
                image=rig.image,
                final_messages=[{"role": "user", "content": "x"}],
            )
        assert info.value.m1_code == "INVALID_AMOUNT"
    assert rig.authority.totals() == {"spent": 0, "held": 0, "available": 15000}


def test_duplicate_request_does_not_double_reserve(rig):
    first = begin(rig, request="dup", amount=1200)
    second = begin(rig, request="dup", amount=1200)
    assert first.attempt_id == second.attempt_id
    assert rig.authority.totals() == {"spent": 0, "held": 1200, "available": 13800}


def test_trusted_settle_charges_once(rig):
    attempt = begin(rig, request="settle", amount=1000)
    consumer = rig.consumer_for(3)
    attempt = consumer.run(attempt, result_payload)
    rig.authority.settle(attempt.attempt_id, 900, "receipt-1")
    rig.authority.settle(attempt.attempt_id, 900, "receipt-1")  # 重复结算幂等
    assert rig.authority.totals() == {"spent": 900, "held": 0, "available": 14100}


def test_client_cannot_release_after_submit(rig):
    attempt = begin(rig, request="no-refund", amount=1000)
    consumer = rig.consumer_for(3)
    attempt = consumer.run(attempt, result_payload)
    # 已提交：客户端不能凭报错要求退款
    assert _code(consumer.cancel, attempt) == "UNKNOWN_RETAINS_BUDGET"
    assert rig.authority.totals() == {"spent": 0, "held": 1000, "available": 14000}


def test_unknown_retains_budget_across_restart(rig):
    attempt = begin(rig, request="unknown", amount=1000)
    consumer = rig.consumer_for(3)
    attempt = consumer.run(attempt, result_payload)
    assert rig.authority.totals()["held"] == 1000

    restarted = rig.reopen()
    restarted.authority.recover()  # M1 运维动作，M3 不调用
    # UNKNOWN 不自动释放
    assert restarted.authority.totals() == {"spent": 0, "held": 1000, "available": 14000}
    restarted_consumer = restarted.consumer_for(3)
    assert _code(restarted_consumer.cancel, attempt) == "UNKNOWN_RETAINS_BUDGET"
    assert _code(begin, restarted, page_no=3, request="next") == "ATTEMPT_UNRESOLVED"

    # 只有可信账单结算才能结束
    restarted.authority.settle(attempt.attempt_id, 1000, "receipt-unknown")
    assert restarted.authority.totals() == {"spent": 1000, "held": 0, "available": 14000}


def test_restart_does_not_reset_ledger(rig):
    attempt = begin(rig, page_no=3, request="spend-1", amount=1000)
    consumer = rig.consumer_for(3)
    attempt = consumer.run(attempt, result_payload)
    rig.authority.settle(attempt.attempt_id, 900, "receipt-spend")

    restarted = rig.reopen()
    assert restarted.authority.totals() == {"spent": 900, "held": 0, "available": 14100}
    # 重启后额度没有被"重置"回 15000
    assert begin(restarted, page_no=4, request="after-restart", amount=14100)
    assert restarted.authority.totals() == {"spent": 900, "held": 14100, "available": 0}
    assert _code(begin, restarted, page_no=5, request="over", amount=1) == "BUDGET_EXHAUSTED"


def test_attempts_cannot_borrow_authorization(rig):
    a = begin(rig, page_no=3, request="attempt-a", amount=500)
    b = begin(rig, page_no=4, request="attempt-b", amount=500)
    assert a.attempt_id != b.attempt_id

    consumer_a = rig.consumer_for(3)
    consumer_b = rig.consumer_for(4)
    # A 的 token 读不到 B 的资产版本
    assert _code(consumer_a.read_asset, a, b.assets[0]) == "ASSET_FORBIDDEN"
    # A 的 token 配上 B 的 identity 也不行
    import dataclasses

    assert _code(consumer_a.read_asset, dataclasses.replace(a, identity=b.identity), a.assets[0]) == "FENCING_MISMATCH"
    # 两个 attempt 各自独立预留
    assert rig.authority.totals() == {"spent": 0, "held": 1000, "available": 14000}
    assert consumer_b.read_asset(b, b.assets[0])


def test_submitted_attempts_keep_hold_until_settled(rig):
    attempt = begin(rig, request="hold", amount=15000)
    consumer = rig.consumer_for(3)
    attempt = consumer.run(attempt, result_payload)
    assert rig.authority.totals() == {"spent": 0, "held": 15000, "available": 0}
    rig.authority.settle(attempt.attempt_id, 15000, "receipt-full")
    assert rig.authority.totals() == {"spent": 15000, "held": 0, "available": 0}


def test_project_binding_rejects_unknown_project(rig):
    node = rig.page(3)
    other = rig.consumer_for(3)
    other.project = "OTHER"
    with pytest.raises(GenerationDenied) as info:
        other.begin(
            page_id=node.page_id,
            request_id="req-other-project",
            amount=100,
            c1=node.c1,
            c2=node.c2,
            size=(96, 128),
            image=rig.image,
            final_messages=[{"role": "user", "content": "x"}],
        )
    assert info.value.m1_code in {"FORBIDDEN", "UNKNOWN_PROJECT", "PROJECT_ACCOUNT_FIXED"}
    assert rig.authority.totals()["held"] == 0


def test_settlement_cannot_exceed_reservation(rig):
    attempt = begin(rig, request="over-settle", amount=1000)
    consumer = rig.consumer_for(3)
    attempt = consumer.run(attempt, result_payload)
    with pytest.raises(Exception) as info:
        rig.authority.settle(attempt.attempt_id, 1001, "receipt-over")
    assert "INVALID_SETTLEMENT" in str(info.value)
    assert rig.authority.totals() == {"spent": 0, "held": 1000, "available": 14000}
