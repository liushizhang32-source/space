"""M3 消费 M1 离线 Generation 参考实现：Gate / Token / 资产 / 提交 / 幂等。

全部用例使用临时 SQLite + 临时离线密钥 + 真实 M1 Gate，不联网、不调用模型、
不产生任何真实费用；Generation Contract V1.0 保持 DRAFT 未激活。
"""

from __future__ import annotations

import pytest

from orchestrator.vendor.member3_v116.agents.generation.m1_generation import (
    GenerationDenied,
    M1GenerationConsumer,
    TERMINAL_DENIALS,
)
from orchestrator.vendor.member3_v116.tests.m1_offline_rig import SIZE, begin, make_rig, result_payload


@pytest.fixture
def rig(tmp_path):
    return make_rig(tmp_path / "m1")


def _code(fn, *args, **kwargs) -> str:
    with pytest.raises(GenerationDenied) as info:
        fn(*args, **kwargs)
    return info.value.m1_code


def test_gate_begin_allocates_attempt_and_keeps_lineage(rig):
    node = rig.page(3)
    attempt = begin(rig)

    # 1) Gate 之后由 M1 分配独立 attempt，而不是复用上游 OCR/VLM attempt
    assert attempt.attempt_id != node.identity.attempt_id
    assert attempt.attempt_id != node.identity.fencing_token
    # 2) 上游五元 lineage 原样保留
    assert attempt.lineage == {
        "job_id": node.identity.job_id,
        "page_id": node.identity.page_id,
        "generation_id": node.identity.generation_id,
        "input_revision": node.identity.input_revision,
        "epoch": node.identity.epoch,
    }
    # 3) begin 原子预留
    assert rig.authority.totals() == {"spent": 0, "held": 1000, "available": 14000}
    assert attempt.amount == 1000
    assert attempt.token and attempt.token != rig.service_token


def test_request_id_idempotent_and_conflict(rig):
    first = begin(rig, request="same-request")
    second = begin(rig, request="same-request")
    assert second.attempt_id == first.attempt_id
    assert second.token == first.token
    assert rig.authority.totals()["held"] == 1000  # 没有重复预留

    assert _code(begin, rig, page_no=3, request="same-request", amount=1001) == "IDEMPOTENCY_CONFLICT"
    # 同一页在新请求上仍未对账 → 必须先把上一 attempt 处理掉
    assert _code(begin, rig, page_no=3, request="another") == "ATTEMPT_UNRESOLVED"


def test_service_binding_rejects_other_service(rig):
    m2_token = rig.authority.service_token("M2", ttl=300)
    consumer = rig.consumer_for(3, service_token=m2_token)
    node = rig.page(3)
    with pytest.raises(GenerationDenied) as info:
        consumer.begin(
            page_id=node.page_id, request_id="req-m2", amount=100,
            c1=node.c1, c2=node.c2, size=SIZE, image=rig.image,
            final_messages=[{"role": "user", "content": "x"}],
        )
    # M2 身份没有 M3 的 generate 授权：服务绑定/授权必须拒绝
    assert info.value.m1_code in {"FORBIDDEN", "SERVICE_MISMATCH"}
    assert rig.authority.totals()["held"] == 0


def test_read_authorized_inputs_and_path_denial(rig):
    attempt = begin(rig)
    consumer = rig.consumer_for(3)
    inputs = consumer.read_inputs(attempt)
    assert set(inputs) == {"c1.json", "c2.json", "sidecar.json", "image.bin"}
    assert inputs["image.bin"] == rig.image
    assert b"page_id" in inputs["c1.json"]

    assert _code(consumer.read_asset, attempt, "private/secret") == "ASSET_FORBIDDEN"
    assert _code(consumer.read_asset, attempt, "../escape") == "INVALID_PATH"


def test_submit_idempotent_and_content_change_rejected(rig):
    attempt = begin(rig)
    consumer = rig.consumer_for(3)
    payload = result_payload(consumer.read_inputs(attempt))
    submitted = consumer.submit(attempt, payload)
    digest = submitted.result_sha256
    assert digest and len(digest) == 64

    # 相同内容重复提交：返回同一摘要，不重复结算，也不需要再读输入
    again = consumer.submit(attempt, payload)
    assert again.result_sha256 == digest
    totals = rig.authority.totals()
    assert totals == {"spent": 0, "held": 1000, "available": 14000}
    # 已提交后不允许再读资产（状态已离开 RESERVED）
    assert _code(consumer.read_asset, attempt, attempt.assets[0]) == "ATTEMPT_SUBMITTED"

    # 内容变化：拒绝
    assert _code(consumer.submit, attempt, b"changed") == "IDEMPOTENCY_CONFLICT"


