"""互动阶段的帧识别、触控命中与帧↔页面对象关联。

用途：视频帧上做物体识别 → 点读命中 → 关联到绘本页对象。
安全与边界：
- 复用 ``safety.evaluate_vlm_safety``，安全不过直接 ``SafetyBlocked``（3004）；
- 置信度缺失记 0.0 并计数，不伪造默认值；
- 关联结果是**候选**，``identity_status`` 恒为 ``unknown``。
"""

from __future__ import annotations

from typing import Any, Mapping

from .characters import category_of
from .safety import SafetyBlocked, evaluate_vlm_safety

SCHEMA_VERSION = "vision_frame/0.1"
MAX_FRAME_OBJECTS = 12
#: 关联分数下限，低于它不产出关联
_MIN_LINK_SCORE = 0.5


def _field(obj: Any, name: str, default: Any = None) -> Any:
    """同时接受 dict 与 VlmObject 数据类。"""
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _frame_objects(raw_objects: list[Any], frame_id: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for index, obj in enumerate(raw_objects[:MAX_FRAME_OBJECTS], start=1):
        bbox = [float(v) for v in (_field(obj, "bbox") or [])]
        if len(bbox) != 4:
            continue
        confidence = _field(obj, "confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            confidence = 0.0
        label = str(_field(obj, "label", "") or "").strip()
        if not label:
            continue
        objects.append(
            {
                "object_id": f"{frame_id}_o{index:02d}",
                "label": label,
                "category": category_of(label),
                "bbox": bbox,
                "confidence": max(0.0, min(1.0, float(confidence))),
            }
        )
    return objects


def recognize_frame(
    image,
    backend,
    *,
    frame_id: str,
    page_id: str | None = None,
    ocr_text: str = "",
) -> dict[str, Any]:
    """对单帧做物体识别，返回帧文档（不写盘，由调用方决定存哪里）。"""
    if not frame_id:
        raise ValueError("frame_id 不能为空")
    result = backend.understand(image, ocr_text)
    verdict = evaluate_vlm_safety(result)
    if not verdict.passed:
        raise SafetyBlocked(verdict, page_id=page_id or frame_id, stage="frame")

    objects = _frame_objects(list(result.objects or []), frame_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "frame_id": frame_id,
        "page_id": page_id,
        "image_width": int(getattr(image, "width", 0)),
        "image_height": int(getattr(image, "height", 0)),
        "objects": objects,
        "confidence_missing": int(getattr(result, "confidence_missing", 0)),
        "safety": {
            "pass": True,
            "flags": list(result.safety_flags or ()),
            "evidence": getattr(result, "safety_evidence", ""),
        },
    }


def _contains(bbox: list[float], x: float, y: float) -> bool:
    x1, y1, x2, y2 = bbox
    return x1 <= x < x2 and y1 <= y < y2


def _area(bbox: list[float]) -> float:
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def hit_test(frame_doc: Mapping[str, Any], x: float, y: float) -> dict[str, Any] | None:
    """返回包含该点的最小物体；没有命中返回 None。"""
    hits = [obj for obj in frame_doc.get("objects") or [] if _contains(list(obj["bbox"]), x, y)]
    if not hits:
        return None
    return min(hits, key=lambda o: _area(list(o["bbox"])))


def link_frame_to_page(
    frame_doc: Mapping[str, Any],
    page_doc: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """把帧上的物体关联到页面对象（类别 + 标签 + 画布内相对位置）。"""
    page_objects = list(page_doc.get("objects") or [])
    if not page_objects:
        return []

    fw = float(frame_doc.get("image_width") or 0) or 1.0
    fh = float(frame_doc.get("image_height") or 0) or 1.0
    pw = float(page_doc.get("image_width") or 0) or 1.0
    ph = float(page_doc.get("image_height") or 0) or 1.0

    def center(bbox: list[float], w: float, h: float) -> tuple[float, float]:
        x1, y1, x2, y2 = bbox
        return ((x1 + x2) / 2 / w, (y1 + y2) / 2 / h)

    links: list[dict[str, Any]] = []
    for obj in frame_doc.get("objects") or []:
        label = str(obj.get("label") or "")
        category = str(obj.get("category") or category_of(label))
        fcx, fcy = center(list(obj["bbox"]), fw, fh)
        best: tuple[float, dict[str, Any]] | None = None
        for page_obj in page_objects:
            if category_of(str(page_obj.get("label") or "")) != category:
                continue
            same_label = str(page_obj.get("label") or "") == label
            pcx, pcy = center(list(page_obj["bbox"]), pw, ph)
            distance = min(1.0, ((fcx - pcx) ** 2 + (fcy - pcy) ** 2) ** 0.5)
            score = 0.6 * (1.0 if same_label else 0.3) + 0.4 * (1.0 - distance)
            if best is None or score > best[0]:
                best = (score, dict(page_obj))
        if best is None or best[0] < _MIN_LINK_SCORE:
            continue
        score, page_obj = best
        links.append(
            {
                "frame_object_id": obj["object_id"],
                "frame_id": frame_doc.get("frame_id"),
                "page_id": page_doc.get("page_id"),
                "page_object_id": page_obj.get("object_id"),
                "method": "category_label_position",
                "score": round(score, 4),
                "identity_status": "unknown",
            }
        )
    return links
