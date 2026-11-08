"""一键演示：在 PyCharm 里右键 → Run 即可，不需要任何命令行参数。

跑的是 samples/demo_page.png，输出到 data/json/。
想换图片就改下面的 IMAGE 常量。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision import pipeline  # noqa: E402
from vision.backends import build_ocr_backend, build_vlm_backend  # noqa: E402
from vision.config import load_env  # noqa: E402

IMAGE = ROOT / "samples" / "demo_page.png"
BOOK_ID = "book01"
PAGE_NO = 1


def main() -> int:
    load_env()

    if not IMAGE.is_file():
        print(f"找不到图片：{IMAGE}\n先运行 scripts/make_demo_page.py 生成示例页")
        return 1

    ocr = build_ocr_backend()
    vlm = build_vlm_backend()
    available, reason = ocr.available()
    print(f"[backend] OCR={ocr.name}（{'可用' if available else reason}） VLM={vlm.name}")

    result = pipeline.run_page(
        image_path=IMAGE,
        book_id=BOOK_ID,
        page_no=PAGE_NO,
        data_dir=ROOT / "data",
        ocr_backend=ocr,
        vlm_backend=vlm,
    )

    print(f"\npage_id  : {result.page_id}")
    print(f"image    : {result.ocr['image_width']} x {result.ocr['image_height']}")
    print(f"ocr.json : {result.ocr_path}  [{result.ocr['status']}]  {result.ocr['elapsed_ms']}ms")
    for block in result.ocr["text_blocks"]:
        print(f"  {block['order']:>2}. {block['text']}  "
              f"bbox={block['bbox']}  conf={block['confidence']:.3f}")

    if result.vlm is None:
        print(f"vlm.json : 未产出（阶段失败：{result.vlm_error.message[:80] if result.vlm_error else '未知'}）")
    else:
        print(f"vlm.json : {result.vlm_path}  [{result.vlm['status']}]  "
              f"objects={len(result.vlm['objects'])}")

    if not result.ok:
        for stage_error in (result.ocr_error, result.vlm_error):
            if stage_error:
                print(f"[stage] {stage_error.stage} 失败 code={stage_error.code}: "
                      f"{stage_error.message[:100]}")
        return 3

    errors = [*result.ocr_errors, *result.vlm_errors]
    if errors:
        print("\n[contract] 校验失败：")
        for error in errors:
            print("  -", error)
        return 2
    print("\ncontract : ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
