"""M2 单次 Worker 的进程入口（给 M1 Supervisor 指向的绝对路径）。

M1 的调用约定是：

    [解释器绝对路径, 本脚本绝对路径, request.json 绝对路径]

本脚本只做三件事：把 ``src`` 放进 ``sys.path``、调用 ``vision.worker.main``、
把退出码透传出去。真正的协议逻辑都在 ``src/vision/worker.py``，这样既能
被 Supervisor 当子进程调，也能在测试里直接 import。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision.worker import main  # noqa: E402 - 必须在 sys.path 调整之后

if __name__ == "__main__":
    raise SystemExit(main())
