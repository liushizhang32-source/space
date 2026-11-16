"""生成一页"难例"绘本：水彩纸纹 + 9 个物体 + 遮挡 + 气泡文字。

用来回答一个具体问题：**VLM 的物体召回在复杂画面上会不会崩**。
真书通常是水彩、物体多、互相遮挡，远比 samples/demo_page.png 难。

产物：
    samples/hard/p01.png       难例页面
    samples/hard/p01.txt       文字真值（给 OCR 评测用，可选）
    samples/hard/p01.gt.json   物体真值（给点读评测用）
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples" / "hard"
SIZE = (1000, 1414)
FONTS = (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf")


def font(size: int):
    for path in FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def paper_base() -> Image.Image:
    """米色纸 + 细噪点。"""
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 4.5, (SIZE[1], SIZE[0], 1)).repeat(3, axis=2)
    base = np.full((SIZE[1], SIZE[0], 3), (250, 246, 238), dtype=np.float64) + noise
    image = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    # 纸张大块明暗，像被翻过
    shade = Image.new("L", SIZE, 0)
    ImageDraw.Draw(shade).ellipse([-200, -300, 900, 900], fill=18)
    return Image.composite(Image.new("RGB", SIZE, "white"), image, shade.point(lambda v: 255 - v))


def wash(image: Image.Image, drawer, blur: int = 24, alpha: int = 90) -> Image.Image:
    """水彩晕染：画在透明层 → 高斯模糊 → 叠上去。"""
    layer = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    drawer(ImageDraw.Draw(layer))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    if alpha < 255:
        r, g, b, a = layer.split()
        layer.putalpha(a.point(lambda v: int(v * alpha / 255)))
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def shape(image: Image.Image, drawer, blur: int = 2) -> Image.Image:
    """画一个实体（带轻微边缘柔化，像手绘）。"""
    layer = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    drawer(ImageDraw.Draw(layer))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def ellipse_poly(x1, y1, x2, y2, n=20):
    cx, cy, rx, ry = (x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) / 2, (y2 - y1) / 2
    return [[int(cx + rx * math.cos(2 * math.pi * i / n)),
             int(cy + ry * math.sin(2 * math.pi * i / n))] for i in range(n)]


def build() -> tuple[Image.Image, list[dict], list[str]]:
    image = paper_base()
    gt: list[dict] = []

    # ---- 大面积水彩：天空 / 草地 ----
    image = wash(image, lambda d: d.rectangle([0, 0, SIZE[0], 780], fill=(168, 208, 235, 255)), blur=30, alpha=150)
    image = wash(image, lambda d: d.rectangle([0, 760, SIZE[0], SIZE[1]], fill=(176, 214, 150, 255)), blur=30, alpha=150)

    # ---- 树（左，占很大面积）----
    image = shape(image, lambda d: d.rectangle([150, 600, 225, 980], fill=(126, 88, 58, 255)))
    image = shape(image, lambda d: d.ellipse([70, 330, 310, 640], fill=(86, 148, 92, 255)))
    image = shape(image, lambda d: d.ellipse([110, 370, 260, 590], fill=(104, 166, 104, 190)))
    gt.append({"label": "树", "polygon": ellipse_poly(70, 330, 310, 640)})

    # ---- 房子（右）----
    image = shape(image, lambda d: d.rectangle([700, 520, 910, 800], fill=(214, 178, 140, 255)))
    image = shape(image, lambda d: d.polygon([(680, 520), (930, 520), (805, 420)], fill=(178, 96, 86, 255)))
    image = shape(image, lambda d: d.rectangle([770, 660, 840, 800], fill=(120, 82, 58, 255)))
    gt.append({"label": "房子", "polygon": [[690, 520], [920, 520], [805, 425], [690, 520]]})

    # ---- 太阳（右上）----
    image = shape(image, lambda d: d.ellipse([860, 80, 970, 190], fill=(250, 205, 90, 255)))
    gt.append({"label": "太阳", "polygon": ellipse_poly(860, 80, 970, 190)})

    # ---- 云（两团）----
    image = shape(image, lambda d: d.ellipse([470, 120, 620, 210], fill=(252, 252, 252, 235)))
    image = shape(image, lambda d: d.ellipse([560, 150, 700, 230], fill=(252, 252, 252, 235)))
    gt.append({"label": "云", "polygon": ellipse_poly(470, 120, 700, 230)})

    # ---- 小鸟（左上空）----
    image = shape(image, lambda d: d.arc([300, 190, 350, 230], 200, 340, fill=(70, 70, 70, 255), width=5))
    image = shape(image, lambda d: d.arc([345, 190, 395, 230], 200, 340, fill=(70, 70, 70, 255), width=5))
    gt.append({"label": "小鸟", "polygon": ellipse_poly(295, 185, 400, 235)})

    # ---- 兔子（中，压着树边缘）----
    image = shape(image, lambda d: d.ellipse([380, 720, 520, 900], fill=(252, 250, 246, 255)))
    image = shape(image, lambda d: d.ellipse([405, 620, 495, 750], fill=(252, 250, 246, 255)))
    image = shape(image, lambda d: d.ellipse([412, 545, 442, 640], fill=(252, 250, 246, 255)))
    image = shape(image, lambda d: d.ellipse([455, 545, 485, 640], fill=(252, 250, 246, 255)))
    image = shape(image, lambda d: d.ellipse([428, 665, 442, 679], fill=(60, 60, 60, 255)), blur=1)
    image = shape(image, lambda d: d.ellipse([458, 665, 472, 679], fill=(60, 60, 60, 255)), blur=1)
    gt.append({"label": "兔子", "polygon": ellipse_poly(380, 545, 520, 900)})

    # ---- 胡萝卜（兔子右边）----
    image = shape(image, lambda d: d.polygon([(560, 800), (620, 820), (566, 920)], fill=(236, 140, 60, 255)))
    image = shape(image, lambda d: d.ellipse([568, 770, 610, 810], fill=(90, 150, 90, 255)))
    gt.append({"label": "胡萝卜", "polygon": [[560, 800], [620, 820], [566, 920], [560, 800]]})

    # ---- 花（草地，小）----
    image = shape(image, lambda d: d.line([(660, 980), (660, 1060)], fill=(80, 130, 80, 255), width=5))
    for dx, dy in ((0, -18), (18, 0), (0, 18), (-18, 0)):
        image = shape(image, lambda d, dx=dx, dy=dy: d.ellipse(
            [660 + dx - 14, 950 + dy - 14, 660 + dx + 14, 950 + dy + 14], fill=(240, 150, 170, 255)))
    gt.append({"label": "花", "polygon": ellipse_poly(630, 925, 690, 985)})

    # ---- 蘑菇（左下，很小）----
    image = shape(image, lambda d: d.ellipse([240, 900, 320, 960], fill=(214, 96, 84, 255)))
    image = shape(image, lambda d: d.rectangle([268, 950, 292, 1000], fill=(246, 240, 226, 255)))
    gt.append({"label": "蘑菇", "polygon": ellipse_poly(240, 900, 320, 960)})

    # ---- 气泡文字（遮挡在天空/树之间）----
    bubble = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    bd = ImageDraw.Draw(bubble)
    bd.rounded_rectangle([470, 380, 780, 500], radius=40, fill=(255, 255, 255, 242),
                         outline=(90, 90, 90, 255), width=3)
    bd.polygon([(520, 495), (560, 560), (590, 495)], fill=(255, 255, 255, 242),
               outline=(90, 90, 90, 255))
    image = Image.alpha_composite(image.convert("RGBA"), bubble).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.text((505, 415), "我也想吃胡萝卜！", font=font(38), fill=(50, 50, 50))

    # ---- 页脚正文 ----
    draw.text((80, 1120), "森林里的新朋友", font=font(50), fill=(40, 40, 40))
    draw.text((80, 1200), "小兔子在树下遇到了小鸟和蘑菇。", font=font(38), fill=(55, 55, 55))

    texts = ["我也想吃胡萝卜！", "森林里的新朋友", "小兔子在树下遇到了小鸟和蘑菇。"]
    return image, gt, texts


def main() -> None:
    image, gt, texts = build()
    OUT.mkdir(parents=True, exist_ok=True)
    image.save(OUT / "p01.png")
    (OUT / "p01.txt").write_text("\n".join(texts) + "\n", encoding="utf-8")
    (OUT / "p01.gt.json").write_text(
        json.dumps({"page_id": "hard01_p01", "objects": gt}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"已生成 {OUT / 'p01.png'}")
    print(f"真值物体 {len(gt)} 个：{'、'.join(o['label'] for o in gt)}")


if __name__ == "__main__":
    main()
