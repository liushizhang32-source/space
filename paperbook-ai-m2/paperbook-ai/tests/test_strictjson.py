"""重复 JSON 键必须 fail-closed（V1.2.2 审查阻塞项）。

复现路径：`{"safety":{"pass":true,"flags":["violence"],"flags":[]}}`
Python 默认解析会把前一个 flags 覆盖成 `[]`，安全信息在进入判定前就丢了。
这些用例锁死“解析层直接拒绝”，并且验证上层不产出 C2/Sidecar。
"""

import hashlib
import json
import os
from pathlib import Path

from PIL import Image

from _helpers import c1_binding, temp_dir

from vision import pipeline, strictjson, worker
from vision.backends.base import OcrLine, VlmObject, VlmResult
from vision.backends.qwen_vl import QwenVlBackend, VlmUnsafeOutput
from vision.strictjson import StrictJsonError

SAFETY_DUP = (
    '{"description":"d","objects":[],"scene_tags":[],'
    '"safety":{"pass":true,"flags":["violence"],"flags":[]}}'
)


def _rejects(text: str) -> StrictJsonError:
    try:
        strictjson.loads(text)
    except StrictJsonError as exc:
        return exc
    raise AssertionError(f"应拒绝重复键: {text}")


def test_duplicate_key_top_level_rejected():
    exc = _rejects('{"a":1,"a":2}')
    assert exc.kind == "duplicate_key" and exc.key == "a"


def test_duplicate_key_nested_object_rejected():
    exc = _rejects('{"outer":{"x":1,"x":2}}')
    assert exc.kind == "duplicate_key" and exc.key == "x"


def test_duplicate_pass_rejected():
    exc = _rejects('{"safety":{"pass":false,"pass":true,"flags":[]}}')
    assert exc.key == "pass"


def test_duplicate_flags_rejected():
    exc = _rejects(SAFETY_DUP)
    assert exc.key == "flags"


def test_duplicate_safety_object_rejected():
    exc = _rejects('{"safety":{"pass":true,"flags":[]},"safety":{"pass":false,"flags":["violence"]}}')
    assert exc.key == "safety"


def test_duplicate_inside_array_element_rejected():
    exc = _rejects('{"objects":[{"label":"人","label":"狗","bbox":[1,1,9,9]}]}')
    assert exc.key == "label"


def test_non_finite_number_rejected():
    exc = _rejects('{"x":NaN}')
    assert exc.kind == "non_finite_number"


def test_vlm_parse_refuses_to_lose_flags():
    # 关键回归：旧行为是 pass=true, flags=[]，现在必须直接抛
    try:
        QwenVlBackend._parse(SAFETY_DUP, (100, 100))
    except VlmUnsafeOutput as exc:
        assert exc.kind == "duplicate_key" and exc.key == "flags"
    else:
        raise AssertionError("重复 flags 必须被拒绝，不能静默覆盖")


class _UnsafeVlm:
    name = "unsafe-vlm"

    def available(self):
        return True, ""

    def understand(self, image, ocr_text):
        raise VlmUnsafeOutput("duplicate_key", key="flags")


class _Ocr:
    name = "fake-ocr"

    def available(self):
        return True, ""

    def recognize(self, image, **_kw):
        return [OcrLine("hello", (0.0, 0.0, 40.0, 10.0), 0.9)]


IDENTITY = dict(
    job_id="job_dupe", page_id="book01_p01", generation_id="gen_dupe",
    input_revision=1, epoch=1, attempt_id="att_dupe",
    fencing_token="tok_0123456789abcdef",
)


def _c1_request(tmp: Path, image: Path) -> dict:
    return {
        "protocol": worker.PROTOCOL, "stage": "ocr", "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
        "outputs": {"c1": "json/book01_p01_ocr.json", "c2": "json/book01_p01_vlm.json", "sidecar": "json/book01_p01_refs.json"}, **IDENTITY,
    }


def _vlm_request(tmp: Path, image: Path, c1: Path) -> dict:
    return {
        "protocol": worker.PROTOCOL, "stage": "vlm", "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
        "outputs": {"c1": "json/book01_p01_ocr.json", "c2": "json/book01_p01_vlm.json", "sidecar": "json/book01_p01_refs.json"},
        "inputs": {"c1": str(c1)},
        "c1_binding": c1_binding(IDENTITY, c1.read_bytes(), Path(image).read_bytes()),
        **IDENTITY,
    }


def test_worker_blocks_unsafe_output_without_artifacts():
    with temp_dir() as tmp:
        image = tmp / "page.png"
        Image.new("RGB", (200, 260), "white").save(image)
        env, code = worker.process_request(_c1_request(tmp, image), cwd=tmp, ocr_backend=_Ocr())
        assert code == 0, env
        c1 = tmp / "json/book01_p01_ocr.json"
        env, code = worker.process_request(
            _vlm_request(tmp, image, c1), cwd=tmp, vlm_backend=_UnsafeVlm()
        )
        assert code == 1, env
        assert env["code"] == 3004, env
        assert "model_output_duplicate_key" in env["msg"], env["msg"]
        assert not (tmp / "json/book01_p01_vlm.json").exists()
        assert not (tmp / "json/book01_p01_refs.json").exists()


def test_pipeline_blocks_unsafe_output_without_c2():
    with temp_dir() as root:
        image = root / "page.png"
        Image.new("RGB", (400, 600), "white").save(image)
        result = pipeline.run_page(
            image_path=image, book_id="book05", page_no=1,
            data_dir=root / "data", ocr_backend=_Ocr(), vlm_backend=_UnsafeVlm(),
        )
        assert result.vlm is None
        assert result.vlm_error is not None and result.vlm_error.code == 3004
        assert not (root / "data" / "json" / "book05_p01_vlm.json").exists()


def test_request_with_duplicate_keys_is_rejected():
    with temp_dir() as tmp:
        request = tmp / "request.json"
        request.write_text(
            '{"protocol":"m1-vision-worker/0.1","stage":"ocr",'
            '"page_id":"book01_p01","page_id":"book02_p02","image_path":"x.png"}',
            encoding="utf-8",
        )
        before = os.getcwd()
        os.chdir(tmp)
        try:
            code = worker.main([str(request)])
        finally:
            os.chdir(before)
        assert code == worker.EXIT_BAD_REQUEST
        assert not (tmp / "result.json").exists()

