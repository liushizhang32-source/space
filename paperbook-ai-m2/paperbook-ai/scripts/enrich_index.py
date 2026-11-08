"""给索引补儿童化讲解（离线一次，点读零延迟）。

    python scripts/enrich_index.py --page-id book01_p01 --image samples/demo_page.png
    python scripts/enrich_index.py --page-id book01_p01 --image ... --force   # 重新生成

每页只调一次 VLM（约 15-20 s），结果写回 data/index/{page_id}.json。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision import explain as explain_mod  # noqa: E402
from vision import index as index_mod  # noqa: E402
from vision.backends import build_vlm_backend  # noqa: E402
from vision.config import load_env  # noqa: E402
from vision.preprocess import load_page_image  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="为物体索引生成讲解")
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--image", required=True, help="该页原图路径")
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--force", action="store_true", help="已有讲解也重新生成")
    args = parser.parse_args(argv)

    load_env()
    data_dir = Path(args.data_dir)
    try:
        page_index = index_mod.load(data_dir, args.page_id)
    except FileNotFoundError:
        print(f"没有索引：{index_mod.index_path(data_dir, args.page_id)}")
        print("先跑 python scripts/build_index.py")
        return 1

    if not page_index.objects:
        print(f"{args.page_id} 没有物体，跳过")
        return 1

    already = sum(1 for o in page_index.objects if o.explanation)
    if already == len(page_index.objects) and not args.force:
        print(f"{args.page_id} 已有全部讲解，跳过（加 --force 可重生成）")
        return 0

    image_path = Path(args.image)
    if not image_path.is_absolute():
        image_path = (ROOT / image_path).resolve()
    if not image_path.is_file():
        print(f"找不到图片：{image_path}")
        return 1

    backend = build_vlm_backend()
    available, reason = backend.available()
    if not available:
        print(f"VLM 不可用：{reason}")
        return 1

    labels = [o.label for o in page_index.objects]
    print(f"页面 {args.page_id}，物体 {len(labels)} 个：{'、'.join(labels)}")
    print(f"调用 {backend.name} 生成讲解…")

    page = load_page_image(image_path)
    try:
        # 讲解是一次性投入，预算给足：思考版模型在 4000 以内可能只输出思考
        budget = int(os.getenv("QWEN_VL_EXPLAIN_TOKENS", "6000"))
        mapping = explain_mod.explain_objects(backend, page.image, labels, max_tokens=budget)
    except Exception as exc:  # noqa: BLE001
        print(f"生成失败：{type(exc).__name__}: {exc}")
        return 2

    updated, hit = index_mod.with_explanations(page_index, mapping)
    target = index_mod.save(updated, data_dir)

    print()
    for obj in updated.objects:
        print(f"  {obj.label:<6} {obj.explanation or '（未生成，保留模板）'}")
    print(f"\n命中 {hit}/{len(labels)}，写入 {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
