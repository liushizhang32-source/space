"""页面级物体索引：把 vlm.json 的 objects 变成可秒级命中的点读索引。

分工：
- 建库（离线）：每页调一次 VLM，把 objects 固化到 data/index/{page_id}.json；
- 点读（在线）：只读这个索引做几何命中，**不再调模型**，延迟 <1ms。

命中策略（两级）：
1. 点落在某个 bbox 内（含容差）→ 取**面积最小**的那个（更具体，避免"森林"盖住"兔子"）；
2. 没命中 → 取最近的 bbox 中心，若在阈值内也认（照顾小朋友点偏）。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .mask import MaskResult, point_in_polygon

INDEX_VERSION = "1.0"
DEFAULT_TOLERANCE_PX = 12
DEFAULT_NEAREST_RATIO = 0.06  # 相对图像对角线，约 5-8% 手指容错


@dataclass(frozen=True)
class IndexObject:
    object_id: str
    label: str
    bbox: tuple[int, int, int, int]
    confidence: float = 0.0
    explanation: str = ""  # 离线生成的儿童化讲解，点读时直接返回
    polygon: tuple[tuple[int, int], ...] = ()  # 精分割轮廓（原图坐标）
    mask_method: str = ""  # sam2 / grabcut / none

    @property
    def area(self) -> int:
        x1, y1, x2, y2 = self.bbox
        return max(0, x2 - x1) * max(0, y2 - y1)

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return (x1 + x2) / 2, (y1 + y2) / 2

    def expanded(self, pad: int) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = self.bbox
        return x1 - pad, y1 - pad, x2 + pad, y2 + pad


@dataclass
class PageIndex:
    page_id: str
    book_id: str
    page_no: int
    image_width: int
    image_height: int
    description: str
    scene_tags: list[str]
    objects: list[IndexObject]
    vlm_backend: str = "unknown"
    built_at: str = ""

    @property
    def diagonal(self) -> float:
        return math.hypot(self.image_width, self.image_height)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": INDEX_VERSION,
            "page_id": self.page_id,
            "book_id": self.book_id,
            "page_no": self.page_no,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "description": self.description,
            "scene_tags": list(self.scene_tags),
            "objects": [
                {
                    "object_id": o.object_id,
                    "label": o.label,
                    "bbox": list(o.bbox),
                    "confidence": o.confidence,
                    "explanation": o.explanation,
                    "polygon": [list(point) for point in o.polygon],
                    "mask_method": o.mask_method,
                }
                for o in self.objects
            ],
            "source": {"vlm_backend": self.vlm_backend, "built_at": self.built_at},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PageIndex:
        source = data.get("source") or {}
        return cls(
            page_id=data["page_id"],
            book_id=data["book_id"],
            page_no=int(data["page_no"]),
            image_width=int(data["image_width"]),
            image_height=int(data["image_height"]),
            description=data.get("description", ""),
            scene_tags=list(data.get("scene_tags") or []),
            objects=[
                IndexObject(
                    object_id=item["object_id"],
                    label=item["label"],
                    bbox=tuple(int(v) for v in item["bbox"]),  # type: ignore[arg-type]
                    confidence=float(item.get("confidence", 0.0)),
                    explanation=str(item.get("explanation", "")),
                    polygon=tuple(
                        (int(point[0]), int(point[1]))
                        for point in (item.get("polygon") or [])
                    ),
                    mask_method=str(item.get("mask_method", "")),
                )
                for item in data.get("objects") or []
            ],
            vlm_backend=str(source.get("vlm_backend", "unknown")),
            built_at=str(source.get("built_at", "")),
        )


def build_from_vlm(vlm_doc: dict[str, Any]) -> PageIndex:
    """vlm.json → PageIndex。status=failed 的页不建库。"""
    if vlm_doc.get("status") == "failed":
        raise ValueError(f"{vlm_doc.get('page_id')} 的 vlm.json 是 failed，跳过")
    producer = vlm_doc.get("producer") or {}
    return PageIndex(
        page_id=vlm_doc["page_id"],
        book_id=vlm_doc["book_id"],
        page_no=int(vlm_doc["page_no"]),
        image_width=int(vlm_doc["image_width"]),
        image_height=int(vlm_doc["image_height"]),
        description=vlm_doc.get("description", ""),
        scene_tags=list(vlm_doc.get("scene_tags") or []),
        objects=[
            IndexObject(
                object_id=item["object_id"],
                label=item["label"],
                bbox=tuple(int(v) for v in item["bbox"]),  # type: ignore[arg-type]
                confidence=float(item.get("confidence", 0.0)),
            )
            for item in vlm_doc.get("objects") or []
        ],
        vlm_backend=str(producer.get("backend", "unknown")),
        built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def hit_test(
    index: PageIndex,
    x: float,
    y: float,
    *,
    tolerance: int = DEFAULT_TOLERANCE_PX,
    nearest_ratio: float = DEFAULT_NEAREST_RATIO,
) -> tuple[IndexObject | None, str]:
    """返回 (命中的物体, 命中方式 in {"inside","nearest","miss"})。"""
    inside = [
        obj for obj in index.objects if _hit_object(obj, x, y, tolerance)
    ]
    if inside:
        # 面积最小的最具体
        return min(inside, key=lambda o: o.area), "inside"

    limit = index.diagonal * nearest_ratio
    best: IndexObject | None = None
    best_distance = float("inf")
    for obj in index.objects:
        cx, cy = obj.center
        distance = math.hypot(cx - x, cy - y)
        if distance < best_distance:
            best, best_distance = obj, distance
    if best is not None and best_distance <= limit:
        return best, "nearest"
    return None, "miss"


def _contains(bbox: tuple[int, int, int, int], x: float, y: float) -> bool:
    x1, y1, x2, y2 = bbox
    return x1 <= x <= x2 and y1 <= y <= y2


def _hit_object(obj: IndexObject, x: float, y: float, tolerance: int) -> bool:
    """有精分割就用轮廓判定，否则退回 bbox（含容差）。"""
    if len(obj.polygon) >= 3:
        for dx, dy in ((0, 0), (tolerance, 0), (-tolerance, 0), (0, tolerance), (0, -tolerance)):
            if point_in_polygon(x + dx, y + dy, obj.polygon):
                return True
        return False
    return _contains(obj.expanded(tolerance), x, y)


def merge_annotations(new: PageIndex, old: PageIndex) -> PageIndex:
    """重建索引时，按 label 把旧的讲解/轮廓/分割方式接回来，避免重复跑模型。"""
    from dataclasses import replace

    previous = {obj.label: obj for obj in old.objects}
    objects: list[IndexObject] = []
    for obj in new.objects:
        old_obj = previous.get(obj.label)
        if old_obj is None:
            objects.append(obj)
            continue
        objects.append(
            replace(
                obj,
                explanation=old_obj.explanation or obj.explanation,
                polygon=old_obj.polygon or obj.polygon,
                mask_method=old_obj.mask_method or obj.mask_method,
            )
        )
    return replace(new, objects=objects)


def with_masks(index: PageIndex, results: list[MaskResult]) -> PageIndex:
    """把分割结果并进索引；结果比物体少时，剩下的保持原样。"""
    from dataclasses import replace

    objects: list[IndexObject] = []
    for obj, result in zip(index.objects, results):
        objects.append(
            replace(obj, polygon=tuple(result.polygon), mask_method=result.method)
        )
    objects.extend(index.objects[len(objects):])
    return replace(index, objects=objects)


def explain(index: PageIndex, obj: IndexObject) -> str:
    """优先用离线生成的讲解；没有就退回模板。"""
    if obj.explanation:
        return obj.explanation
    parts = [f"这是{obj.label}。"]
    if index.description:
        parts.append(index.description)
    return "".join(parts)


def with_explanations(
    index: PageIndex, mapping: dict[str, str]
) -> tuple[PageIndex, int]:
    """按 label 合并讲解，返回新索引与命中数量。"""
    from dataclasses import replace

    hit = 0
    objects: list[IndexObject] = []
    for obj in index.objects:
        text = (mapping.get(obj.label) or "").strip()
        if text:
            hit += 1
            objects.append(replace(obj, explanation=text))
        else:
            objects.append(obj)
    return replace(index, objects=objects), hit


def index_dir(data_dir: str | Path) -> Path:
    path = Path(data_dir) / "index"
    path.mkdir(parents=True, exist_ok=True)
    return path


def index_path(data_dir: str | Path, page_id: str) -> Path:
    return index_dir(data_dir) / f"{page_id}.json"


def save(index: PageIndex, data_dir: str | Path) -> Path:
    target = index_path(data_dir, index.page_id)
    tmp = target.with_name(target.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(index.to_dict(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(target)
    return target


def load(data_dir: str | Path, page_id: str) -> PageIndex:
    with index_path(data_dir, page_id).open("r", encoding="utf-8") as handle:
        return PageIndex.from_dict(json.load(handle))
