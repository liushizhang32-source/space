"""VLM 子进程执行器（V1.2.1 P0-2）。

为什么要有它：VLM 走常驻 HTTP 服务时，Worker 只是在等 socket。
只杀 Worker 的 Python 进程，不能证明 HTTP 对端已经停止计算。
把这次调用放进**独立子进程**后，M1 杀进程树 / 本模块超时都会
真正终止发起请求的客户端；服务端是否立即释放算力由
``docs/VLM_EXECUTION_BOUNDARY.md`` 里的探针实测给出，不靠猜。

本文件只由 ``vision.worker`` 调用，不是公共接口：

    python -m vision.vlm_child <job.json>

job.json::

    {"image_path": "...", "ocr_text": "...", "out_path": "...", "page_id": "..."}

输出（原子写 ``out_path``）::

    {"ok": true, "description": ..., "objects": [...], "scene_tags": [...],
     "safety_pass": true, "safety_flags": [], "safety_source": "model",
     "confidence_missing": 0}

或 ``{"ok": false, "reason": "..."}``。退出码不作为语义，一律由 out 文件判定。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import preprocess, writer
from .backends import build_vlm_backend


def run(job_path: Path) -> int:
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
        image_path = Path(job["image_path"])
        out_path = Path(job["out_path"])
        ocr_text = str(job.get("ocr_text") or "")
    except Exception as exc:  # noqa: BLE001 - 子进程只回报原因
        print(f"[vlm-child] FATAL 任务不可读: {type(exc).__name__}", file=sys.stderr)
        return 2

    try:
        page = preprocess.load_page_image(image_path)
        backend = build_vlm_backend()
        result = backend.understand(page.image, ocr_text)
        payload = {
            "ok": True,
            "description": result.description,
            "objects": [
                {
                    "label": obj.label,
                    "bbox": [float(v) for v in obj.bbox],
                    "confidence": float(obj.confidence),
                }
                for obj in result.objects
            ],
            "scene_tags": list(result.scene_tags),
            "safety_pass": result.safety_pass,
            "safety_flags": list(result.safety_flags),
            "safety_source": result.safety_source,
            "confidence_missing": int(result.confidence_missing),
        }
        writer.write_json_exclusive(out_path, payload)
        return 0
    except Exception as exc:  # noqa: BLE001
        try:
            writer.write_json_exclusive(
                out_path, {"ok": False, "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}
            )
        except Exception:  # noqa: BLE001
            pass
        print(f"[vlm-child] ERROR {type(exc).__name__}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m vision.vlm_child <job.json>", file=sys.stderr)
        return 2
    return run(Path(args[0]))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
