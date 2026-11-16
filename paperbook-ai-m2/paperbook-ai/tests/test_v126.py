"""V1.2.6 复审 T01–T12：混合安全字段、旧索引旁路、clothing 与 M1 Gate 兼容。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from _helpers import c1_binding, temp_dir

from vision import contracts, index, refs as refs_mod, worker
from vision.backends.base import OcrLine, VlmObject, VlmResult
from vision.safety import SafetyBlocked, SafetyVerdict, issue_clearance, parse_safety

IDENTITY = {
    "job_id": "job_v126",
    "page_id": "book01_p01",
    "generation_id": "gen_v126",
    "input_revision": 3,
    "epoch": 3,
    "attempt_id": "att_v126",
    "fencing_token": "tok_0123456789abcdef",
}


class _Ocr:
    name = "fixture-ocr"

    def available(self):
        return True, ""

    def recognize(self, image):
        return [OcrLine("Hello page", (10.0, 10.0, 120.0, 40.0), 0.97)]


class _Vlm:
    name = "fixture-vlm"

    def __init__(self, result: VlmResult):
        self.result = result

    def available(self):
        return True, ""

    def understand(self, *args, **kwargs):
        return self.result


def _result(**overrides) -> VlmResult:
    payload = dict(
        description="画面",
        safety_pass=True,
        objects=[VlmObject("孩子", (5.0, 5.0, 50.0, 60.0), 0.7)],
        scene_tags=["草地"],
        safety_flags=[],
        safety_source="model",
        confidence_missing=0,
    )
    payload.update(overrides)
    if "safety_raw" not in overrides:
        payload["safety_raw"] = {"pass": payload["safety_pass"], "flags": payload["safety_flags"]}
    return VlmResult(**payload)


def _page(tmp: Path) -> Path:
    path = tmp / "page.png"
    Image.new("RGB", (200, 260), "white").save(path)
    return path


def _ocr_request(tmp: Path, image: Path) -> dict:
    return {
        "protocol": worker.PROTOCOL,
        "stage": "ocr",
        "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
        "outputs": {"c1": "json/book01_p01_ocr.json", "c2": "json/book01_p01_vlm.json", "sidecar": "json/book01_p01_refs.json"},
        **IDENTITY,
    }


def _vlm_request(tmp: Path, image: Path, c1: Path) -> dict:
    digest = hashlib.sha256(c1.read_bytes()).hexdigest()
    return {
        "protocol": worker.PROTOCOL,
        "stage": "vlm",
        "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
        "outputs": {"c1": "json/book01_p01_ocr.json", "c2": "json/book01_p01_vlm.json", "sidecar": "json/book01_p01_refs.json"},
        "inputs": {"c1": str(c1)},
        "c1_binding": c1_binding(IDENTITY, c1.read_bytes(), image.read_bytes()),
        **IDENTITY,
    }


def _run_vlm(tmp: Path, result: VlmResult) -> dict:
    image = _page(tmp)
    env, code = worker.process_request(_ocr_request(tmp, image), cwd=tmp, ocr_backend=_Ocr())
    assert code == 0, env
    c1 = tmp / "json/book01_p01_ocr.json"
    env, code = worker.process_request(_vlm_request(tmp, image, c1), cwd=tmp, vlm_backend=_Vlm(result))
    return env


def _assert_blocked(env: dict, reason: str) -> None:
    assert env["code"] == 3004, env
    assert reason in env["msg"], env["msg"]


# ---------------------------------------------------------------- 安全字段


def test_absolute_c1_path_is_accepted():
    with temp_dir() as tmp:
        image = _page(tmp)
        env, code = worker.process_request(_ocr_request(tmp, image), cwd=tmp, ocr_backend=_Ocr())
        assert code == 0, env
        c1 = tmp / "json/book01_p01_ocr.json"
        request = _vlm_request(tmp, image, c1)
        assert Path(request["inputs"]["c1"]).is_absolute()  # M1 基准：绝对路径
        env, code = worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(_result()))
        assert code == 0, env


def test_missing_c1_binding_is_rejected():
    with temp_dir() as tmp:
        image = _page(tmp)
        env, code = worker.process_request(_ocr_request(tmp, image), cwd=tmp, ocr_backend=_Ocr())
        assert code == 0, env
        c1 = tmp / "json/book01_p01_ocr.json"
        request = _vlm_request(tmp, image, c1)
        del request["c1_binding"]
        env, code = worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(_result()))
        assert code != 0 and env["code"] == 9001, env
        assert not (tmp / "json/book01_p01_vlm.json").exists()


def test_t01_pass_and_flags_mixed_is_blocked():
    env = _run_vlm_with(_result(safety_raw={"pass": True, "flags": ["violence"]}))
    _assert_blocked(env, "flag:violence")


def test_t02_flags_missing_or_null_is_blocked():
    missing = _run_vlm_with(_result(safety_raw={"pass": True}))
    _assert_blocked(missing, "safety_flags_missing")
    null = _run_vlm_with(_result(safety_raw={"pass": True, "flags": None}))
    _assert_blocked(null, "safety_flags_null")


def test_t03_flags_wrong_type_is_blocked():
    env = _run_vlm_with(_result(safety_raw={"pass": True, "flags": "violence"}))
    _assert_blocked(env, "safety_flags_not_list")
    nested = _run_vlm_with(_result(safety_raw={"pass": True, "flags": [["violence"]]}))
    _assert_blocked(nested, "safety_flag_not_string")


def test_t04_unknown_risk_marker_is_blocked():
    flag = _run_vlm_with(_result(safety_raw={"pass": True, "flags": ["weird_new_risk"]}))
    _assert_blocked(flag, "flag:weird_new_risk")
    field = _run_vlm_with(_result(safety_raw={"pass": True, "flags": [], "score": 0.9}))
    _assert_blocked(field, "safety_unknown_field:score")


def test_t05_contradictory_safety_fields_are_blocked():
    env = _run_vlm_with(
        _result(safety_flags=["violence"], safety_raw={"pass": True, "flags": []})
    )
    _assert_blocked(env, "safety_flags_mismatch")


def _run_vlm_with(result: VlmResult) -> dict:
    with temp_dir() as tmp:
        return _run_vlm(tmp, result)


# ---------------------------------------------------------------- 旧索引旁路


def _safe_doc():
    return contracts.build_vlm_document(
        book_id="book01",
        page_id="book01_p01",
        page_no=1,
        image_width=200,
        image_height=260,
        description="画面",
        objects=[VlmObject("孩子", (10, 10, 90, 120), 0.8)],
        scene_tags=["草地"],
        safety_pass=True,
        safety_flags=[],
        elapsed_ms=1,
        backend="fixture",
    )


def _write_vlm_json(tmp: Path, doc: dict) -> Path:
    path = tmp / "json" / "book01_p01_vlm.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def test_t06_gate_runs_before_old_index_load():
    with temp_dir() as tmp:
        page_index = index.build_from_vlm(_safe_doc())
        index.save(page_index, tmp)
        unsafe = _safe_doc()
        unsafe["safety"] = {"pass": True, "flags": ["violence"]}
        _write_vlm_json(tmp, unsafe)
        try:
            index.load_after_gate(tmp, "book01_p01")
        except index.UnsafeIndexError as exc:
            assert "flag:violence" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("旧索引不得绕过安全门禁")


def test_t07_bare_load_requires_clearance():
    with temp_dir() as tmp:
        index.save(index.build_from_vlm(_safe_doc()), tmp)
        try:
            index.load(tmp, "book01_p01")
        except index.UnsafeIndexError as exc:
            assert "凭证" in str(exc) or "clearance" in str(exc).lower()
        else:  # pragma: no cover
            raise AssertionError("无安全凭证的加载必须拒绝")


def test_t08_failed_retry_cannot_reuse_success():
    with temp_dir() as tmp:
        image = _page(tmp)
        env, code = worker.process_request(_ocr_request(tmp, image), cwd=tmp, ocr_backend=_Ocr())
        assert code == 0, env
        c1 = tmp / "json/book01_p01_ocr.json"
        # 第一次成功
        ok = _result()
        env, code = worker.process_request(_vlm_request(tmp, image, c1), cwd=tmp, vlm_backend=_Vlm(ok))
        assert code == 0, env
        c2 = tmp / "json/book01_p01_vlm.json"
        assert c2.exists()
        # 第二次（异常重跑）必须 fail-closed：M1 每个 attempt 用全新目录，
        # 同目录已有产物说明不是同一次执行，拒绝覆盖，不得返回成功。
        bad = _result(safety_raw={"pass": True, "flags": ["violence"]})
        env, code = worker.process_request(_vlm_request(tmp, image, c1), cwd=tmp, vlm_backend=_Vlm(bad))
        assert code != 0 and env["code"] in (3004, 9001), env
        assert env.get("artifacts") in (None, {})


def test_t09_blocked_task_leaves_no_consumable_index():
    with temp_dir() as tmp:
        image = _page(tmp)
        env, code = worker.process_request(_ocr_request(tmp, image), cwd=tmp, ocr_backend=_Ocr())
        assert code == 0, env
        c1 = tmp / "json/book01_p01_ocr.json"
        bad = _result(safety_raw={"pass": False, "flags": ["violence"]})
        env, code = worker.process_request(_vlm_request(tmp, image, c1), cwd=tmp, vlm_backend=_Vlm(bad))
        assert code == 1 and env["code"] == 3004, env
        assert not (tmp / "data" / "index" / "book01_p01.json").exists()
        try:
            index.load_after_gate(tmp, "book01_p01")
        except index.UnsafeIndexError:
            pass
        else:  # pragma: no cover
            raise AssertionError("拦截后不应存在可消费索引")


# ---------------------------------------------------------------- clothing / Gate


def _refs(**kwargs):
    doc = _safe_doc()
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    return refs_mod.build_refs(
        identity={**IDENTITY},
        page_id="book01_p01",
        c2_doc=doc,
        c2_relative_path="json/book01_p01_vlm.json",
        c2_bytes=raw,
        component_mode="fixture",
        model_ref="fixture-vlm",
        prompt_sha256="0" * 64,
        evidence_ref="test",
        **kwargs,
    )


def test_t10_clothing_valid_value_is_preserved():
    sidecar = _refs(clothing="蓝色外套")
    obs = sidecar["observations"][0]
    assert obs["appearance"]["clothing"] == "蓝色外套"


def test_t11_clothing_missing_and_null_modes():
    default = _refs()
    assert "clothing" not in default["observations"][0]["appearance"]
    try:
        _refs(clothing="")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("空白 clothing 必须拒绝")


def test_t12_sidecar_matches_m1_gate_fields():
    sidecar = _refs()
    assert sidecar["schema_version"] == "vision_refs/0.1"
    assert "identity" not in sidecar
    assert "contract_status" not in sidecar
    for key in worker.IDENTITY_FIELDS:  # 顶层扁平七元
        assert sidecar[key] == IDENTITY[key]
    assert sidecar["source"]["component_mode"] in ("fixture", "stub")
    assert sidecar["c2"]["sha256"] == hashlib.sha256(
        json.dumps(_safe_doc(), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    obs = sidecar["observations"][0]
    assert obs["identity_status"] in ("unknown", "ambiguous")
    assert obs["confidence"]["kind"] == "model_estimate"
    assert obs["confidence"]["calibrated"] is False
    assert obs["object_id"].startswith("book01_p01_")
