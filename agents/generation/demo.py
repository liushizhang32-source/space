"""离线样例页：没有成员 2 的真实 OCR/VLM 产物时，用来跑通 story->tts->video。

生成的东西全部是 mock：
  uploads/{page_id}_orig.png   合成插图
  json/{page_id}_ocr.json     手写 OCR 结果
  json/{page_id}_vlm.json     手写 VLM 结果
CLI 会在输出里明确标注 mock，避免和真实模型产物混淆。
"""

from __future__ import annotations

from pathlib import Path

from .config import Settings
from .ids import book_id_of, page_no_of, is_page_id
from .storage import PageFiles, write_json

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover
    Image = ImageDraw = ImageFont = None  # type: ignore[assignment]

TEXT_OCR = ["从前有只小兔子，住在森林边上。", "一天晚上，它出门去找朋友。"]
WORDLESS_OCR: list[str] = []
DESCRIPTION = "夜晚的森林，一只小兔子站在树下，月光洒在树梢。"
OBJECTS = [
    {"object_id": "book01_p03_o01", "label": "兔子", "bbox": [420, 620, 620, 900], "confidence": 0.92},
    {"object_id": "book01_p03_o02", "label": "树", "bbox": [60, 470, 300, 1080], "confidence": 0.96},
]
SCENE_TAGS = ["夜晚", "森林"]

FONT_CANDIDATES = (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf")


def _font(size: int):
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def build_sample_image(settings: Settings, page_id: str, text: list[str]) -> Path:
    if Image is None:
        raise RuntimeError("需要 Pillow 才能生成样例插图：pip install pillow")
    width, height = 900, 1200
    image = Image.new("RGB", (width, height), "#16233d")
    draw = ImageDraw.Draw(image)
    for y in range(height):
        shade = int(18 + y / height * 26)
        draw.line([(0, y), (width, y)], fill=(16, shade, 50 + shade))
    draw.ellipse([600, 130, 760, 290], fill="#f4e7c5")
    for x, top in ((70, 420), (700, 520)):
        draw.rectangle([x, top, x + 150, height], fill="#1d3a2c")
        draw.ellipse([x - 40, top - 60, x + 190, top + 110], fill="#22452f")
    draw.rounded_rectangle([390, 640, 660, 930], radius=80, fill="#e9e2d6")
    draw.ellipse([470, 560, 580, 670], fill="#e9e2d6")

    font = _font(40)
    y = 960
    for line in text[:3]:
        draw.text((90, y), line, font=font, fill="#ffffff")
        y += 58

    target = settings.uploads_dir / f"{page_id}_orig.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return target


def build_sample_docs(page_id: str, *, wordless: bool = False) -> tuple[dict, dict]:
    book_id = book_id_of(page_id)
    page_no = page_no_of(page_id)
    texts = WORDLESS_OCR if wordless else TEXT_OCR
    ocr = {
        "schema_version": "1.0",
        "book_id": book_id,
        "page_id": page_id,
        "page_no": page_no,
        "status": "empty" if wordless else "ok",
        "image_width": 900,
        "image_height": 1200,
        "text_blocks": [
            {
                "block_id": f"{page_id}_t{index:02d}",
                "order": index,
                "text": text,
                "bbox": [90, 940 + (index - 1) * 58, 800, 990 + (index - 1) * 58],
                "confidence": 0.97,
            }
            for index, text in enumerate(texts, 1)
        ],
        "page_confidence": 0.97 if texts else 0,
        "elapsed_ms": 1830,
    }
    vlm = {
        "schema_version": "1.0",
        "book_id": book_id,
        "page_id": page_id,
        "page_no": page_no,
        "status": "ok",
        "image_width": 900,
        "image_height": 1200,
        "description": DESCRIPTION,
        "objects": OBJECTS,
        "scene_tags": SCENE_TAGS,
        "safety": {"pass": True, "flags": []},
        "elapsed_ms": 2100,
    }
    return ocr, vlm


def ensure_sample_page(
    settings: Settings,
    page_id: str = "book01_p03",
    *,
    wordless: bool = False,
    overwrite: bool = False,
) -> tuple[dict, dict]:
    if not is_page_id(page_id):
        raise ValueError(f"page_id 格式非法：{page_id!r}")
    ocr, vlm = build_sample_docs(page_id, wordless=wordless)
    files = PageFiles(settings, page_id)

    if overwrite or not files.ocr.is_file():
        write_json(files.ocr, ocr)
    if overwrite or not files.vlm.is_file():
        write_json(files.vlm, vlm)
    if overwrite or files.source_image() is None:
        try:
            texts = [block["text"] for block in ocr["text_blocks"]]
            build_sample_image(settings, page_id, texts)
        except RuntimeError:
            pass  # 没有 Pillow 时仍可生成 story.json，只是没有视频
    return ocr, vlm
