"""图像加载与预处理。

坐标约定（本轮修过，务必看清）：
- 契约里的 bbox 一律是**原图像素**，且"原图"指 **/capture 落盘的那个文件**；
- 手机照片常带 EXIF 方向（相机竖拍、图库旋转），文件里的像素是"歪的"。
  我们为模型准备一份**摆正后**的工作副本，但坐标必须换算回**文件原本的像素系**；
- 因此 ``PageImage`` 同时记录：
    * ``width/height``：文件原始尺寸（契约坐标系）
    * ``scale``：工作副本 / 摆正图 的比例
    * ``orientation``：EXIF 方向码（1–8）
  ``to_original_bbox`` 先除 scale 回到摆正图，再按 orientation 逆变换回原图。
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageOps

# 契约：/capture 限制长边 ≤ 4096（§1.5）
MAX_SIDE = 4096
# 送模型的长边；绘本页字大，1600 足够，且能显著降延迟
WORK_SIDE = 1600

# EXIF 方向标签
_ORIENTATION_TAG = 0x0112


@dataclass(frozen=True)
class PageImage:
    path: Path
    width: int  # 原图宽（文件像素，bbox 参照系）
    height: int  # 原图高（文件像素，bbox 参照系）
    image: Image.Image  # RGB 工作副本（已摆正、可能已缩小）
    scale: float  # 工作副本 / 摆正图，<=1
    orientation: int = 1  # EXIF 方向码

    def to_original_bbox(self, bbox: Sequence[float]) -> list[float]:
        """工作副本坐标 → 原图像素坐标。"""
        s = self.scale or 1.0
        x1, y1, x2, y2 = (float(v) / s for v in bbox)
        p1 = _unorient(x1, y1, self.orientation, self.width, self.height)
        p2 = _unorient(x2, y2, self.orientation, self.width, self.height)
        return [
            min(p1[0], p2[0]),
            min(p1[1], p2[1]),
            max(p1[0], p2[0]),
            max(p1[1], p2[1]),
        ]


def _unorient(
    x: float, y: float, orientation: int, raw_width: int, raw_height: int
) -> tuple[float, float]:
    """摆正图坐标 → 文件原始坐标（连续坐标，边缘对边缘）。

    与 PIL 的 exif_transpose 保持互逆：
    1 原样 / 2 水平镜像 / 3 旋转180 / 4 垂直镜像
    5 主对角转置 / 6 顺时针90 / 7 副对角转置 / 8 逆时针90
    """
    width, height = raw_width, raw_height
    if orientation == 2:
        return width - x, y
    if orientation == 3:
        return width - x, height - y
    if orientation == 4:
        return x, height - y
    if orientation == 5:
        return y, x
    if orientation == 6:
        return y, height - x
    if orientation == 7:
        return width - y, height - x
    if orientation == 8:
        return width - y, x
    return x, y


class ImageLoadError(ValueError):
    """图片无法读取或格式不支持（对应错误码 1006）。"""


def read_orientation(path: Path) -> int:
    try:
        with Image.open(path) as image:
            value = image.getexif().get(_ORIENTATION_TAG, 1)
    except Exception:  # noqa: BLE001
        return 1
    try:
        orientation = int(value)
    except (TypeError, ValueError):
        return 1
    return orientation if 1 <= orientation <= 8 else 1


def load_page_image(
    image_path: str | Path,
    *,
    work_side: int = WORK_SIDE,
    max_side: int = MAX_SIDE,
    data: bytes | None = None,
) -> PageImage:
    """加载一页图片。

    ``data`` 给定时不再读盘：Worker 先用 ``O_RDONLY`` 读一次字节、
    校验 SHA256，再用同一份字节解码，避免“校验后文件被替换”的 TOCTOU。
    """
    path = Path(image_path)
    if data is None:
        if not path.is_file():
            raise ImageLoadError(f"图片不存在: {path}")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ImageLoadError(f"图片读取失败: {exc}") from exc

    try:
        with Image.open(io.BytesIO(data)) as handle:
            raw_size = handle.size  # 文件原始尺寸：契约坐标系
            value = handle.getexif().get(_ORIENTATION_TAG, 1)
            try:
                orientation = int(value)
            except (TypeError, ValueError):
                orientation = 1
            if not 1 <= orientation <= 8:
                orientation = 1
            upright = ImageOps.exif_transpose(handle).convert("RGB")  # 摆正副本
    except ImageLoadError:
        raise
    except Exception as exc:  # noqa: BLE001 - 统一转成契约错误
        raise ImageLoadError(f"图片读取失败: {exc}") from exc

    width, height = raw_size
    if width <= 0 or height <= 0:
        raise ImageLoadError(f"图片尺寸非法: {width}x{height}")
    if max(width, height) > max_side:
        # /capture 会挡，但独立运行时也要有明确保护（对应错误码 1004）
        raise ImageLoadError(f"图片过大: {width}x{height}，长边上限 {max_side}")

    long_side = max(upright.size)
    if long_side > work_side:
        scale = work_side / long_side
        work = upright.resize(
            (max(1, round(upright.width * scale)), max(1, round(upright.height * scale))),
            Image.LANCZOS,
        )
    else:
        scale = 1.0
        work = upright

    return PageImage(
        path=path,
        width=width,
        height=height,
        image=work,
        scale=scale,
        orientation=orientation,
    )
