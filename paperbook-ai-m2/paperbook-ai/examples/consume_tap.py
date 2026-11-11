"""M4 视角：点读坐标 → 一条符合 A5 契约的 /qa 响应。

    python examples/consume_tap.py --page book01_p01 --x 660 --y 700
    python examples/consume_tap.py --page book01_p01 --x 100 --y 1600   # 空白处

M4 可以照抄这里的字段：`citations`、`is_fallback`、`code` 的取值方式。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision import index as vindex  # noqa: E402
from vision.config import load_env  # noqa: E402

FALLBACK_ANSWER = "这个问题我还不知道，我们一起看看书上画了什么吧"


def make_response(page_id: str, x: int, y: int, data_dir: Path) -> dict:
    # 索引常驻内存时，一次点读只有几十微秒；这里把"读文件"和"命中"分开计时
    page = vindex.load(data_dir, page_id)
    started = time.perf_counter()
    obj, how = vindex.hit_test(page, x, y)
    elapsed = (time.perf_counter() - started) * 1000

    if obj is None:
        data = {
            "answer_id": f"ans_{uuid.uuid4().hex[:26]}",
            "answer": FALLBACK_ANSWER,
            "is_fallback": True,
            "citations": [],
            "audio_url": None,
            "safety": {"pass": True, "flags": []},
            "latency_ms": {"asr": 0, "llm": 0, "tts": 0, "total": round(elapsed, 3)},
        }
    else:
        data = {
            "answer_id": f"ans_{uuid.uuid4().hex[:26]}",
            "answer": vindex.explain(page, obj),
            "is_fallback": False,
            "citations": [
                {
                    "page_id": page.page_id,
                    "object_ids": [obj.object_id],
                    "bbox": list(obj.bbox),
                }
            ],
            "audio_url": None,  # 由 M3 的 TTS 填
            "safety": {"pass": True, "flags": []},
            "latency_ms": {"asr": 0, "llm": 0, "tts": 0, "total": round(elapsed, 3)},
        }

    return {
        "code": 0,
        "msg": "ok",
        "data": data,
        "trace_id": f"tr_{uuid.uuid4().hex[:26]}",
        "_debug": {"hit": how, "x": x, "y": y},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="点读 → /qa 响应示例")
    parser.add_argument("--page", required=True)
    parser.add_argument("--x", type=int, required=True)
    parser.add_argument("--y", type=int, required=True)
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    args = parser.parse_args(argv)

    load_env()
    data_dir = Path(args.data_dir)
    if not (data_dir / "index" / f"{args.page}.json").is_file():
        print(f"缺少索引 data/index/{args.page}.json，先跑 scripts/build_index.py")
        return 1

    response = make_response(args.page, args.x, args.y, data_dir)
    print(f"# 命中方式: {response['_debug']['hit']}")
    response.pop("_debug", None)
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
