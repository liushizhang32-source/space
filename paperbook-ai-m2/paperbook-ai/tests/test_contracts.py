from vision import contracts, validate
from vision.backends.base import OcrLine, VlmObject


def test_clamp_bbox_normalizes_and_rejects_degenerate():
    assert contracts.clamp_bbox([10, 20, 30, 40], 100, 200) == [10, 20, 30, 40]
    assert contracts.clamp_bbox([30, 40, 10, 20], 100, 200) == [10, 20, 30, 40]
    assert contracts.clamp_bbox([-5, -5, 120, 260], 100, 200) == [0, 0, 100, 200]
    assert contracts.clamp_bbox([10, 10, 10, 40], 100, 200) is None
    assert contracts.clamp_bbox(None, 100, 200) is None
    assert contracts.clamp_bbox([1, 2, 3], 100, 200) is None


def test_ocr_document_orders_blocks_and_weights_confidence():
    doc = contracts.build_ocr_document(
        book_id="book01",
        page_id="book01_p03",
        page_no=3,
        image_width=1000,
        image_height=1500,
        lines=[
            OcrLine("小兔子", [10, 20, 200, 80], 1.0),
            OcrLine("胡萝卜", [10, 100, 300, 160], 0.5),
        ],
        elapsed_ms=12,
        backend="stub",
    )
    assert doc["status"] == "ok"
    assert [b["order"] for b in doc["text_blocks"]] == [1, 2]
    assert doc["text_blocks"][0]["block_id"] == "book01_p03_t01"
    assert 0.6 < doc["page_confidence"] < 0.8  # 加权平均，短文本权重小
    assert validate.validate_ocr(doc) == []


def test_ocr_document_empty_page_is_not_failure():
    doc = contracts.build_ocr_document(
        book_id="book01",
        page_id="book01_p03",
        page_no=3,
        image_width=1000,
        image_height=1500,
        lines=[],
        elapsed_ms=5,
        backend="stub",
    )
    assert doc["status"] == "empty"
    assert doc["page_confidence"] == 0.0
    assert validate.validate_ocr(doc) == []


def test_scale_restores_original_coordinates():
    # 模型在 800x1200 工作副本上给出框，原图是 1600x2400
    doc = contracts.build_ocr_document(
        book_id="book01",
        page_id="book01_p01",
        page_no=1,
        image_width=1600,
        image_height=2400,
        lines=[OcrLine("你好", [100, 100, 300, 200], 0.9)],
        elapsed_ms=1,
        backend="stub",
        scale=0.5,
    )
    assert doc["text_blocks"][0]["bbox"] == [200, 200, 600, 400]
    assert validate.validate_ocr(doc) == []


def test_failed_document_keeps_contract():
    doc = contracts.failed_ocr_document(
        book_id="book01", page_id="book01_p02", page_no=2,
        width=800, height=1200, elapsed_ms=30, backend="paddleocr",
        code=2001, msg="模型超时",
    )
    assert doc["status"] == "failed"
    # 默认不写附加字段（公共 Schema 不接受未声明字段）
    assert "error" not in doc
    assert "producer" not in doc
    assert validate.validate_ocr(doc) == []


def test_extra_fields_are_opt_in():
    import os

    os.environ["VISION_EMIT_EXTRA"] = "1"
    try:
        doc = contracts.failed_ocr_document(
            book_id="book01", page_id="book01_p02", page_no=2,
            width=800, height=1200, elapsed_ms=30, backend="paddleocr",
            code=2001, msg="模型超时",
        )
        assert doc["error"]["code"] == 2001
        assert doc["producer"]["backend"] == "paddleocr"
    finally:
        os.environ.pop("VISION_EMIT_EXTRA", None)


def test_vlm_document_and_validation():
    doc = contracts.build_vlm_document(
        book_id="book01",
        page_id="book01_p03",
        page_no=3,
        image_width=1000,
        image_height=1500,
        description="夜晚的森林，一只小兔子站在树下",
        objects=[
            VlmObject("兔子", [30, 40, 120, 150], 0.92),
            VlmObject("树", [200, 10, 400, 300], 0.96),
        ],
        scene_tags=["夜晚", "森林"],
        safety_pass=True,
        elapsed_ms=2100,
        backend="qwen2.5-vl-http",
    )
    assert [o["object_id"] for o in doc["objects"]] == ["book01_p03_o01", "book01_p03_o02"]
    assert doc["safety"] == {"pass": True, "flags": []}
    assert validate.validate_vlm(doc) == []


def test_unknown_fields_are_allowed():
    doc = contracts.build_vlm_document(
        book_id="book01", page_id="book01_p03", page_no=3,
        image_width=100, image_height=100, description="x", elapsed_ms=1, backend="stub",
        safety_pass=True,
    )
    doc["future_field"] = {"anything": 1}
    assert validate.validate_vlm(doc) == []


def test_validator_catches_bad_bbox_and_order():
    doc = contracts.build_ocr_document(
        book_id="book01", page_id="book01_p03", page_no=3,
        image_width=100, image_height=100,
        lines=[OcrLine("a", [10, 10, 50, 50], 0.9), OcrLine("b", [10, 60, 50, 90], 0.9)],
        elapsed_ms=1, backend="stub",
    )
    doc["text_blocks"][0]["bbox"] = [10, 10, 10, 50]
    doc["text_blocks"][1]["order"] = 5
    errors = validate.validate_ocr(doc)
    assert any("bbox" in e for e in errors)
    assert any("order" in e for e in errors)
