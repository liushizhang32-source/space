"""A6 · POST /api/v1/tts（§1.10）。

唯一 owner 是成员 3：视频/故事走进程内函数调用，成员 4 的问答走这个 HTTP 接口。
响应恒为 HTTP 200 + 统一响应体；错误码：1001 缺 text / 1002 参数非法 / 2004 服务不可用 /
3008 合成失败 / 2002 超时。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from ..envelope import fail, ok
from ..errors import AppError, ErrorCode
from ..ids import new_trace_id
from .client import TTSClient

router = APIRouter(prefix="/api/v1", tags=["tts"])


class TTSRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str | None = None
    voice_id: str | None = None
    speed: float | None = None
    format: str | None = None


def _client(request: Request) -> TTSClient:
    return request.app.state.tts_client


@router.post("/tts")
async def synthesize_tts(request: Request, body: TTSRequest) -> JSONResponse:
    trace = new_trace_id()
    try:
        call = await run_in_threadpool(
            _client(request).synthesize, body.text, body.voice_id, body.speed, body.format
        )
    except AppError as exc:
        return JSONResponse(status_code=200, content=fail(exc.code, exc.msg, trace))
    return JSONResponse(status_code=200, content=ok(call.as_response_data(), trace))
