"""给物体索引补精分割轮廓（离线跑一次）。

    python scripts/build_masks.py --page-id book01_p01 --image samples/demo_page.png
    python scripts/build_masks.py --page-id book01_p01 --image ... --segmenter grabcut
    python scripts/build_masks.py --page-id book01_p01 --image ... --preview data/masks_p01.png

分割后端 auto：装了 ultralytics 就用 SAM2，否则用 GrabCut。
结果写回 data/index/{page_id}.json（polygon + mask_method），点读时零开销。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision import index as index_mod  # noqa: E402
from vision import mask as mask_mod  # noqa: E402
from vision.config import load_env  # noqa: E402


def imread_unicode(path: Path):
    import cv2

    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def draw_preview(image_path: Path, page_index, out_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    colors = [(255, 99, 71), (30, 144, 255), (50, 205, 50), (255, 165, 0), (148, 0, 211)]
    font = None
    for candidate in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if Path(candidate).exists():
            font = ImageFont.truetype(candidate, 34)
            break

    for i, obj in enumerate(page_index.objects):
        color = colors[i % len(colors)]
        if len(obj.polygon) >= 3:
            draw.polygon([tuple(p) for p in obj.polygon], outline=color + (255,), width=5)
        x1, y1, x2, y2 = obj.bbox
        draw.rectangle([x1, y1, x2, y2], outline=color + (90,), width=2)
        label = f"{obj.label}({obj.mask_method or 'bbox'})"
        draw.text((x1 + 4, max(0, y1 - 40)), label, font=font, fill=color + (255,))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    print(f"预览图：{out_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成物体精分割轮廓")
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--segmenter", default="auto", help="auto | sam2 | grabcut | none")
    parser.add_argument("--preview", default=None, help="把轮廓画到图上另存一份")
    args = parser.parse_args(argv)

    load_env()
    data_dir = Path(args.data_dir)
    try:
        page_index = index_mod.load(data_dir, args.page_id)
    except FileNotFoundError:
        print(f"没有索引：{index_mod.index_path(data_dir, args.page_id)}")
        return 1
    if not page_index.objects:
        print(f"{args.page_id} 没有物体，跳过")
        return 1

    image_path = Path(args.image)
    if not image_path.is_absolute():
        image_path = (ROOT / image_path).resolve()
    if not image_path.is_file():
        print(f"找不到图片：{image_path}")
        return 1

    segmenter = mask_mod.build_segmenter(args.segmenter)
    available, reason = segmenter.available()
    print(f"分割后端：{segmenter.name}（{'可用' if available else reason}）")
    if not available:
        return 2

    image = imread_unicode(image_path)
    if image is None:
        print(f"图片读取失败：{image_path}")
        return 1

    bboxes = [obj.bbox for obj in page_index.objects]
    results = segmenter.segment(image, bboxes)
    updated = index_mod.with_masks(page_index, results)
    target = index_mod.save(updated, data_dir)

    print()
    for obj in updated.objects:
        box_area = max(1, (obj.bbox[2] - obj.bbox[0]) * (obj.bbox[3] - obj.bbox[1]))
        poly_area = mask_mod.polygon_area(obj.polygon) if len(obj.polygon) >= 3 else box_area
        print(f"  {obj.label:<6} {obj.mask_method:<16} "
              f"points={len(obj.polygon):<3} 面积占比={poly_area / box_area:.0%}")
    print(f"\n写入 {target.relative_to(ROOT)}")

    if args.preview:
        preview_path = Path(args.preview)
        if not preview_path.is_absolute():
            preview_path = ROOT / preview_path
        draw_preview(image_path, updated, preview_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
