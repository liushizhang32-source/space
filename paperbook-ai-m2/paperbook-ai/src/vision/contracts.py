"""ocr.json / vlm.json 的构造器（对齐 docs/API_v1.0.md §1.12 C1/C2）。

这一层只负责「把模型输出装进契约」：
- bbox 一律整数、左上原点、x2/y2 不含端点、必须落在图像内；
- block_id / object_id 按 order 连续编号（01 起）；
- status 自报：ok / empty / failed，由中枢据此判页面状态（§1.7 三级状态）。
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from . import ids

SCHEMA_VERSION = "1.0"
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_FAILED = "failed"
VALID_STATUS = (STATUS_OK, STATUS_EMPTY, STATUS_FAILED)
# 公共 VLMData 只接受这两个值（见 orchestrator/schemas/vlm.py）
VLM_STATUS = (STATUS_OK, STATUS_EMPTY)

MODULE_NAME = "vision"
MODULE_VERSION = "0.1.0"

# block_id / object_id 用两位序号，超过 99 就必须截断，否则整页崩（F06 / M2-06）
MAX_ITEMS = 99


def emit_extra_fields() -> bool:
    """是否在 JSON 里附加 producer / error。

    默认 **关闭**：正常情况下按 API §1.2.5，消费方应忽略未知字段；
    这里默认不写只是为了少一层歧义，不是兼容性前提。
    附加信息会写日志或由调用方自行记录，不进交付文件。
    本地排障时设 ``VISION_EMIT_EXTRA=1`` 打开。
    """
    return os.getenv("VISION_EMIT_EXTRA", "0") == "1"


def clamp_bbox(
    bbox: Sequence[float] | None, width: int, height: int
) -> list[int] | None:
    """把任意框裁进图像内并转成整数；退化框（宽或高为 0）返回 None。

    非有限值（inf / nan）、长度不对、类型不对一律返回 None，不抛异常——
    后端返回畸形数据不能中断整条流水线。
    """
    if bbox is None or width <= 0 or height <= 0:
        return None
    try:
        if len(bbox) != 4:
            return None
        x1, y1, x2, y2 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
        return None
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    x1 = max(0, min(int(round(x1)), width - 1))
    y1 = max(0, min(int(round(y1)), height - 1))
    x2 = max(0, min(int(round(x2)), width))
    y2 = max(0, min(int(round(y2)), height))
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return max(0.0, min(1.0, v))


def _to_raw_bbox(
    raw_bbox: Any,
    to_original: Callable[[Sequence[float]], Sequence[float]] | None,
    scale: float,
) -> list[float] | None:
    """把工作副本坐标转回原图；任何异常都吞掉返回 None。"""
    if raw_bbox is None:
        return None
    try:
        if len(raw_bbox) != 4:
            return None
        if to_original is not None:
            mapped = list(to_original(raw_bbox))
        elif scale and scale != 1.0:
            mapped = [float(v) / scale for v in raw_bbox]
        else:
            mapped = [float(v) for v in raw_bbox]
    except (TypeError, ValueError, ZeroDivisionError, ArithmeticError):
        return None
    return mapped if len(mapped) == 4 else None


def _producer(backend: str) -> dict[str, str]:
    return {"module": MODULE_NAME, "backend": backend, "version": MODULE_VERSION}


def build_text_blocks(
    *,
    page_id: str,
    lines: Iterable[Any],
    width: int,
    height: int,
    scale: float = 1.0,
    to_original: Callable[[Sequence[float]], Sequence[float]] | None = None,
) -> list[dict[str, Any]]:
    """把后端返回的行（OcrLine）转成契约里的 text_blocks，并重新连续编号。

    ``to_original`` 负责工作副本坐标 → 原图像素（含缩放与 EXIF 方向）；
    不传则退化为只按 ``scale`` 还原（老调用方式）。
    """
    blocks: list[dict[str, Any]] = []
    for line in lines:
        if len(blocks) >= MAX_ITEMS:  # 两位序号上限，多余的行丢弃而不是整页失败
            break
        text = getattr(line, "text", "")
        if not isinstance(text, str):
            text = "" if text is None else str(text)  # 后端给了非字符串也不崩
        text = text.strip()
        if not text:
            continue
        box = clamp_bbox(
            _to_raw_bbox(getattr(line, "bbox", None), to_original, scale), width, height
        )
        if box is None:
            continue
        blocks.append(
            {
                "block_id": ids.block_id(page_id, len(blocks) + 1),
                "order": len(blocks) + 1,
                "text": text,
                "bbox": box,
                "confidence": round(_clamp01(getattr(line, "confidence", 0.0)), 4),
            }
        )
    return blocks


def _weighted_page_confidence(blocks: list[dict[str, Any]]) -> float:
    weight = sum(len(b["text"]) for b in blocks)
    if weight == 0:
        return 0.0
    score = sum(len(b["text"]) * b["confidence"] for b in blocks) / weight
    return round(max(0.0, min(1.0, score)), 4)


def build_ocr_document(
    *,
    book_id: str,
    page_id: str,
    page_no: int,
    image_width: int,
    image_height: int,
    lines: Iterable[Any] = (),
    elapsed_ms: int = 0,
    backend: str = "unknown",
    scale: float = 1.0,
    to_original: Callable[[Sequence[float]], Sequence[float]] | None = None,
    status: str | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocks = build_text_blocks(
        page_id=page_id,
        lines=lines,
        width=image_width,
        height=image_height,
        scale=scale,
        to_original=to_original,
    )
    resolved = status or (STATUS_EMPTY if not blocks else STATUS_OK)
    if resolved not in VALID_STATUS:
        raise ValueError(f"非法 status: {resolved}")
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "book_id": book_id,
        "page_id": page_id,
        "page_no": page_no,
        "status": resolved,
        "image_width": int(image_width),
        "image_height": int(image_height),
        "text_blocks": blocks,
        "page_confidence": _weighted_page_confidence(blocks),
        "elapsed_ms": max(0, int(elapsed_ms)),
    }
    # 附加信息默认不写进交付文件（按 §1.2.5 消费方本应忽略未知字段）
    if emit_extra_fields():
        doc["producer"] = _producer(backend)
        if error:
            doc["error"] = error
    return doc


def build_objects(
    *,
    page_id: str,
    objects: Iterable[Any],
    width: int,
    height: int,
    scale: float = 1.0,
    to_original: Callable[[Sequence[float]], Sequence[float]] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for obj in objects:
        if len(result) >= MAX_ITEMS:
            break
        label = getattr(obj, "label", "")
        if not isinstance(label, str):
            label = "" if label is None else str(label)
        label = label.strip()
        if not label:
            continue
        box = clamp_bbox(
            _to_raw_bbox(getattr(obj, "bbox", None), to_original, scale), width, height
        )
        if box is None:
            continue
        result.append(
            {
                "object_id": ids.object_id(page_id, len(result) + 1),
                "label": label,
                "bbox": box,
                "confidence": round(_clamp01(getattr(obj, "confidence", 0.0)), 4),
            }
        )
    return result


def build_vlm_document(
    *,
    book_id: str,
    page_id: str,
    page_no: int,
    image_width: int,
    image_height: int,
    description: str = "",
    objects: Iterable[Any] = (),
    scene_tags: Iterable[str] = (),
    safety_pass: bool,  # 必填：不允许"忘传就默认安全"（第三轮 R02）
    safety_flags: Iterable[str] = (),
    elapsed_ms: int = 0,
    backend: str = "unknown",
    scale: float = 1.0,
    to_original: Callable[[Sequence[float]], Sequence[float]] | None = None,
    status: str | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    items = build_objects(
        page_id=page_id,
        objects=objects,
        width=image_width,
        height=image_height,
        scale=scale,
        to_original=to_original,
    )
    resolved = status or (STATUS_EMPTY if not items else STATUS_OK)
    # 公共 VLMData 的 status 只有 ok / empty：不允许产出 failed，
    # 阶段失败由 pipeline 的错误通道上报，不写这个文件（见 docs/TEST_REPORT.md F01）。
    if resolved not in VLM_STATUS:
        raise ValueError(
            f"VLMData.status 只接受 {VLM_STATUS}，实际 {resolved!r}；"
            "阶段失败请走 StageError 通道，不要伪装成 empty"
        )
    if not isinstance(safety_pass, bool):
        raise TypeError(f"safety_pass 必须是 bool，实际 {type(safety_pass).__name__}")
    if not isinstance(safety_flags, (list, tuple)):
        raise TypeError(f"safety_flags 必须是序列，实际 {type(safety_flags).__name__}")
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "book_id": book_id,
        "page_id": page_id,
        "page_no": page_no,
        "status": resolved,
        "image_width": int(image_width),
        "image_height": int(image_height),
        "description": (description or "").strip(),
        "objects": items,
        "scene_tags": [str(t).strip() for t in scene_tags if str(t).strip()],
        "safety": {"pass": safety_pass, "flags": [str(f) for f in safety_flags]},
        "elapsed_ms": max(0, int(elapsed_ms)),
    }
    if emit_extra_fields():
        doc["producer"] = _producer(backend)
        if error:
            doc["error"] = error
    return doc


def failed_ocr_document(
    *, book_id: str, page_id: str, page_no: int, width: int, height: int,
    elapsed_ms: int, backend: str, code: int, msg: str
) -> dict[str, Any]:
    """直接构造失败契约，**不经过** build_ocr_document。

    构造器本身出问题时，失败兜底仍要能写出合规文件供中枢降级。
    """
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "book_id": book_id,
        "page_id": page_id,
        "page_no": page_no,
        "status": STATUS_FAILED,
        "image_width": int(width),
        "image_height": int(height),
        "text_blocks": [],
        "page_confidence": 0.0,
        "elapsed_ms": max(0, int(elapsed_ms)),
    }
    if emit_extra_fields():
        doc["producer"] = _producer(backend)
        doc["error"] = {"code": code, "msg": str(msg)[:500]}
    return doc


def failed_vlm_document(
    *, book_id: str, page_id: str, page_no: int, width: int, height: int,
    elapsed_ms: int, backend: str, code: int, msg: str
) -> dict[str, Any]:
    """已废弃：公共 VLMData 不接受 status=failed。

    保留函数只为显式报错，避免有人误用后产出非法文件；阶段失败请用
    ``pipeline.StageError`` + 错误日志通道。
    """
    raise ValueError(
        "VLMData 不接受 status=failed；阶段失败请走 StageError 通道，"
        "不要生成 vlm.json（见 docs/TEST_REPORT.md F01）"
    )
