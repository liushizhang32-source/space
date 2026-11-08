"""契约校验（不依赖第三方库，CI 与本地都能跑）。

与 contracts/*.schema.json 同源：schema 给外部工具用，这里给代码与单测用。
校验失败返回中文错误列表，空列表 = 通过。
"""

from __future__ import annotations

import re
from typing import Any

from .ids import BOOK_ID_PATTERN, PAGE_ID_PATTERN

_BOOK_RE = re.compile(BOOK_ID_PATTERN)
_PAGE_RE = re.compile(PAGE_ID_PATTERN)
_BLOCK_RE = re.compile(r"^.+_t\d{2}$")
_OBJECT_RE = re.compile(r"^.+_o\d{2}$")

OCR_STATUS_VALUES = {"ok", "empty", "failed"}
# 公共 VLMData 只有 ok / empty（见 orchestrator/schemas/vlm.py）
VLM_STATUS_VALUES = {"ok", "empty"}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_common(
    doc: dict[str, Any], errors: list[str], status_values: set[str]
) -> None:
    for key in ("schema_version", "book_id", "page_id", "page_no", "status",
                "image_width", "image_height", "elapsed_ms"):
        if key not in doc:
            errors.append(f"缺少字段 {key}")
    if doc.get("schema_version") != "1.0":
        errors.append(f"schema_version 必须为 '1.0'，实际 {doc.get('schema_version')!r}")

    book_id = doc.get("book_id")
    page_id = doc.get("page_id")
    if not isinstance(book_id, str) or not _BOOK_RE.match(book_id or ""):
        errors.append(f"book_id 非法: {book_id!r}")
    if not isinstance(page_id, str) or not _PAGE_RE.match(page_id or ""):
        errors.append(f"page_id 非法: {page_id!r}")
    if isinstance(book_id, str) and isinstance(page_id, str) and not page_id.startswith(f"{book_id}_p"):
        errors.append(f"page_id 与 book_id 不匹配: {page_id!r} / {book_id!r}")

    page_no = doc.get("page_no")
    if not _is_int(page_no) or not 1 <= page_no <= 99:
        errors.append(f"page_no 必须是 1..99 的整数: {page_no!r}")
    elif isinstance(page_id, str) and _PAGE_RE.match(page_id):
        if int(page_id[-2:]) != page_no:
            errors.append(f"page_no={page_no} 与 page_id={page_id} 不一致")

    if doc.get("status") not in status_values:
        errors.append(
            f"status 非法: {doc.get('status')!r}（允许 {sorted(status_values)}）"
        )

    for key in ("image_width", "image_height"):
        value = doc.get(key)
        if not _is_int(value) or value <= 0:
            errors.append(f"{key} 必须是正整数: {value!r}")

    if not _is_int(doc.get("elapsed_ms")) or doc.get("elapsed_ms", -1) < 0:
        errors.append(f"elapsed_ms 必须是非负整数: {doc.get('elapsed_ms')!r}")


def _check_bbox(
    bbox: Any, width: int, height: int, where: str, errors: list[str]
) -> None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        errors.append(f"{where}.bbox 必须是长度 4 的数组: {bbox!r}")
        return
    if not all(_is_int(v) for v in bbox):
        errors.append(f"{where}.bbox 必须是整数（禁止浮点）: {bbox!r}")
        return
    x1, y1, x2, y2 = bbox
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        errors.append(f"{where}.bbox 越界或退化: {bbox!r}（图 {width}x{height}）")


def _check_confidence(value: Any, where: str, errors: list[str]) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append(f"{where} 必须是数字: {value!r}")
        return
    if not 0.0 <= float(value) <= 1.0:
        errors.append(f"{where} 必须在 0..1: {value!r}")


