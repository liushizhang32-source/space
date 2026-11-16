"""V1.2.1 专项测试：安全边界、路径安全、C1 关联、超量、置信度、取消。

对应独立审查的四条 P0 与 P1-5/6/8/9/10；不联网，全部用假后端。
"""

from __future__ import annotations

import hashlib
import json
import re
import math
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

from vision import worker
from vision.backends.base import OcrLine, VlmObject, VlmResult
from vision.backends.qwen_vl import QwenVlBackend, VlmOutputOverflow

from _helpers import c1_binding, temp_dir

IDENTITY = {
    "job_id": "job_02",
    "page_id": "book01_p01",
    "generation_id": "gen_02",
    "input_revision": 3,
    "epoch": 4,
    "attempt_id": "att_02",
    "fencing_token": "tok_fedcba9876543210",
}


class _Ocr:
    name = "fake-ocr"

    def __init__(self, lines=None):
        self.lines = lines

    def available(self):
        return True, ""

    def recognize(self, image):
        return self.lines if self.lines is not None else [OcrLine("Hi", (1.0, 2.0, 30.0, 40.0), 0.9)]


class _Vlm:
    name = "fake-vlm"

    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc

    def available(self):
        return True, ""

    def understand(self, image, ocr_text):
        if self.exc is not None:
            raise self.exc
        return self.result


def _image(tmp: Path) -> Path:
    path = tmp / "page.png"
    Image.new("RGB", (200, 260), "white").save(path)
    return path


def _ocr_doc(tmp: Path) -> Path:
    image = _image(tmp)
    request = {
        "protocol": worker.PROTOCOL,
        "stage": "ocr",
        "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
        "outputs": {"c1": "json/book01_p01_ocr.json", "c2": "json/book01_p01_vlm.json", "sidecar": "json/book01_p01_refs.json"},
        **IDENTITY,
    }
    envelope, code = worker.process_request(request, cwd=tmp, ocr_backend=_Ocr())
    assert code == 0, envelope
    return tmp / "json/book01_p01_ocr.json"


def _ok_result(**overrides) -> VlmResult:
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
        payload["safety_raw"] = {
            "pass": payload["safety_pass"],
            "flags": payload["safety_flags"],
        }
    return VlmResult(**payload)


def _vlm_request(tmp: Path, *, c1_path: Path | None = None, **overrides) -> dict:
    image = _image(tmp)
    c1 = (c1_path or _ocr_doc(tmp)).resolve()
    # M1 基准：inputs.c1 绝对路径；image_sha256 在请求顶层；
    # c1_binding.identity 是 OCR attempt 的七元（attempt/token 与本次不同）。
    request = {
        "protocol": worker.PROTOCOL,
        "stage": "vlm",
        "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
        "outputs": {"c1": "json/book01_p01_ocr.json", "c2": "json/book01_p01_vlm.json", "sidecar": "json/book01_p01_refs.json"},
        "inputs": {"c1": str(c1)},
        **IDENTITY,
    }
    request.update(overrides)
    request.setdefault(
        "c1_binding",
        c1_binding(request, c1.read_bytes(), image.read_bytes()),
    )
    return request


# ---------------------------------------------------------------- 安全边界


def _assert_blocked(result: VlmResult, expected_reason: str) -> None:
    with temp_dir() as tmp:
        request = _vlm_request(tmp)
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(result))
        assert code == 1, envelope
        assert envelope["code"] == 3004, envelope
        assert not (tmp / "json/book01_p01_vlm.json").exists()
        assert expected_reason in envelope["msg"], envelope["msg"]


def test_safety_string_true_is_blocked():
    _assert_blocked(_ok_result(safety_pass="true"), "safety_pass_not_true")


def test_safety_number_one_is_blocked():
    _assert_blocked(_ok_result(safety_pass=1), "safety_pass_not_true")


def test_safety_missing_source_is_blocked():
    _assert_blocked(_ok_result(safety_source="unavailable"), "safety_source_untrusted")


def test_safety_blank_flag_is_blocked():
    _assert_blocked(_ok_result(safety_flags=["  "]), "safety_flag_blank")


def test_safety_flags_not_list_is_blocked():
    _assert_blocked(_ok_result(safety_flags="violence"), "safety_flags_not_list")


def test_safety_pass_with_flag_is_conflict():
    _assert_blocked(_ok_result(safety_flags=["violence"]), "flag:violence")


# ---------------------------------------------------------------- 路径安全


def test_path_collision_between_artifacts_is_rejected():
    with temp_dir() as tmp:
        request = _vlm_request(tmp)
        request["outputs"]["sidecar"] = request["outputs"]["c2"]
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(_ok_result()))
        assert code == 2, envelope
        assert envelope["code"] == 9001
        assert "outputs.sidecar" in envelope["msg"]


