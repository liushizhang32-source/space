"""产物落盘（对齐 docs/API_v1.0.md §1.15 文件存储规范）。

规则：文件名固定为 ``{page_id}_{ocr|vlm}.json``，禁止时间戳/随机串做 key；
写入用「临时文件 + 原子替换」，避免中枢读到半截 JSON。
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

OCR_KIND = "ocr"
VLM_KIND = "vlm"


def json_dir(data_dir: str | Path) -> Path:
    path = Path(data_dir) / "json"
    path.mkdir(parents=True, exist_ok=True)
    return path


def json_path(data_dir: str | Path, page_id: str, kind: str) -> Path:
    if kind not in (OCR_KIND, VLM_KIND):
        raise ValueError(f"kind 必须是 ocr/vlm: {kind!r}")
    return json_dir(data_dir) / f"{page_id}_{kind}.json"


def write_json_atomic(path: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # 唯一临时名（pid + 随机后缀）：同进程多线程写同一页也不会互相覆盖
    tmp = target.with_name(f"{target.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, target)
    finally:
        # 写失败/替换失败也不留垃圾临时文件
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return target


def write_json_exclusive(path: str | Path, payload: dict[str, Any]) -> Path:
    """**不覆盖**地写入 JSON（V1.2.1 P0-3）。

    用 ``O_CREAT|O_EXCL`` 直接创建目标文件：目标已存在（含符号链接、
    预置文件、并发抢先创建）时抛 ``FileExistsError``，绝不静默覆盖。
    崩溃留下半截文件也只会待在自己的 attempt 目录里，由 M1 清理。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd = os.open(target, flags, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            target.unlink()
        except OSError:
            pass
        raise
    return target


def log_dir(data_dir: str | Path) -> Path:
    path = Path(data_dir) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def error_log_path(data_dir: str | Path, page_id: str, stage: str) -> Path:
    return log_dir(data_dir) / f"{page_id}_{stage}.error.json"


def write_error_log(
    data_dir: str | Path, page_id: str, stage: str, payload: dict[str, Any]
) -> Path:
    """阶段失败的结构化日志（不进契约文件，供中枢/排障读取）。"""
    return write_json_atomic(error_log_path(data_dir, page_id, stage), payload)


def read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)
