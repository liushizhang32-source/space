"""交付自检：确认这一页的 OCR/VLM 是**真跑出来的**，不是打桩、不是隔夜旧文件。

    python scripts/verify_handoff.py --page book01_p01
    python scripts/verify_handoff.py --page book01_p01 --max-age-min 5

M1 触发一次 /generate 后跑这个，全 PASS 才算第 2 条真的接上了。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision import validate  # noqa: E402
from vision.config import load_env  # noqa: E402

OK = "PASS"
BAD = "FAIL"
NOTE = "INFO"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查视觉产物是否可用于交付")
    parser.add_argument("--page", required=True, help="如 book01_p01")
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--max-age-min", type=float, default=None,
                        help="要求文件是最近 N 分钟内生成的")
    args = parser.parse_args(argv)

    load_env()
    data_dir = Path(args.data_dir)
    failures = 0

    def report(status: str, title: str, detail: str = "") -> None:
        nonlocal failures
        if status == BAD:
            failures += 1
        print(f"[{status}] {title}" + (f"  {detail}" if detail else ""))

    for kind in ("ocr", "vlm"):
        path = data_dir / "json" / f"{args.page}_{kind}.json"
        if not path.is_file():
            # VLM 阶段失败时不产出文件，详情在 logs/*.error.json
            log = data_dir / "logs" / f"{args.page}_{kind}.error.json"
            if log.is_file():
                detail = json.loads(log.read_text(encoding="utf-8"))
                report(
                    BAD,
                    f"{kind} 阶段失败",
                    f"code={detail.get('code')} {str(detail.get('message'))[:80]}",
                )
            else:
                report(BAD, f"{kind}.json 不存在", str(path))
            continue

        doc = json.loads(path.read_text(encoding="utf-8"))
        errors = validate.validate(doc, kind)
        if errors:
            report(BAD, f"{kind}.json 契约不合规", errors[0])
            continue

        producer = doc.get("producer") or {}
        backend = producer.get("backend")
        elapsed = int(doc.get("elapsed_ms", 0) or 0)
        status = doc.get("status")

        report(OK, f"{kind}.json 存在且合规", f"status={status} {elapsed}ms")

        # 附加字段默认关闭（公共 Schema 不允许），所以 backend 可能缺失
        if backend in ("stub", "skipped"):
            report(BAD, f"{kind} 是打桩产物", f"backend={backend}，M1 没真正调用视觉模块")
        elif backend is None:
            if elapsed <= 0:
                report(BAD, f"{kind} elapsed_ms=0", "几乎可以确定不是真模型跑的")
            else:
                report(NOTE, f"{kind} 未附带 producer", "按耗时判断为真实运行")
        else:
            report(OK, f"{kind} 由真实后端产出", f"backend={backend}")

        if args.max_age_min is not None:
            age_min = (time.time() - path.stat().st_mtime) / 60
            if age_min > args.max_age_min:
                report(BAD, f"{kind}.json 太旧", f"{age_min:.1f} 分钟前生成，要求 ≤{args.max_age_min}")
            else:
                report(OK, f"{kind}.json 是本次任务生成的", f"{age_min:.1f} 分钟前")

    index_path = data_dir / "index" / f"{args.page}.json"
    if index_path.is_file():
        page_index = json.loads(index_path.read_text(encoding="utf-8"))
        objects = page_index.get("objects") or []
        report(OK, "物体索引存在", f"{len(objects)} 个物体（点读可用）")
    else:
        report(NOTE, "物体索引缺失", "点读不可用；跑 scripts/build_index.py")

    draft = data_dir / "draft" / f"{args.page}_story.json"
    if draft.is_file():
        report(NOTE, "story 草稿存在", "M3 已能读视觉产物")
    else:
        report(NOTE, "story 草稿缺失", "M3 还没消费这些产物")

    print()
    if failures:
        print(f"结果：{failures} 项不通过 —— 第 2 条还没真正接上")
        return 1
    print("结果：全部通过 —— 视觉产物可用于交付")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