def test_artifact_colliding_with_result_path_is_rejected():
    with temp_dir() as tmp:
        request = _vlm_request(tmp)
        request["outputs"]["c2"] = "result.json"
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(_ok_result()))
        assert code == 2
        assert "outputs.c2" in envelope["msg"]


def test_existing_output_is_not_overwritten():
    with temp_dir() as tmp:
        request = _vlm_request(tmp)
        target = tmp / "json/book01_p01_vlm.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{\"keep\": true}", encoding="utf-8")
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(_ok_result()))
        assert code == 2, envelope
        assert "已存在" in envelope["msg"]
        assert target.read_text("utf-8") == "{\"keep\": true}"


def test_symlinked_output_is_rejected():
    with temp_dir() as tmp:
        request = _vlm_request(tmp)
        real = tmp / "real.json"
        real.write_text("{}", encoding="utf-8")
        link = tmp / "link.json"
        try:
            os.symlink(real, link)
        except (OSError, NotImplementedError):  # Windows 无权限时跳过
            return
        request["outputs"]["c2"] = "link.json"
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(_ok_result()))
        assert code == 2, envelope
        assert "符号链接" in envelope["msg"]


# ---------------------------------------------------------------- C1 关联


def test_c1_sha256_mismatch_is_rejected():
    with temp_dir() as tmp:
        request = _vlm_request(tmp)
        request["c1_binding"]["sha256"] = "0" * 64
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(_ok_result()))
        assert code == 1
        assert envelope["code"] == 9001
        assert "sha256" in envelope["msg"].lower()


def test_c1_cross_page_is_rejected():
    with temp_dir() as tmp:
        c1 = _ocr_doc(tmp)
        doc = json.loads(c1.read_text("utf-8"))
        doc["page_id"] = "book02_p01"
        c1.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        request = _vlm_request(tmp, c1_path=c1)
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(_ok_result()))
        assert code == 1
        assert envelope["code"] == 9001
        assert "page_id" in envelope["msg"]


def test_c1_old_revision_size_is_rejected():
    with temp_dir() as tmp:
        c1 = _ocr_doc(tmp)
        doc = json.loads(c1.read_text("utf-8"))
        doc["image_width"] = 999
        c1.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        request = _vlm_request(tmp, c1_path=c1)
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(_ok_result()))
        assert code == 1
        assert "尺寸" in envelope["msg"]


def test_image_sha256_mismatch_is_rejected():
    with temp_dir() as tmp:
        request = _vlm_request(tmp)
        request["image_sha256"] = "f" * 64
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(_ok_result()))
        assert code in (1, 2), envelope
        assert envelope["code"] == 9001
        assert "image_sha256" in envelope["msg"]


def test_c1_binding_image_hash_mismatch_is_rejected():
    with temp_dir() as tmp:
        request = _vlm_request(tmp)
        request["c1_binding"]["image_sha256"] = "e" * 64
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(_ok_result()))
        assert code in (1, 2), envelope
        assert envelope["code"] == 9001
        assert "c1_binding.image_sha256" in envelope["msg"]


def test_missing_c1_is_contract_error_not_internal_ocr():
    with temp_dir() as tmp:
        request = _vlm_request(tmp)
        del request["inputs"]["c1"]
        vlm = _Vlm(_ok_result())
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=vlm)
        assert code in (1, 2), envelope
        assert envelope["code"] == 9001
        assert "inputs" in envelope["msg"] and "c1" in envelope["msg"]


# ---------------------------------------------------------------- 超量 / 置信度


def test_ocr_blocks_over_limit_is_structured_1004():
    with temp_dir() as tmp:
        lines = [OcrLine("x", (1.0, 1.0, 10.0, 10.0), 0.9)] * (worker.MAX_OCR_BLOCKS + 1)
        image = _image(tmp)
        request = {
            "protocol": worker.PROTOCOL,
            "stage": "ocr",
            "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
            "outputs": {"c1": "json/book01_p01_ocr.json", "c2": "json/book01_p01_vlm.json", "sidecar": "json/book01_p01_refs.json"},
            **IDENTITY,
        }
        envelope, code = worker.process_request(request, cwd=tmp, ocr_backend=_Ocr(lines))
        assert code == 1
        assert envelope["code"] == 1004
        assert "ocr_blocks" in envelope["msg"], envelope["msg"]
        assert str(worker.MAX_OCR_BLOCKS + 1) in envelope["msg"], envelope["msg"]
        assert not (tmp / "json/book01_p01_ocr.json").exists()


def test_objects_overflow_is_structured_1004():
    with temp_dir() as tmp:
        request = _vlm_request(tmp)
        envelope, code = worker.process_request(
            request, cwd=tmp, vlm_backend=_Vlm(exc=VlmOutputOverflow(40, 12))
        )
        assert code == 1
        assert envelope["code"] == 1004
        assert "objects 40>12" in envelope["msg"], envelope["msg"]


