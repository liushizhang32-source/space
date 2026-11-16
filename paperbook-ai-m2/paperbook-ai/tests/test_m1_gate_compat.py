"""用 M1 证据包里的**真实 Gate** 验收 M2 产物（只读导入，不修改 M1 代码）。

证据来源：``M1_CURRENT_GATE_HANDOFF_EVIDENCE.zip``（SHA256
``c0650eab8b2650854d4cb95c9889f204607e1484e133419308996e02396d9137``），
HEAD ``0dc2844f910d0e37ae3ef0253d7838dea1f61bfb``。
本机若没有解压后的证据目录，本组测试自动跳过（打包后不带 M1 源码）。
"""

from __future__ import annotations

import hashlib
import json

try:
    import pytest
except ImportError:  # tests/run_all.py 的无 pytest 环境
    pytest = None
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT.parent / ".m1evidence"
if EVIDENCE.exists() and str(EVIDENCE) not in sys.path:
    sys.path.insert(0, str(EVIDENCE))

from PIL import Image  # noqa: E402

from vision import worker  # noqa: E402
from vision.backends.base import OcrLine, VlmObject, VlmResult  # noqa: E402

from _helpers import c1_binding, temp_dir  # noqa: E402

AVAILABLE = (EVIDENCE / "orchestrator" / "services" / "vision_supervisor" / "gate.py").exists()
if AVAILABLE:
    # 证据包只带 gate.py / supervisor.py，没有 tree.py（进程监管实现）。
    # gate 的校验路径不使用 tree，这里放一个最小占位，避免导入失败；
    # 真正调用 start_tree/drain 的 M1 监管逻辑不在本测试范围内。
    import types

    _tree = types.ModuleType("orchestrator.services.vision_supervisor.tree")

    class ContainmentError(Exception):
        pass

    def _unused_start_tree(*args, **kwargs):
        raise RuntimeError("tree 占位实现：gate 测试不应启动进程树")

    def _unused_drain(*args, **kwargs):
        return None

    _tree.ContainmentError = ContainmentError
    _tree.start_tree = _unused_start_tree
    _tree.drain = _unused_drain
    sys.modules["orchestrator.services.vision_supervisor.tree"] = _tree

    from orchestrator.services.vision_supervisor.gate import Gate
    from orchestrator.services.vision_supervisor.supervisor import (
        Fences,
        Generation,
        Identity,
        Snapshot,
        VisionError,
    )

IDENTITY = {
    "job_id": "job_01",
    "page_id": "book01_p01",
    "generation_id": "gen_01",
    "input_revision": 1,
    "epoch": 2,
    "attempt_id": "att_01",
    "fencing_token": "tok_0123456789abcdef",
}
OCR_IDENTITY = {**IDENTITY, "attempt_id": "att_ocr", "fencing_token": "tok_ocr"}


class _Ocr:
    name = "stub-ocr"

    def recognize(self, image):
        return [OcrLine("Hello page", (20.0, 30.0, 200.0, 60.0), 0.95)]


class _Vlm:
    def __init__(self, result: VlmResult, name: str = "stub-vlm"):
        self._result = result
        self.name = name

    def understand(self, image, text):
        return self._result


def _result() -> VlmResult:
    return VlmResult(
        description="一个孩子在草地上",
        objects=[VlmObject("孩子", (10.0, 10.0, 100.0, 200.0), 0.8)],
        scene_tags=["草地"],
        safety_pass=True,
        safety_flags=[],
        safety_raw={"pass": True, "flags": []},
        safety_source="model",
    )


def _image(tmp: Path) -> Path:
    path = tmp / "page.png"
    Image.new("RGB", (240, 320), "white").save(path)
    return path


def _ocr_request(tmp: Path, image: Path) -> dict:
    return {
        "protocol": worker.PROTOCOL,
        "stage": "ocr",
        "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
        **IDENTITY,
        "outputs": {"c1": "json/book01_p01_ocr.json", "c2": "json/book01_p01_vlm.json", "sidecar": "json/book01_p01_refs.json"},
    }


def _vlm_request(tmp: Path, image: Path, c1: Path) -> dict:
    return {
        "protocol": worker.PROTOCOL,
        "stage": "vlm",
        "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
        "outputs": {"c1": "json/book01_p01_ocr.json", "c2": "json/book01_p01_vlm.json", "sidecar": "json/book01_p01_refs.json"},
        "inputs": {"c1": str(c1.resolve())},
        "c1_binding": c1_binding(IDENTITY, c1.read_bytes(), image.read_bytes()),
        **IDENTITY,
    }