def validate_ocr(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["文档必须是 object"]
    _check_common(doc, errors, OCR_STATUS_VALUES)
    width = doc.get("image_width") or 0
    height = doc.get("image_height") or 0

    blocks = doc.get("text_blocks")
    if not isinstance(blocks, list):
        errors.append("text_blocks 必须是数组")
        blocks = []

    expected_id = doc.get("page_id", "")
    for index, block in enumerate(blocks, start=1):
        where = f"text_blocks[{index - 1}]"
        if not isinstance(block, dict):
            errors.append(f"{where} 必须是 object")
            continue
        for key in ("block_id", "order", "text", "bbox", "confidence"):
            if key not in block:
                errors.append(f"{where} 缺少字段 {key}")
        block_id = block.get("block_id")
        if not isinstance(block_id, str) or not _BLOCK_RE.match(block_id or ""):
            errors.append(f"{where}.block_id 非法: {block_id!r}")
        elif expected_id and not block_id.startswith(f"{expected_id}_t"):
            errors.append(f"{where}.block_id 未使用当前 page_id: {block_id!r}")
        if block.get("order") != index:
            errors.append(f"{where}.order 必须连续从 1 开始，实际 {block.get('order')!r}")
        text = block.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{where}.text 必须是非空字符串")
        if isinstance(width, int) and isinstance(height, int):
            _check_bbox(block.get("bbox"), width, height, where, errors)
        _check_confidence(block.get("confidence"), f"{where}.confidence", errors)

    _check_confidence(doc.get("page_confidence"), "page_confidence", errors)

    status = doc.get("status")
    if status == "empty":
        if blocks:
            errors.append("status=empty 但 text_blocks 非空")
        if doc.get("page_confidence") not in (0, 0.0):
            errors.append("status=empty 时 page_confidence 必须为 0")
    if status == "failed" and blocks:
        errors.append("status=failed 但 text_blocks 非空")
    if status == "ok" and not blocks:
        errors.append("status=ok 但 text_blocks 为空（无字页应为 empty）")
    return errors


def validate_vlm(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["文档必须是 object"]
    _check_common(doc, errors, VLM_STATUS_VALUES)
    width = doc.get("image_width") or 0
    height = doc.get("image_height") or 0

    if not isinstance(doc.get("description"), str):
        errors.append("description 必须是字符串")

    objects = doc.get("objects")
    if not isinstance(objects, list):
        errors.append("objects 必须是数组")
        objects = []

    expected_id = doc.get("page_id", "")
    for index, obj in enumerate(objects, start=1):
        where = f"objects[{index - 1}]"
        if not isinstance(obj, dict):
            errors.append(f"{where} 必须是 object")
            continue
        for key in ("object_id", "label", "bbox", "confidence"):
            if key not in obj:
                errors.append(f"{where} 缺少字段 {key}")
        object_id = obj.get("object_id")
        if not isinstance(object_id, str) or not _OBJECT_RE.match(object_id or ""):
            errors.append(f"{where}.object_id 非法: {object_id!r}")
        elif expected_id and not object_id.startswith(f"{expected_id}_o"):
            errors.append(f"{where}.object_id 未使用当前 page_id: {object_id!r}")
        label = obj.get("label")
        if not isinstance(label, str) or not label.strip():
            errors.append(f"{where}.label 必须是非空字符串")
        if isinstance(width, int) and isinstance(height, int):
            _check_bbox(obj.get("bbox"), width, height, where, errors)
        _check_confidence(obj.get("confidence"), f"{where}.confidence", errors)

    tags = doc.get("scene_tags")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        errors.append("scene_tags 必须是字符串数组")

    safety = doc.get("safety")
    if not isinstance(safety, dict):
        errors.append("safety 必须是 object")
    else:
        if not isinstance(safety.get("pass"), bool):
            errors.append("safety.pass 必须是布尔")
        flags = safety.get("flags")
        if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
            errors.append("safety.flags 必须是字符串数组")

    status = doc.get("status")
    if status == "empty" and objects:
        errors.append("status=empty 但 objects 非空")
    if status == "ok" and not objects:
        errors.append("status=ok 但 objects 为空（无物体应为 empty）")
    return errors


def validate(doc: dict[str, Any], kind: str) -> list[str]:
    if kind == "ocr":
        return validate_ocr(doc)
    if kind == "vlm":
        return validate_vlm(doc)
    raise ValueError(f"kind 必须是 ocr/vlm: {kind!r}")


def assert_valid(doc: dict[str, Any], kind: str) -> None:
    errors = validate(doc, kind)
    if errors:
        raise AssertionError(f"{kind}.json 契约校验失败：\n- " + "\n- ".join(errors))