def test_confidence_rejects_bool_nan_and_string():
    content = json.dumps(
        {
            "description": "d",
            "objects": [
                {"label": "人", "bbox": [10, 10, 100, 100], "confidence": True},
                {"label": "狗", "bbox": [200, 200, 300, 300], "confidence": "0.9"},
                {"label": "树", "bbox": [400, 400, 500, 500], "confidence": "nan"},
            ],
            "scene_tags": [],
            "safety": {"pass": True, "flags": []},
        }
    )
    result = QwenVlBackend._parse(content, (1000, 1000))
    assert [obj.confidence for obj in result.objects] == [0.0, 0.0, 0.0]
    assert result.confidence_missing == 3
    assert all(not math.isnan(obj.confidence) for obj in result.objects)


def test_nan_literal_is_rejected_before_parsing():
    # 非有限数字不是合法 JSON；strictjson 在解析层就拒绝，交给上层 3004
    content = (
        '{"description":"d","objects":[{"label":"树","bbox":[1,1,9,9],'
        '"confidence":NaN}],"scene_tags":[],"safety":{"pass":true,"flags":[]}}'
    )
    from vision.backends.qwen_vl import VlmUnsafeOutput

    try:
        QwenVlBackend._parse(content, (100, 100))
    except VlmUnsafeOutput as exc:
        assert exc.kind == "non_finite_number"
    else:
        raise AssertionError("NaN 必须被拒绝")


# ---------------------------------------------------------------- 执行边界


def test_child_process_timeout_is_killed_and_reaped():
    with temp_dir() as tmp:
        started = __import__("time").perf_counter()
        try:
            worker._run_child(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=tmp,
                timeout=1.0,
            )
        except subprocess.TimeoutExpired:
            pass
        else:  # pragma: no cover
            raise AssertionError("应当超时")
        elapsed = __import__("time").perf_counter() - started
        assert elapsed < 15, elapsed


def test_sidecar_candidate_contract_fields():
    with temp_dir() as tmp:
        request = _vlm_request(tmp)
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(_ok_result()))
        assert code == 0, envelope
        sidecar = json.loads(
            (tmp / "json/book01_p01_refs.json").read_text("utf-8")
        )
        assert sidecar["schema_version"] == "vision_refs/0.1"
        assert "identity" not in sidecar
        assert "contract_status" not in sidecar
        assert "c1_sha256" not in sidecar
        for key in worker.IDENTITY_FIELDS:  # 协议要求顶层扁平七元
            assert sidecar[key] == IDENTITY[key]
        assert sidecar["c2"]["asset_id"] == "book01_p01_vlm"
        assert sidecar["c2"]["schema_version"] == "1.0"
        assert re.fullmatch(r"[0-9a-f]{64}", sidecar["source"]["prompt_sha256"])
        assert sidecar["source"]["component_mode"] in ("fixture", "stub")
        obs = sidecar["observations"][0]
        # M1 Gate 不接受 clothing=null，默认省略该键（未知而非伪造空串）
        assert "clothing" not in obs["appearance"]
        assert obs["appearance"]["visible_features"] == []
        assert isinstance(obs["confidence"]["calibrated"], bool)
        assert obs["confidence"]["calibrated"] is False
        assert sidecar["c2"]["sha256"] == hashlib.sha256(
            (tmp / "json/book01_p01_vlm.json").read_bytes()
        ).hexdigest()


def test_raw_flags_loss_is_detected():
    # V1.2.2 P0-1：解析层把 ["violence"] 变成 [] 时，必须由原始 raw 兜住
    result = _ok_result(safety_flags=[], safety_raw={"pass": True, "flags": ["violence"]})
    _assert_blocked(result, "flag:violence")


def test_raw_flags_loss_reported_as_mismatch():
    result = _ok_result(safety_flags=[], safety_raw={"pass": True, "flags": ["violence"]})
    with temp_dir() as tmp:
        request = _vlm_request(tmp)
        envelope, code = worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(result))
        assert code == 1, envelope
        assert envelope["code"] == 3004, envelope
        assert "safety_flags_mismatch" in envelope["msg"], envelope["msg"]


def test_missing_flags_field_is_blocked():
    _assert_blocked(_ok_result(safety_flags=[], safety_raw={"pass": True}), "safety_flags_missing")


def test_unknown_flag_is_blocked():
    _assert_blocked(
        _ok_result(safety_flags=["unknown_thing_xyz"], safety_raw={"pass": True, "flags": ["unknown_thing_xyz"]}),
        "flag:unknown_thing_xyz",
    )


def test_safety_object_missing_is_blocked():
    _assert_blocked(_ok_result(safety_raw=None), "safety_missing")
