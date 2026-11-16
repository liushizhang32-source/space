"""V1.2.4 复审 P0 回归：超量拒绝、部分写入清理、旧索引入口安全门禁。"""

import hashlib
import json
from pathlib import Path

from PIL import Image

from _helpers import c1_binding, temp_dir

from vision import contracts, index as index_mod, worker
from vision.backends.base import OcrLine, VlmObject, VlmResult
from vision.contracts import ContractLimitError
from vision.index import UnsafeIndexError
from vision.safety import SafetyVerdict, issue_clearance

IDENTITY = dict(
    job_id="job_p0", page_id="book01_p01", generation_id="gen_p0",
    input_revision=1, epoch=1, attempt_id="att_p0",
    fencing_token="tok_0123456789abcdef",
)


class _Ocr:
    name = "fake-ocr"

    def __init__(self, count=1):
        self._count = count

    def available(self):
        return True, ""

    def recognize(self, image, **_kw):
        return [OcrLine("hi", (0.0, 0.0, 40.0, 10.0), 0.9) for _ in range(self._count)]


class _Vlm:
    name = "fake-vlm"

    def __init__(self, objects=None, *, flags=None, pass_value=True):
        self._objects = objects or [VlmObject("男孩", (10, 10, 60, 90), 0.9)]
        self._flags = [] if flags is None else flags
        self._pass = pass_value

    def available(self):
        return True, ""

    def understand(self, image, ocr_text):
        return VlmResult(
            description="画面",
            safety_pass=self._pass,
            objects=list(self._objects),
            safety_flags=list(self._flags),
            safety_raw={"pass": self._pass, "flags": list(self._flags)},
            safety_source="model",
        )


def _img(tmp: Path) -> Path:
    path = Path(tmp) / "page.png"
    Image.new("RGB", (200, 260), "white").save(path)
    return path


def _ocr_req(image: Path, page="book01_p01") -> dict:
    return {
        "protocol": worker.PROTOCOL, "stage": "ocr", "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
        "outputs": {"c1": f"json/{page}_ocr.json", "c2": f"json/{page}_vlm.json", "sidecar": f"json/{page}_refs.json"},
        **{**IDENTITY, "page_id": page},
    }


def _vlm_req(image: Path, c1: Path, page="book01_p01") -> dict:
    import hashlib

    return {
        "protocol": worker.PROTOCOL, "stage": "vlm", "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
        "outputs": {"c1": f"json/{page}_ocr.json", "c2": f"json/{page}_vlm.json", "sidecar": f"json/{page}_refs.json"},
        "inputs": {"c1": str(c1)},
        "c1_binding": c1_binding({**IDENTITY, "page_id": page}, c1.read_bytes(), image.read_bytes()),
        **{**IDENTITY, "page_id": page},
    }


# ---------------------------------------------------------------- 超量


def test_contract_limit_on_text_blocks():
    blocks = [OcrLine("x", (0.0, 0.0, 10.0, 10.0), 0.9) for _ in range(contracts.MAX_ITEMS + 1)]
    try:
        contracts.build_text_blocks(
            page_id="book01_p01", lines=blocks, width=200, height=260, scale=1.0,
            to_original=lambda b: b,
        )
    except ContractLimitError as exc:
        assert exc.kind == "text_blocks" and exc.actual == contracts.MAX_ITEMS + 1
    else:
        raise AssertionError("超量文字块必须拒绝，不能静默截断")


def test_contract_limit_on_objects():
    objs = [VlmObject("男孩", (0, 0, 10, 10), 0.9) for _ in range(contracts.MAX_ITEMS + 1)]
    try:
        contracts.build_objects(
            page_id="book01_p01", objects=objs, width=200, height=260, scale=1.0,
            to_original=lambda b: b,
        )
    except ContractLimitError as exc:
        assert exc.kind == "objects"
    else:
        raise AssertionError("超量物体必须拒绝")


def test_worker_ocr_limit_is_1004_without_c1():
    with temp_dir() as tmp:
        image = _img(tmp)
        env, code = worker.process_request(
            _ocr_req(image), cwd=tmp, ocr_backend=_Ocr(contracts.MAX_ITEMS + 1)
        )
        assert code == 1 and env["code"] == 1004
        assert not (Path(tmp) / "json/book01_p01_ocr.json").exists()