def _produce(tmp: Path, backend_name: str = "stub-vlm"):
    """用 M2 Worker 真跑 OCR + VLM，返回 C1/C2/sidecar 的原始字节。"""
    image = _image(tmp)
    env, code = worker.process_request(_ocr_request(tmp, image), cwd=tmp, ocr_backend=_Ocr())
    assert code == 0, env
    c1_path = tmp / "json/book01_p01_ocr.json"
    env, code = worker.process_request(
        _vlm_request(tmp, image, c1_path), cwd=tmp, vlm_backend=_Vlm(_result(), backend_name)
    )
    assert code == 0, env
    c2_path = tmp / "json/book01_p01_vlm.json"
    sidecar_path = tmp / "json/book01_p01_refs.json"
    return image, c1_path.read_bytes(), c2_path.read_bytes(), sidecar_path.read_bytes()


def _record() -> Generation:
    record = Generation(
        IDENTITY["job_id"],
        IDENTITY["page_id"],
        IDENTITY["generation_id"],
        IDENTITY["input_revision"],
        IDENTITY["epoch"],
    )
    record.status = "running"
    record.identity = Identity(**IDENTITY)
    return record


def _snapshot(document: str, raw: bytes, *, identity=None, image_sha: str | None = None,
              c1_sha: str | None = None) -> Snapshot:
    return Snapshot(
        identity=identity or Identity(**IDENTITY),
        source_id="m2-test",
        documents={document: raw},
        image_sha256=image_sha,
        c1_sha256=c1_sha,
    )


def _accept(tmp: Path, *, produced=None, sidecar_override=None, c2_override=None):
    image, c1, c2, sidecar = produced or _produce(tmp)
    if c2_override is not None:
        c2 = c2_override
    if sidecar_override is not None:
        sidecar = sidecar_override
    image_sha = hashlib.sha256(image.read_bytes()).hexdigest()
    c1_snapshot = _snapshot(
        "c1", c1, identity=Identity(**OCR_IDENTITY), image_sha=image_sha,
        c1_sha=hashlib.sha256(c1).hexdigest(),
    )
    c2_snapshot = Snapshot(
        identity=Identity(**IDENTITY),
        source_id="m2-test",
        documents={"c2": c2, "sidecar": sidecar},
    )
    record = _record()
    fences = Fences()
    fences.pages[IDENTITY["page_id"]] = record
    fences.serial[IDENTITY["page_id"]] = threading.Lock()
    gate = Gate({"m2-test"})
    handoff = gate.accept(record, fences, c1_snapshot, c2_snapshot, (240, 320))
    return handoff, c2


def _expect_code(fn, code: int) -> None:
    try:
        fn()
    except VisionError as exc:
        assert exc.code == code, (exc.code, exc.msg)
        return
    raise AssertionError(f"期望 VisionError({code})，实际未抛异常")


def test_real_m1_gate_accepts_m2_worker_outputs():
    if not AVAILABLE:
        return
    with temp_dir() as tmp:
        handoff, c2 = _accept(tmp)
        assert handoff.c2_sha256 == hashlib.sha256(c2).hexdigest()
        assert handoff.identity == Identity(**IDENTITY)


def test_real_m1_gate_rejects_clothing_null():
    if not AVAILABLE:
        return
    with temp_dir() as tmp:
        produced = _produce(tmp)
        sidecar = produced[3]
        doc = json.loads(sidecar)
        doc["observations"][0]["appearance"] = {"clothing": None, "visible_features": []}
        _expect_code(lambda: _accept(tmp, sidecar_override=json.dumps(doc).encode(), produced=produced), 1002)


def test_real_m1_gate_rejects_non_bool_calibrated():
    if not AVAILABLE:
        return
    with temp_dir() as tmp:
        produced = _produce(tmp)
        sidecar = produced[3]
        doc = json.loads(sidecar)
        doc["observations"][0]["confidence"]["calibrated"] = 0
        _expect_code(lambda: _accept(tmp, sidecar_override=json.dumps(doc).encode(), produced=produced), 1002)


def test_real_m1_gate_rejects_bad_prompt_fingerprint():
    if not AVAILABLE:
        return
    with temp_dir() as tmp:
        produced = _produce(tmp)
        sidecar = produced[3]
        doc = json.loads(sidecar)
        doc["source"]["prompt_sha256"] = "NOT-A-HASH"
        _expect_code(lambda: _accept(tmp, sidecar_override=json.dumps(doc).encode(), produced=produced), 1002)


def test_real_m1_gate_rejects_noncanonical_c2_path():
    if not AVAILABLE:
        return
    with temp_dir() as tmp:
        produced = _produce(tmp)
        sidecar = produced[3]
        doc = json.loads(sidecar)
        doc["c2"]["relative_path"] = "json/other_vlm.json"
        _expect_code(lambda: _accept(tmp, sidecar_override=json.dumps(doc).encode(), produced=produced), 1002)


def test_real_m1_gate_rejects_identity_attempt_mismatch():
    if not AVAILABLE:
        return
    with temp_dir() as tmp:
        produced = _produce(tmp)
        sidecar = produced[3]
        doc = json.loads(sidecar)
        doc["attempt_id"] = "att_other"
        _expect_code(lambda: _accept(tmp, sidecar_override=json.dumps(doc).encode(), produced=produced), 1002)


