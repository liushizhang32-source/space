"""生成一套可复现的"演示绘本"，用来验证批量与评测链路。

产物：samples/books_demo/{demo01,demo02}/pXX.png + 同名 .txt 真值

注意：这是**合成数据**，只用来验证流程与拍摄退化实验，
      不能当成"组委会绘本的识别准确率"对外汇报。
拿到真书后，把它放到 samples/books/ 下即可，脚本不用改。
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples" / "books_demo"
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)
SIZE = (1000, 1414)

BOOKS = {
    "demo01": [
        ("小兔子找胡萝卜", ["森林里，小兔子发现了一根胡萝卜。", "它高兴地跳了起来。"], None),
        ("回家的路", ["天黑了，小兔子沿着小溪往家走。", "萤火虫为它照亮了小路。"], "rotate"),
        ("分享", ["小兔子把胡萝卜分给了好朋友。", "大家一起吃得真开心。"], None),
    ],
    "demo02": [
        ("下雨天", ["雨点落在树叶上，滴答滴答。", "小兔子躲进了蘑菇伞下。"], "blur"),
        ("彩虹", ["雨停了，天上出现了一道彩虹。", "小兔子数了数，有七种颜色。"], "jpeg"),
        ("夜晚的森林", ["月亮升起来了，森林静悄悄的。", "猫头鹰在树上眨着眼睛。"], "shadow"),
    ],
    "demo03": [
        ("春天来了", ["小草从土里钻出来，绿绿的。", "小兔子在草地上打滚。"], "stress_blur"),
        ("朋友", ["小鸟落在树枝上，唱着歌。", "小兔子抬头跟它打招呼。"], "stress_jpeg"),
        ("睡觉", ["夜深了，星星一闪一闪。", "小兔子盖上被子睡着了。"], "stress_shadow"),
    ],
}


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def ellipse_polygon(bbox: list[int], points: int = 24) -> list[list[int]]:
    """把椭圆采样成多边形（真值用）。"""
    import math

    x1, y1, x2, y2 = bbox
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    rx, ry = (x2 - x1) / 2, (y2 - y1) / 2
    return [
        [int(cx + rx * math.cos(2 * math.pi * i / points)),
         int(cy + ry * math.sin(2 * math.pi * i / points))]
        for i in range(points)
    ]


def convex_hull(points: list[list[int]]) -> list[list[int]]:
    """Andrew 单调链，用来把兔子（身体+头+耳朵）合成一个轮廓。"""
    pts = sorted({(p[0], p[1]) for p in points})

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[int, int]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[int, int]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return [[x, y] for x, y in hull]


def scene_gt() -> list[dict]:
    """这一页画了什么、在哪里——**真值来自绘图代码，与 VLM/索引无关**。"""
    rabbit_parts = (
        ellipse_polygon([520, 640, 660, 800])   # 身体
        + ellipse_polygon([555, 550, 625, 660])  # 头
        + ellipse_polygon([562, 480, 586, 566])  # 左耳
        + ellipse_polygon([596, 480, 620, 566])  # 右耳
    )
    return [
        {"label": "树", "polygon": ellipse_polygon([110, 340, 350, 610])},
        {"label": "兔子", "polygon": convex_hull(rabbit_parts)},
        {"label": "太阳", "polygon": ellipse_polygon([780, 90, 930, 240])},
    ]


def draw_page(title: str, lines: list[str]) -> Image.Image:
    width, height = SIZE
    image = Image.new("RGB", (width, height), "#fdfaf3")
    draw = ImageDraw.Draw(image)

    draw.rectangle([0, 0, width, int(height * 0.58)], fill="#cfe8f7")
    draw.rectangle([0, int(height * 0.58), width, height], fill="#d9f0d0")
    draw.ellipse([780, 90, 930, 240], fill="#ffd966", outline="#e6b800", width=4)
    draw.rectangle([200, 560, 260, 840], fill="#8b5a2b")
    draw.ellipse([110, 340, 350, 610], fill="#4f9d4f", outline="#2f6b2f", width=5)
    draw.ellipse([520, 640, 660, 800], fill="#ffffff", outline="#333333", width=4)
    draw.ellipse([555, 550, 625, 660], fill="#ffffff", outline="#333333", width=4)
    draw.ellipse([562, 480, 586, 566], fill="#ffffff", outline="#333333", width=4)
    draw.ellipse([596, 480, 620, 566], fill="#ffffff", outline="#333333", width=4)
    draw.ellipse([572, 585, 584, 597], fill="#333333")
    draw.ellipse([596, 585, 608, 597], fill="#333333")

    draw.text((80, 980), title, font=load_font(50), fill="#222222")
    for index, line in enumerate(lines):
        draw.text((80, 1070 + index * 74), line, font=load_font(40), fill="#333333")
    return image


def _shadow(image: Image.Image) -> Image.Image:
    width, height = image.size
    overlay = Image.new("L", (width, height))
    pixels = overlay.load()
    for x in range(width):
        shade = int(40 + 170 * (x / width))
        for y in range(height):
            pixels[x, y] = min(255, shade)
    shade_layer = Image.new("RGB", (width, height), "black")
    return Image.composite(image, shade_layer, overlay.point(lambda v: 255 - int(v * 0.35)))


def _jpeg(image: Image.Image, quality: int) -> Image.Image:
    tmp = Path("_tmp_jpeg.jpg")
    image.save(tmp, quality=quality)
    with Image.open(tmp) as reloaded:
        result = reloaded.convert("RGB")
    tmp.unlink(missing_ok=True)
    return result


def degrade(image: Image.Image, kind: str | None) -> Image.Image:
    if kind == "rotate":  # 手持轻微倾斜
        return image.rotate(1.8, resample=Image.BICUBIC, fillcolor="white")
    if kind == "blur":  # 对焦不准
        return image.filter(ImageFilter.GaussianBlur(0.9))
    if kind == "jpeg":  # 压缩严重
        return _jpeg(image, 32)
    if kind == "shadow":  # 手机挡住光线的阴影
        return _shadow(image)

    # ---- 压力条件：模拟手机上拍糊 / 压缩 / 阴影叠加 ----
    if kind == "stress_blur":
        width, height = image.size
        blurred = image.filter(ImageFilter.GaussianBlur(2.2))
        return blurred.resize((520, int(520 * height / width)), Image.BICUBIC)
    if kind == "stress_jpeg":
        return _jpeg(image.rotate(3.5, resample=Image.BICUBIC, fillcolor="white"), 15)
    if kind == "stress_shadow":
        return _jpeg(_shadow(image).filter(ImageFilter.GaussianBlur(1.2)), 20)
    return image


def main() -> None:
    # 只有"不改变几何"的退化（模糊/压缩/阴影）才能沿用原始真值坐标；
    # 旋转、缩放会移动像素，不写 gt，避免用错真值。
    geometry_safe = {None, "blur", "jpeg", "shadow"}
    for book_id, pages in BOOKS.items():
        book_dir = OUT / book_id
        book_dir.mkdir(parents=True, exist_ok=True)
        for index, (title, lines, kind) in enumerate(pages, start=1):
            image = degrade(draw_page(title, lines), kind)
            image.save(book_dir / f"p{index:02d}.png")
            truth = "\n".join([title, *lines])
            (book_dir / f"p{index:02d}.txt").write_text(truth + "\n", encoding="utf-8")
            if kind in geometry_safe:
                page_id = f"{book_id}_p{index:02d}"
                gt = {"page_id": page_id, "objects": scene_gt()}
                (book_dir / f"p{index:02d}.gt.json").write_text(
                    json.dumps(gt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            print(f"{book_id}/p{index:02d}.png  {kind or 'clean'}")
    print(f"\n已生成 {OUT}")


if __name__ == "__main__":
    main()
