"""物体精分割：把 bbox 细化成贴合轮廓的多边形，供点读精确命中。

三个后端：
- ``sam2``    ：ultralytics 自带 SAM2（需 torch，效果最好）
- ``grabcut`` ：OpenCV 经典算法（无需 torch，纯 CPU，适合插画）
- ``none``    ：直接用 bbox 当多边形（保底）

分割只在**建库时**跑一次，点读时只查索引，不碰模型。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np

BBox = tuple[int, int, int, int]


@dataclass(frozen=True)
class MaskResult:
    polygon: list[tuple[int, int]]
    area: int
    method: str


class Segmenter(Protocol):
    name: str

    def available(self) -> tuple[bool, str]: ...

    def segment(self, image: np.ndarray, bboxes: Sequence[BBox]) -> list[MaskResult]: ...


def polygon_area(polygon: Sequence[Sequence[int]]) -> float:
    """鞋带公式，返回绝对面积。"""
    n = len(polygon)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def point_in_polygon(x: float, y: float, polygon: Sequence[Sequence[int]]) -> bool:
    """射线法。"""
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < xin:
                inside = not inside
    return inside


class NullSegmenter:
    """不分割，直接把 bbox 四角当多边形。"""

    name = "none"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def segment(self, image: np.ndarray, bboxes: Sequence[BBox]) -> list[MaskResult]:
        results: list[MaskResult] = []
        for x1, y1, x2, y2 in bboxes:
            poly = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
            results.append(MaskResult(poly, int((x2 - x1) * (y2 - y1)), "none"))
        return results


class GrabCutSegmenter:
    """OpenCV GrabCut：以 bbox 为初始矩形迭代前景/背景。"""

    name = "grabcut"

    def __init__(self, iterations: int = 3, pad: int = 4) -> None:
        self.iterations = iterations
        self.pad = pad

    def available(self) -> tuple[bool, str]:
        try:
            import cv2  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            return False, f"未安装 opencv: {exc}"
        return True, ""

    def segment(self, image: np.ndarray, bboxes: Sequence[BBox]) -> list[MaskResult]:
        import cv2

        height, width = image.shape[:2]
        results: list[MaskResult] = []
        for bbox in bboxes:
            result = self._one(cv2, image, bbox, width, height)
            results.append(result or _bbox_result(bbox, "grabcut-fallback"))
        return results

    def _one(self, cv2, image, bbox: BBox, width: int, height: int) -> MaskResult | None:
        x1, y1, x2, y2 = bbox
        x1 = max(0, x1 - self.pad)
        y1 = max(0, y1 - self.pad)
        x2 = min(width, x2 + self.pad)
        y2 = min(height, y2 + self.pad)
        if x2 - x1 < 8 or y2 - y1 < 8:
            return None

        mask = np.zeros((height, width), np.uint8)
        background = np.zeros((1, 65), np.float64)
        foreground = np.zeros((1, 65), np.float64)
        try:
            cv2.grabCut(
                image, mask, (x1, y1, x2 - x1, y2 - y1),
                background, foreground, self.iterations, cv2.GC_INIT_WITH_RECT,
            )
        except Exception:  # noqa: BLE001
            return None

        binary = np.where(
            (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0
        ).astype(np.uint8)
        kernel = np.ones((5, 5), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        contour = max(contours, key=cv2.contourArea)
        area = float(cv2.contourArea(contour))
        # 分割结果太小说明 GrabCut 跑飞了，退回 bbox 更安全
        if area < 0.15 * (x2 - x1) * (y2 - y1):
            return None

        epsilon = 0.01 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
        polygon = [(int(p[0]), int(p[1])) for p in approx]
        if len(polygon) < 3:
            return None
        return MaskResult(polygon, int(area), "grabcut")


class Sam2Segmenter:
    """ultralytics 的 SAM2：按 bbox 提示分割。"""

    name = "sam2"

    def __init__(self, weights: str = "sam2_t.pt") -> None:
        self.weights = weights
        self._model = None

    def available(self) -> tuple[bool, str]:
        try:
            import ultralytics  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            return False, f"未安装 ultralytics: {exc}"
        return True, ""

    def segment(self, image: np.ndarray, bboxes: Sequence[BBox]) -> list[MaskResult]:
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(reason)
        from ultralytics import SAM

        if self._model is None:
            self._model = SAM(self.weights)
        results = self._model(image, bboxes=[list(b) for b in bboxes], verbose=False)
        masks = getattr(results[0], "masks", None) if results else None
        if masks is None or not getattr(masks, "xy", None):
            raise RuntimeError("SAM2 没有返回掩码")

        outputs: list[MaskResult] = []
        for index, bbox in enumerate(bboxes):
            try:
                polygon = [(int(p[0]), int(p[1])) for p in masks.xy[index]]
            except Exception:  # noqa: BLE001
                polygon = []
            if len(polygon) < 3:
                outputs.append(_bbox_result(bbox, "sam2-fallback"))
            else:
                outputs.append(MaskResult(polygon, int(polygon_area(polygon)), "sam2"))
        return outputs


def _bbox_result(bbox: BBox, method: str) -> MaskResult:
    x1, y1, x2, y2 = bbox
    poly = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    return MaskResult(poly, max(0, x2 - x1) * max(0, y2 - y1), method)


def build_segmenter(name: str | None = None) -> Segmenter:
    """auto：优先 SAM2，装不上就用 GrabCut。"""
    resolved = (name or "auto").lower()
    if resolved in ("none", "null", "off"):
        return NullSegmenter()
    if resolved == "grabcut":
        return GrabCutSegmenter()
    if resolved == "sam2":
        return Sam2Segmenter()
    if resolved == "auto":
        # 默认 GrabCut：CPU 上约 0.2 s/页。
        # SAM2 在纯 CPU 上要几十秒到几分钟，只在 GPU 环境（企业赛云机）才划算，
        # 需要时显式传 --segmenter sam2。
        grab = GrabCutSegmenter()
        if grab.available()[0]:
            return grab
        return NullSegmenter()
    raise ValueError(f"未知分割后端 {name!r}，可选 auto/sam2/grabcut/none")