def test_token_expiry_is_terminal(rig):
    attempt = begin(rig)
    consumer = rig.consumer_for(3)
    rig.clock[0] += 121  # attempt token 默认 ttl=120
    assert _code(consumer.read_asset, attempt, attempt.assets[0]) == "TOKEN_EXPIRED"
    assert "TOKEN_EXPIRED" in TERMINAL_DENIALS
    # 过期不自动退款：预留仍被持有
    assert rig.authority.totals()["held"] == 1000


def test_cancel_revokes_token_and_releases_reservation(rig):
    attempt = begin(rig)
    consumer = rig.consumer_for(3)
    consumer.cancel(attempt)
    assert rig.authority.totals() == {"spent": 0, "held": 0, "available": 15000}
    assert _code(consumer.read_asset, attempt, attempt.assets[0]) == "TOKEN_REVOKED"
    # 重复 cancel 幂等
    consumer.cancel(attempt)


def test_stale_attempt_after_settlement(rig):
    first = begin(rig, request="req-old")
    consumer = rig.consumer_for(3)
    first = consumer.run(first, result_payload)
    rig.authority.settle(first.attempt_id, 500, "receipt-old")

    second = begin(rig, page_no=3, request="req-new")
    assert second.attempt_id != first.attempt_id
    # lineage 的 epoch 来自上游 generation，不随 M3 attempt 递增；这正是"保留上游身份"
    assert second.lineage == first.lineage
    assert second.epoch == first.epoch
    # 旧 attempt 的 token 还没过期，但已不是 current → STALE_ATTEMPT
    assert _code(consumer.read_asset, first, first.assets[0]) == "STALE_ATTEMPT"


def test_fencing_mismatch_on_tampered_identity(rig):
    attempt = begin(rig)
    consumer = rig.consumer_for(3)
    import dataclasses

    tampered = dataclasses.replace(attempt, identity=dict(attempt.identity, epoch=attempt.epoch + 1))
    assert _code(consumer.read_asset, tampered, attempt.assets[0]) == "FENCING_MISMATCH"


def test_asset_version_binding(rig):
    attempt = begin(rig)
    consumer = rig.consumer_for(3)
    name = attempt.assets[0]
    assert consumer.read_asset(attempt, name)
    rig.authority.put_asset("M1", name, b"replaced-after-begin")
    assert _code(consumer.read_asset, attempt, name) == "ASSET_VERSION"


def test_grant_revocation_blocks_new_attempts(rig):
    rig.authority.grant("M3", "M1", "generate", False)
    assert _code(begin, rig, page_no=3, request="req-nogrant") == "FORBIDDEN"
    assert rig.authority.totals()["held"] == 0
    rig.authority.grant("M3", "M1", "generate")
    assert begin(rig, page_no=3, request="req-grant-back")


def test_image_binding_rejects_non_original_bytes(rig):
    node = rig.page(3)
    consumer = rig.consumer_for(3)
    with pytest.raises(GenerationDenied) as info:
        consumer.begin(
            page_id=node.page_id,
            request_id="req-bad-image",
            amount=100,
            c1=node.c1,
            c2=node.c2,
            size=SIZE,
            image=b"not-the-original-image",
            final_messages=[{"role": "user", "content": "x"}],
        )
    assert info.value.m1_code in {"IMAGE_BINDING", "DENIED"}


def test_consumer_has_no_billing_surface(rig):
    consumer = rig.consumer_for(3)
    assert isinstance(consumer, M1GenerationConsumer)
    # M3 不持有、也不能调用结算：只有 M1 可信账单适配器可以 settle
    assert not hasattr(consumer, "settle")
    assert not hasattr(consumer, "recover")
    assert not hasattr(consumer, "provision_project")
    assert not hasattr(consumer, "grant")


def test_m3_story_generator_consumes_authorized_inputs(rig):
    """真实 M3 故事生成器只吃 M1 授权字节，产出 C3 候选并提交。"""
    import json

    from orchestrator.vendor.member3_v116.agents.generation.m1_story import story_payload

    node = rig.page(3)
    consumer = rig.consumer_for(3)

    first = consumer.run(begin(rig, request="req-story"), story_payload)
    assert first.result_sha256 and len(first.result_sha256) == 64
    rig.authority.settle(first.attempt_id, 700, "receipt-story")
    assert rig.authority.totals() == {"spent": 700, "held": 0, "available": 14300}

    # 换一个 attempt 复算：结果只取决于授权输入，页面身份与 Segment 必须完整
    second = begin(rig, page_no=3, request="req-story-check", amount=700)
    payload = story_payload(consumer.read_inputs(second))
    doc = json.loads(payload)
    assert doc["page_id"] == node.page_id
    assert doc["schema_version"]
    assert doc["segments"], "故事必须有至少一个 Segment"
    assert consumer.submit(second, payload).result_sha256
