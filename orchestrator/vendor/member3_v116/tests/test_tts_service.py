"""A6 服务异常处理器：必须 HTTP 200 + 统一响应体（本轮修复点 1）。"""

from __future__ import annotations

import asyncio
import json

from agents.generation.tts.service import handle_unexpected, handle_validation_error


def _run(handler) -> tuple[int, dict]:
    response = asyncio.run(handler(None, None))
    return response.status_code, json.loads(response.body)


def test_validation_error_returns_http_200_and_code_1002():
    status, body = _run(handle_validation_error)
    assert status == 200, "统一响应要求 HTTP 恒 200，不能是 422/500"
    assert body["code"] == 1002
    assert body["data"] is None
    assert body["trace_id"].startswith("tr_")


def test_unhandled_error_returns_http_200_and_code_9001():
    status, body = _run(handle_unexpected)
    assert status == 200
    assert body["code"] == 9001
    assert body["msg"] == "未预期错误"
