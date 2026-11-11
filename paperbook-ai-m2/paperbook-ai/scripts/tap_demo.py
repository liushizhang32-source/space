"""模拟一次点读：坐标 → 查索引 → 命中物体 + 讲解 + 耗时。

    python scripts/tap_demo.py --page-id book01_p01 --x 620 --y 700
    python scripts/tap_demo.py --page-id book01_p01 --probe     # 网格扫描，看覆盖面
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision import index as index_mod  # noqa: E402
from vision.config import load_env  # noqa: E402


def _tap(page_index, x: int, y: int) -> None:
    started = time.perf_counter()
    obj, how = index_mod.hit_test(page_index, x, y)
    elapsed_ms = (time.perf_counter() - started) * 1000

    if obj is None:
        print(f"({x},{y}) 未命中（{how}），elapsed={elapsed_ms:.2f}ms")
        return
    text = index_mod.explain(page_index, obj)
    print(f"({x},{y}) → {obj.label}  [{how}]  {elapsed_ms:.2f}ms")
    print(f"   bbox={list(obj.bbox)} conf={obj.confidence:.2f}")
    print(f"   讲解：{text}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="点读命中演示")
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--x", type=int)
    parser.add_argument("--y", type=int)
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--probe", action="store_true", help="按 5x5 网格扫描整页")
    args = parser.parse_args(argv)

    load_env()
    data_dir = Path(args.data_dir)
    try:
        page_index = index_mod.load(data_dir, args.page_id)
    except FileNotFoundError:
        print(f"没有索引：{index_mod.index_path(data_dir, args.page_id)}")
        print("先跑 python scripts/build_index.py")
        return 1

    print(f"页面 {page_index.page_id}  {page_index.image_width}x{page_index.image_height}  "
          f"物体 {len(page_index.objects)} 个")
    print(f"        {page_index.description}\n")

    if args.probe:
        width, height = page_index.image_width, page_index.image_height
        for row in range(1, 6):
            for col in range(1, 6):
                x = int(width * col / 5)
                y = int(height * row / 5)
                obj, how = index_mod.hit_test(page_index, x, y)
                label = obj.label if obj else "—"
                print(f"({x:>4},{y:>4}) {label:<6} {how}")
        return 0

    if args.x is None or args.y is None:
        parser.error("要么给 --x/--y，要么加 --probe")
    _tap(page_index, args.x, args.y)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
