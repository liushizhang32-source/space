"""OFFLINE PROTOCOL V1.0 私有结构回归（REQUEST / RESULT / SIDECAR / PROMPT_HASH）。

这些用例只校验 M2 侧实现是否与冻结协议一致，不依赖 M1 源码或真实模型。
"""

from __future__ import annotations

import json
from pathlib import Path

from vision import protocol, refs

IDENTITY = dict(
    job_id="job_p1",
    page_id="book01_p03",
    generation_id="gen_p1",
    input_revision=1,
    epoch=1,
    attempt_id="att_p1",
    fencing_token="tok_0123456789abcdef",
)


def _ocr_request(**over):
    doc = {
        "protocol": protocol.PROTOCOL,
        "stage": "ocr",
        "image_path": "C:/m1-offline/attempt-ocr-001/input.bin",
        "image_sha256": "a" * 64,
        "result_path": "result.json",
        "outputs": protocol.canonical_outputs("book01_p03"),
        **IDENTITY,
    }
    doc.update(over)
    return doc


def _vlm_request():
    doc = _ocr_request(stage="vlm")
    doc["inputs"] = {"c1": "C:/m1-offline/attempt-vlm-001/c1.json"}
    doc["c1_binding"] = {
        "identity": {**IDENTITY, "page_id": "book01_p03", "attempt_id": "ocr-attempt-1",
                     "fencing_token": "ocr-token-1"},
        "sha256": "b" * 64,
        "image_sha256": "a" * 64,
    }
    return doc


def test_canonical_outputs_are_protocol_paths():
    out = protocol.canonical_outputs("book01_p03")
    assert out == {
        "c1": "json/book01_p03_ocr.json",
        "c2": "json/book01_p03_vlm.json",
        "sidecar": "json/book01_p03_refs.json",
    }


def test_valid_ocr_request_is_accepted():
    spec = protocol.validate_request(_ocr_request())
    assert spec["stage"] == "ocr"
    assert spec["outputs"] == {"c1": "json/book01_p03_ocr.json"}


def test_valid_vlm_request_is_accepted():
    spec = protocol.validate_request(_vlm_request())
    assert spec["stage"] == "vlm"
    assert spec["outputs"] == {
        "c2": "json/book01_p03_vlm.json",
        "sidecar": "json/book01_p03_refs.json",
    }


def test_unknown_field_is_rejected():
    try:
        protocol.validate_request(_ocr_request(extra="x"))
    except protocol.ProtocolRequestError as exc:
        assert "未声明字段" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("未声明字段必须拒绝")


def test_ocr_request_must_not_carry_c1_binding():
    doc = _ocr_request()
    doc["c1_binding"] = _vlm_request()["c1_binding"]
    try:
        protocol.validate_request(doc)
    except protocol.ProtocolRequestError as exc:
        assert "c1_binding" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("OCR 请求不得含 c1_binding")


def test_vlm_request_requires_c1_binding():
    doc = _vlm_request()
    del doc["c1_binding"]
    try:
        protocol.validate_request(doc)
    except protocol.ProtocolRequestError as exc:
        assert "c1_binding" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("VLM 请求必须含 c1_binding")


def test_inputs_only_allows_c1():
    doc = _vlm_request()
    doc["inputs"]["c1_sha256"] = "c" * 64
    try:
        protocol.validate_request(doc)
    except protocol.ProtocolRequestError as exc:
        assert "inputs" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("inputs 只允许 c1")


def test_int_identity_rejects_bool_and_float():
    for bad in (True, 1.0, 0):
        try:
            protocol.validate_request(_ocr_request(input_revision=bad, epoch=1))
        except protocol.ProtocolRequestError:
            continue
        raise AssertionError(f"input_revision={bad!r} 必须拒绝")


def test_result_has_no_detail_and_exact_identity():
    env = protocol.build_result(identity=IDENTITY, code=3004, msg="safety_blocked")
    assert "detail" not in env
    assert set(env) <= {"protocol", "identity", "code", "msg", "artifacts", "transient"}
    assert set(env["identity"]) == set(protocol.IDENTITY_FIELDS)
    assert env["artifacts"] == {}
    protocol.validate_result(env)


def test_success_result_artifact_keys():
    env = protocol.build_result(
        identity=IDENTITY, code=0, msg="", artifacts={"c1": "json/book01_p03_ocr.json"}
    )
    assert env["artifacts"] == {"c1": "json/book01_p03_ocr.json"}
    assert "transient" not in env


def test_prompt_hash_is_deterministic_and_order_sensitive():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert protocol.prompt_sha256(msgs) == protocol.prompt_sha256(list(msgs))
    swapped = [msgs[1], msgs[0]]
    assert protocol.prompt_sha256(msgs) != protocol.prompt_sha256(swapped)


def test_prompt_messages_reject_extra_keys():
    try:
        protocol.canonical_messages_bytes([{"role": "user", "content": "x", "name": "y"}])
    except Exception as exc:  # noqa: BLE001 - 实现抛 ValueError 即可
        assert "role/content" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("消息项只允许 role/content")


def test_sidecar_root_keys_are_exact():
    c2 = {
        "schema_version": "1.0", "book_id": "book01", "page_id": "book01_p03", "page_no": 3,
        "status": "ok", "image_width": 100, "image_height": 120,
        "description": "d", "scene_tags": [], "safety": {"pass": True, "flags": []},
        "objects": [{"object_id": "book01_p03_o01", "label": "兔子",
                     "bbox": [1, 2, 10, 12], "confidence": 0.9}],
        "elapsed_ms": 1, "backend": "fixture",
    }
    raw = json.dumps(c2, ensure_ascii=False).encode("utf-8")
    sidecar = refs.build_refs(
        identity=IDENTITY, page_id="book01_p03", c2_doc=c2,
        c2_relative_path="json/book01_p03_vlm.json", c2_bytes=raw,
        component_mode="fixture", model_ref="fixture/1",
        prompt_sha256="4" * 64, evidence_ref="e1",
    )
    assert set(sidecar) == {"schema_version", "c2", "source", "observations", *IDENTITY}
    assert "identity" not in sidecar
    assert "contract_status" not in sidecar
    assert sidecar["c2"]["sha256"] == refs.sha256_bytes(raw)
    assert sidecar["source"]["component_mode"] == "fixture"
    assert sidecar["observations"][0]["appearance"] == {"visible_features": []}
