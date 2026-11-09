"""子进程封装：统一超时、隐藏控制台窗口、错误信息截断。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .errors import AppError, ErrorCode

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def run(
    cmd: list[str],
    *,
    timeout: float,
    cwd: str | Path | None = None,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AppError(ErrorCode.TIMEOUT, f"子进程超时（{timeout:.0f}s）：{Path(cmd[0]).name}") from exc


def tail(proc: subprocess.CompletedProcess, limit: int = 800) -> str:
    stderr = (proc.stderr or b"").decode("utf-8", "replace").strip()
    stdout = (proc.stdout or b"").decode("utf-8", "replace").strip()
    text = stderr or stdout
    return text[-limit:]