def test_real_m1_gate_blocks_nonempty_flags():
    if not AVAILABLE:
        return
    with temp_dir() as tmp:
        doc_c2 = {
            "schema_version": "1.0",
            "book_id": "book01", "page_id": "book01_p01", "page_no": 1,
            "status": "ok", "image_width": 240, "image_height": 320,
            "text_blocks": [], "page_confidence": 0.9, "elapsed_ms": 1,
            "description": "一个孩子在草地上",
            "objects": [{"object_id": "book01_p01_o01", "label": "孩子",
                         "bbox": [10, 10, 100, 200], "confidence": 0.8}],
            "scene_tags": ["草地"],
            "safety": {"pass": True, "flags": ["violence"]},
        }
        _expect_code(lambda: _accept(tmp, c2_override=json.dumps(doc_c2).encode()), 3004)


def test_real_m1_gate_blocks_string_pass():
    if not AVAILABLE:
        return
    with temp_dir() as tmp:
        doc_c2 = {
            "schema_version": "1.0",
            "book_id": "book01", "page_id": "book01_p01", "page_no": 1,
            "status": "ok", "image_width": 240, "image_height": 320,
            "text_blocks": [], "page_confidence": 0.9, "elapsed_ms": 1,
            "description": "一个孩子在草地上",
            "objects": [], "scene_tags": [],
            "safety": {"pass": "true", "flags": []},
        }
        _expect_code(lambda: _accept(tmp, c2_override=json.dumps(doc_c2).encode()), 3004)


def test_real_m1_gate_rejects_c1_image_hash_mismatch():
    if not AVAILABLE:
        return
    with temp_dir() as tmp:
        image, c1, _, _ = _produce(tmp)
        snapshot = _snapshot(
            "c1", c1, identity=Identity(**OCR_IDENTITY),
            image_sha="0" * 64, c1_sha=hashlib.sha256(c1).hexdigest(),
        )
        _expect_code(
            lambda: Gate.bound_c1(snapshot, Identity(**IDENTITY),
                                  hashlib.sha256(image.read_bytes()).hexdigest()),
            1002,
        )


def _vlm_after_mutating_binding(tmp: Path, mutate):
    image = _image(tmp)
    env, code = worker.process_request(_ocr_request(tmp, image), cwd=tmp, ocr_backend=_Ocr())
    assert code == 0, env
    c1_path = tmp / "json/book01_p01_ocr.json"
    request = _vlm_request(tmp, image, c1_path)
    mutate(request)
    return worker.process_request(request, cwd=tmp, vlm_backend=_Vlm(_result()))


def test_cross_page_c1_binding_is_rejected():
    with temp_dir() as tmp:
        env, code = _vlm_after_mutating_binding(
            tmp, lambda req: req["c1_binding"]["identity"].__setitem__("page_id", "book01_p02")
        )
        assert code in (1, 2) and env["code"] == 9001, env
        assert "page_id" in env["msg"]


def test_old_input_revision_is_rejected():
    with temp_dir() as tmp:
        env, code = _vlm_after_mutating_binding(
            tmp, lambda req: req["c1_binding"]["identity"].__setitem__("input_revision", 9)
        )
        assert code in (1, 2) and env["code"] == 9001, env
        assert "input_revision" in env["msg"]


def test_old_generation_is_rejected():
    with temp_dir() as tmp:
        env, code = _vlm_after_mutating_binding(
            tmp, lambda req: req["c1_binding"]["identity"].__setitem__("generation_id", "gen_old")
        )
        assert code in (1, 2) and env["code"] == 9001, env
        assert "generation_id" in env["msg"]


def test_ocr_attempt_id_may_differ_from_vlm_attempt():
    """M1 的 c1_binding.identity 是 OCR attempt，attempt/token 必然不同。"""
    with temp_dir() as tmp:
        env, code = _vlm_after_mutating_binding(
            tmp, lambda req: req["c1_binding"]["identity"].__setitem__("attempt_id", "att_other")
        )
        assert code == 0, env


def test_offline_component_modes_and_real_rejection():
    if not AVAILABLE:
        return
    for backend_name, expected in (("fixture", "fixture"), ("stub", "stub")):
        with temp_dir() as tmp:
            produced = _produce(tmp, backend_name)
            sidecar = json.loads(produced[3])
            assert sidecar["source"]["component_mode"] == expected, sidecar["source"]
            handoff, _ = _accept(tmp, produced=produced)
            assert handoff.c2_sha256
    # 协议 V1.0：离线只允许 fixture/stub；real 必须在 M2 侧就被拒绝
    with temp_dir() as tmp:
        if pytest is not None:
            with pytest.raises(Exception):
                _produce(tmp, "http")
        else:
            try:
                _produce(tmp, "http")
            except Exception:
                pass
            else:
                raise AssertionError("real 必须在 M2 侧被拒绝")
