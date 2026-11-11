"""第三轮验收问题（R01–R04）的回归测试。

R01 构造/校验异常不得中断流水线
R02 安全结论必须显式，省略即报错
R03 后端返回 None 必须判失败
R04 内部校验器 / 导出 Schema 与公共契约同步
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from vision import contracts, pipeline, validate
from vision.backends.base import OcrLine, VlmResult

from _helpers import temp_dir

ROOT = Path(__file__).resolve().parents[1]


class _NullVlm:
    name = "null"

    def available(self):
        return True, ""

    def understand(self, image, ocr_text):
        return VlmResult(description="", objects=[], scene_tags=[], safety_pass=True)


class _NoneVlm:
    name = "none"

    def available(self):
        return True, ""

    def understand(self, image, ocr_text):
        return None


class _BadOcr:
    """返回畸形数据：短 bbox、inf 坐标、非字符串文本。"""

    name = "bad-ocr"

    def available(self):
        return True, ""

    def recognize(self, image):
        return [
            OcrLine("正常", [10, 10, 80, 40], 0.9),
            OcrLine("短框", [10, 10, 80], 0.9),
            OcrLine("无穷", [float("inf"), 0, 10, 10], 0.9),
            OcrLine(123, [20, 20, 60, 50], 0.8),
        ]


def _image(root: Path) -> Path:
    path = root / "p.png"
    Image.new("RGB", (200, 300), "white").save(path)
    return path


# ---------- R01 ----------

def test_malformed_ocr_data_does_not_crash():
    with temp_dir() as root:
        result = pipeline.run_page(
            image_path=_image(root), book_id="book01", page_no=1,
            data_dir=root / "data", ocr_backend=_BadOcr(), vlm_backend=_NullVlm(),
            run_vlm=False,
        )
        assert result.ocr is not None
        assert result.ocr["status"] in ("ok", "empty")
        texts = [b["text"] for b in result.ocr["text_blocks"]]
        assert "正常" in texts and "123" in texts   # 非字符串被安全转型
        assert "短框" not in texts and "无穷" not in texts  # 畸形框被丢弃
        assert result.ocr_error is None


def test_ocr_builder_exception_becomes_stage_error():
    old = contracts.build_ocr_document

    def _boom(**kwargs):
        raise RuntimeError("构造炸了")

    contracts.build_ocr_document = _boom
    try:
        with temp_dir() as root:
            result = pipeline.run_page(
                image_path=_image(root), book_id="book02", page_no=1,
                data_dir=root / "data", ocr_backend=_BadOcr(), vlm_backend=_NullVlm(),
                run_vlm=False,
            )
            assert result.ocr_error is not None
            assert result.ocr_error.code == 9001
            # 仍写出 failed 契约，供中枢降级
            assert result.ocr is not None and result.ocr["status"] == "failed"
            assert (root / "data" / "logs" / "book02_p01_ocr.error.json").is_file()
    finally:
        contracts.build_ocr_document = old


# ---------- R02 ----------

def test_builder_requires_explicit_safety():
    try:
        contracts.build_vlm_document(
            book_id="book01", page_id="book01_p01", page_no=1,
            image_width=100, image_height=100, description="x",
        )
    except TypeError as exc:
        assert "safety_pass" in str(exc)
    else:
        raise AssertionError("省略 safety_pass 必须报错")


def test_vlm_result_requires_explicit_safety():
    try:
        VlmResult(description="x")
    except TypeError as exc:
        assert "safety_pass" in str(exc)
    else:
        raise AssertionError("VlmResult 省略 safety_pass 必须报错")


# ---------- R03 ----------

def test_vlm_returning_none_is_a_stage_error():
    with temp_dir() as root:
        result = pipeline.run_page(
            image_path=_image(root), book_id="book03", page_no=1,
            data_dir=root / "data", ocr_backend=None, vlm_backend=_NoneVlm(),
            run_ocr=False, run_vlm=True,
        )
        assert result.vlm is None
        assert result.vlm_error is not None
        assert result.vlm_error.code == 9002
        assert result.ok is False
        assert not (root / "data" / "json" / "book03_p01_vlm.json").exists()


def test_stale_vlm_file_is_removed_when_stage_fails():
    with temp_dir() as root:
        data = root / "data"
        stale = data / "json" / "book04_p01_vlm.json"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text('{"stale": true}', encoding="utf-8")

        result = pipeline.run_page(
            image_path=_image(root), book_id="book04", page_no=1,
            data_dir=data, ocr_backend=None, vlm_backend=_NoneVlm(),
            run_ocr=False, run_vlm=True,
        )
        assert result.vlm is None
        assert not stale.exists(), "失败后必须清掉过期的 vlm.json"


def test_timeout_maps_to_2002():
    class _TimeoutVlm:
        name = "timeout"

        def available(self):
            return True, ""

        def understand(self, image, ocr_text):
            raise TimeoutError("read timeout")

    with temp_dir() as root:
        result = pipeline.run_page(
            image_path=_image(root), book_id="book05", page_no=1,
            data_dir=root / "data", ocr_backend=None, vlm_backend=_TimeoutVlm(),
            run_ocr=False, run_vlm=True,
        )
        assert result.vlm_error.code == 2002


# ---------- R04 ----------

def test_validator_rejects_vlm_failed_status():
    doc = {
        "schema_version": "1.0", "book_id": "book01", "page_id": "book01_p01",
        "page_no": 1, "status": "failed", "image_width": 100, "image_height": 100,
        "description": "", "objects": [], "scene_tags": [],
        "safety": {"pass": True, "flags": []}, "elapsed_ms": 1,
    }
    errors = validate.validate_vlm(doc)
    assert any("status 非法" in e for e in errors)


def test_validator_requires_objects_when_ok():
    doc = {
        "schema_version": "1.0", "book_id": "book01", "page_id": "book01_p01",
        "page_no": 1, "status": "ok", "image_width": 100, "image_height": 100,
        "description": "x", "objects": [], "scene_tags": [],
        "safety": {"pass": True, "flags": []}, "elapsed_ms": 1,
    }
    assert any("objects 为空" in e for e in validate.validate_vlm(doc))


def test_validator_requires_zero_confidence_for_empty_ocr():
    doc = contracts.build_ocr_document(
        book_id="book01", page_id="book01_p01", page_no=1,
        image_width=100, image_height=100, lines=[], elapsed_ms=1, backend="stub",
    )
    doc["page_confidence"] = 0.5
    assert any("page_confidence" in e for e in validate.validate_ocr(doc))


def test_exported_vlm_schema_excludes_failed():
    schema = json.loads((ROOT / "contracts" / "vlm.schema.json").read_text(encoding="utf-8"))
    assert "failed" not in schema["properties"]["status"]["enum"]
