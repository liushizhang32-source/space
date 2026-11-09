"""统一响应体（§1.2.1）：HTTP 恒 200，业务结果只看 code。"""

from __future__ import annotations

from .errors import ErrorCode
from .ids import new_trace_id


def ok(data, trace_id: str | None = None) -> dict:
    return {
        "code": int(ErrorCode.OK),
        "msg": "ok",
        "data": data,
        "trace_id": trace_id or new_trace_id(),
    }


def fail(code: ErrorCode | int, msg: str, trace_id: str | None = None) -> dict:
    return {
        "code": int(code),
        "msg": msg,
        "data": None,
        "trace_id": trace_id or new_trace_id(),
    }
