"""建页级物体索引：data/json/*_vlm.json → data/index/{page_id}.json

    python scripts/build_index.py
    python scripts/build_index.py --page book01_p01
    python scripts/build_index.py --data-dir data

每页只读现成的 vlm.json，**不再调模型**，所以是毫秒级批量。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision import index as index_mod  # noqa: E402
from vision.config import load_env  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 vlm.json 批量建物体索引")
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--page", default=None, help="只处理某一页，如 book01_p01")
    args = parser.parse_args(argv)

    load_env()
    data_dir = Path(args.data_dir)
    json_dir = data_dir / "json"
    if not json_dir.is_dir():
        print(f"没有找到 {json_dir}，先跑一次 run.py / eval/run_batch.py")
        return 1

    pattern = f"{args.page}_vlm.json" if args.page else "*_vlm.json"
    files = sorted(json_dir.glob(pattern))
    if not files:
        print(f"{json_dir} 下没有匹配 {pattern} 的文件")
        return 1

    built = skipped = 0
    total_objects = 0
    for file in files:
        doc = json.loads(file.read_text(encoding="utf-8"))
        if not doc.get("objects") and not (doc.get("description") or "").strip():
            # 打桩产物（VLM 未启用时 description 为空），不建库
            print(f"  跳过 {file.name}: 无物体且无描述（打桩产物）")
            skipped += 1
            continue
        try:
            page_index = index_mod.build_from_vlm(doc)
        except Exception as exc:  # noqa: BLE001
            print(f"  跳过 {file.name}: {exc}")
            skipped += 1
            continue

        # 重建时保留已有的讲解与轮廓（它们要跑模型，别丢）
        existing_path = index_mod.index_path(data_dir, page_index.page_id)
        if existing_path.is_file():
            try:
                previous = index_mod.load(data_dir, page_index.page_id)
                page_index = index_mod.merge_annotations(page_index, previous)
            except Exception:  # noqa: BLE001 - 旧文件坏了就当没有
                pass
        target = index_mod.save(page_index, data_dir)
        built += 1
        total_objects += len(page_index.objects)
        print(f"  {page_index.page_id:<14} objects={len(page_index.objects):<3} "
              f"→ {target.relative_to(ROOT)}")

    print(f"\n完成：{built} 页，{total_objects} 个物体，跳过 {skipped} 页")
    if built:
        print(f"索引目录：{(data_dir / 'index').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