def test_worker_vlm_limit_is_1004_without_c2():
    with temp_dir() as tmp:
        image = _img(tmp)
        env, code = worker.process_request(_ocr_req(image), cwd=tmp, ocr_backend=_Ocr())
        assert code == 0
        c1 = Path(tmp) / "json/book01_p01_ocr.json"
        objs = [VlmObject("男孩", (10, 10, 60, 90), 0.9) for _ in range(contracts.MAX_ITEMS + 1)]
        env, code = worker.process_request(
            _vlm_req(image, c1), cwd=tmp, vlm_backend=_Vlm(objs)
        )
        assert code == 1 and env["code"] == 1004
        assert not (Path(tmp) / "json/book01_p01_vlm.json").exists()


# ---------------------------------------------------------------- 部分写入


def test_partial_write_rolls_back_c2():
    with temp_dir() as tmp:
        image = _img(tmp)
        worker.process_request(_ocr_req(image), cwd=tmp, ocr_backend=_Ocr())
        c1 = Path(tmp) / "json/book01_p01_ocr.json"

        original = worker.refs.build_refs

        def boom(**_kw):
            raise ValueError("sidecar build failed")

        worker.refs.build_refs = boom
        try:
            env, code = worker.process_request(
                _vlm_req(image, c1), cwd=tmp, vlm_backend=_Vlm()
            )
        finally:
            worker.refs.build_refs = original
        assert code == 1 and env["code"] == 9001
        assert not (Path(tmp) / "json/book01_p01_vlm.json").exists()
        assert not (Path(tmp) / "json/book01_p01_refs.json").exists()


# ---------------------------------------------------------------- 旧索引


def _c2(**over):
    doc = {
        "schema_version": "1.0", "book_id": "book01", "page_id": "book01_p01", "page_no": 1,
        "status": "ok", "image_width": 200, "image_height": 260,
        "description": "画面", "objects": [{"object_id": "book01_p01_o01", "label": "男孩",
                                            "bbox": [10, 10, 60, 90], "confidence": 0.9}],
        "scene_tags": [], "safety": {"pass": True, "flags": []}, "elapsed_ms": 10,
    }
    doc.update(over)
    return doc


def test_index_rejects_safety_missing():
    doc = _c2()
    del doc["safety"]
    try:
        index_mod.build_from_vlm(doc)
    except UnsafeIndexError as exc:
        assert "safety_missing" in str(exc)
    else:
        raise AssertionError("缺 safety 的旧 vlm.json 不得建索引")


def test_index_rejects_nonempty_flags():
    doc = _c2(safety={"pass": True, "flags": ["violence"]})
    try:
        index_mod.build_from_vlm(doc)
    except UnsafeIndexError:
        pass
    else:
        raise AssertionError("非空 flags 不得建索引")


def test_index_rejects_string_pass():
    doc = _c2(safety={"pass": "true", "flags": []})
    try:
        index_mod.build_from_vlm(doc)
    except UnsafeIndexError:
        pass
    else:
        raise AssertionError("字符串 pass 不得建索引")


def test_index_load_rejects_duplicate_keys():
    with temp_dir() as tmp:
        target = Path(tmp) / "index/book01_p01.json"
        target.parent.mkdir(parents=True)
        target.write_text('{"page_id":"a","page_id":"b"}', encoding="utf-8")
        try:
            index_mod.load(tmp, "book01_p01", clearance=issue_clearance("book01_p01", SafetyVerdict(passed=True)))
        except ValueError as exc:
            assert "结构不可信" in str(exc)
        else:
            raise AssertionError("索引文件重复键必须拒绝")


def test_build_index_script_blocks_unsafe_page():
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("build_index", root / "scripts/build_index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    with temp_dir() as tmp:
        json_dir = Path(tmp) / "json"
        json_dir.mkdir(parents=True)
        (json_dir / "book01_p01_vlm.json").write_text(
            json.dumps(_c2(safety={"pass": False, "flags": ["violence"]})), encoding="utf-8"
        )
        rc = mod.main(["--data-dir", str(tmp)])
        assert rc == 2
        assert not (Path(tmp) / "index/book01_p01.json").exists()
