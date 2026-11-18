"""生成一张示例绘本页，用于跑通链路与演示（不依赖任何绘本素材）。

python scripts/make_demo_page.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples" / "demo_page.png"
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def main() -> None:
    width, height = 1240, 1754  # 150dpi 的 A4 比例
    image = Image.new("RGB", (width, height), "#fdfaf3")
    draw = ImageDraw.Draw(image)

    # 天空与地面
    draw.rectangle([0, 0, width, int(height * 0.62)], fill="#cfe8f7")
    draw.rectangle([0, int(height * 0.62), width, height], fill="#d9f0d0")

    # 太阳
    draw.ellipse([940, 120, 1120, 300], fill="#ffd966", outline="#e6b800", width=4)

    # 树
    draw.rectangle([250, 620, 320, 980], fill="#8b5a2b")
    draw.ellipse([140, 380, 430, 700], fill="#4f9d4f", outline="#2f6b2f", width=5)

    # 小兔子（简笔）
    draw.ellipse([600, 700, 760, 880], fill="#ffffff", outline="#333333", width=4)  # 身体
    draw.ellipse([640, 600, 720, 720], fill="#ffffff", outline="#333333", width=4)  # 头
    draw.ellipse([648, 520, 676, 620], fill="#ffffff", outline="#333333", width=4)  # 左耳
    draw.ellipse([688, 520, 716, 620], fill="#ffffff", outline="#333333", width=4)  # 右耳
    draw.ellipse([662, 640, 676, 654], fill="#333333")  # 眼
    draw.ellipse([690, 640, 704, 654], fill="#333333")  # 眼
    draw.ellipse([676, 664, 692, 678], fill="#ff9999")  # 鼻子

    # 胡萝卜
    draw.polygon([(800, 780), (860, 800), (806, 900)], fill="#ff8c1a", outline="#cc6600")
    draw.ellipse([810, 740, 850, 780], fill="#4f9d4f")

    # 文字
    title_font = load_font(54)
    body_font = load_font(44)
    draw.text((110, 1200), "小兔子找胡萝卜", font=title_font, fill="#222222")
    draw.text((110, 1300), "森林里，小兔子发现了一根胡萝卜。", font=body_font, fill="#333333")
    draw.text((110, 1380), "它高兴地跳了起来。", font=body_font, fill="#333333")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT)
    print(f"已生成 {OUT} ({width}x{height})")


if __name__ == "__main__":
    main()
