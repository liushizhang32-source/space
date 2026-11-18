"""V1.2.4 P0 回归：子进程输入与截断修复分支。

对应复审意见：
- P0-01 子进程原始 JSON 里的重复安全字段必须被拒绝，且安全类失败不能退化成普通失败；
- P0-02 截断/半截 JSON 不允许“补齐括号救回来”当成成功产物。
"""

import hashlib
import json
from pathlib import Path

from PIL import Image

from _helpers import c1_binding, temp_dir

from vision import worker
from vision.backends.base import OcrLine
from vision.backends.qwen_vl import (
    QwenVlBackend,
    VlmIncompleteOutput,
    VlmUnsafeOutput,
    _loads_json,
)

IDENTITY = dict(
    job_id="job_v124", page_id="book01_p01", generation_id="gen_v124",
    input_revision=1, epoch=1, attempt_id="att_v124",
    fencing_token="tok_0123456789abcdef",
)


class _Ocr:
    name = "fake-ocr"

    def available(self):
        return True, ""

    def recognize(self, image, **_kw):
        return [OcrLine("hi", (0.0, 0.0, 40.0, 10.0), 0.9)]


class _IncompleteVlm:
    name = "incomplete-vlm"

    def available(self):
        return True, ""

    def understand(self, image, ocr_text):
        raise VlmIncompleteOutput("model_output_incomplete: invalid_json")


# ---------------------------------------------------------------- P0-01


def test_child_payload_with_duplicate_safety_is_rejected():
    text = (
        '{"ok":true,"safety_pass":true,"safety_flags":["violence"],'
        '"safety_flags":[],"description":"d","objects":[]}'
    )
    try:
        worker._parse_child_payload(text)
    except worker.ContractViolation as exc:
        assert "duplicate_key" in str(exc)
    else:
        raise AssertionError("子进程结果里的重复键必须拒绝")


def test_child_payload_duplicate_nested_key_is_rejected():
    text = '{"ok":true,"safety":{"pass":true,"pass":false},"objects":[]}'
    try:
        worker._parse_child_payload(text)
    except worker.ContractViolation:
        pass
    else:
        raise AssertionError("嵌套重复键必须拒绝")


def test_child_unsafe_error_keeps_3004_semantics():
    payload = {
        "ok": False,
        "error_kind": "VlmUnsafeOutput",
        "kind": "duplicate_key",
        "key": "flags",
        "reason": "VlmUnsafeOutput: ...",
    }
    try:
        worker._result_or_raise(payload)
    except VlmUnsafeOutput as exc:
        assert exc.kind == "duplicate_key" and exc.key == "flags"
    else:
        raise AssertionError("安全类失败必须保持 3004 语义")


def test_child_plain_failure_is_not_safety():
    try:
        worker._result_or_raise({"ok": False, "reason": "boom"})
    except VlmUnsafeOutput:
        raise AssertionError("普通失败不应被当成安全拦截")
    except RuntimeError:
        pass
    else:
        raise AssertionError("应当抛错")


# ---------------------------------------------------------------- P0-02


def test_truncated_json_is_incomplete_not_repaired():
    try:
        _loads_json('{"description":"x","safety":{"pass":true,"flags":["violence"]')
    except VlmIncompleteOutput:
        pass
    else:
        raise AssertionError("半截 JSON 不允许被修复成成功")


def test_unbalanced_braces_are_not_auto_closed():
    # 旧实现会补一个 } 让它解析成功
    try:
        _loads_json('{"description":"x"')
    except VlmIncompleteOutput:
        pass
    else:
        raise AssertionError("缺右括号不得自动补齐后返回成功")


def test_duplicate_key_still_distinguishable_from_truncation():
    try:
        _loads_json('{"a":1,"a":2}')
    except VlmUnsafeOutput:
        pass
    except VlmIncompleteOutput:
        raise AssertionError("重复键不应被当成截断")
    else:
        raise AssertionError("重复键必须拒绝")


def test_parse_maps_truncation_to_incomplete():
    try:
        QwenVlBackend._parse('{"description":"x"', (100, 100))
    except VlmIncompleteOutput:
        pass
    else:
        raise AssertionError("_parse 遇到截断必须抛 VlmIncompleteOutput")


# ---------------------------------------------------------------- 端点


def _c1_request(image: Path) -> dict:
    return {
        "protocol": worker.PROTOCOL, "stage": "ocr", "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
        "outputs": {"c1": "json/book01_p01_ocr.json", "c2": "json/book01_p01_vlm.json", "sidecar": "json/book01_p01_refs.json"}, **IDENTITY,
    }


def _vlm_request(image: Path, c1: Path) -> dict:
    return {
        "protocol": worker.PROTOCOL, "stage": "vlm", "image_path": str(image), "result_path": "result.json", "image_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
        "outputs": {"c1": "json/book01_p01_ocr.json", "c2": "json/book01_p01_vlm.json", "sidecar": "json/book01_p01_refs.json"},
        "inputs": {"c1": str(c1)},
        "c1_binding": c1_binding(IDENTITY, c1.read_bytes(), image.read_bytes()),
        **IDENTITY,
    }


def test_worker_incomplete_output_is_2001_without_artifacts():
    with temp_dir() as tmp:
        image = tmp / "page.png"
        Image.new("RGB", (200, 260), "white").save(image)
        env, code = worker.process_request(_c1_request(image), cwd=tmp, ocr_backend=_Ocr())
        assert code == 0, env
        c1 = Path(tmp) / "json/book01_p01_ocr.json"
        env, code = worker.process_request(
            _vlm_request(image, c1), cwd=tmp, vlm_backend=_IncompleteVlm()
        )
        assert code == 1
        assert env["code"] == 2001
        assert env["transient"] is True
        assert env["msg"] == "model_output_incomplete"
        assert not (Path(tmp) / "json/book01_p01_vlm.json").exists()
        assert not (Path(tmp) / "json/book01_p01_refs.json").exists()
