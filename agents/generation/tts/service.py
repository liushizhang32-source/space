"""TTS 独立服务（本地联调 / 演示用）。

启动：
    python -m agents.generation.cli serve --port 8001
或：
    uvicorn agents.generation.tts.service:create_app --factory --port 8001
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..config import Settings
from ..envelope import fail
from ..errors import ErrorCode
from ..ids import new_trace_id
from .api import router
from .client import TTSClient


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_dirs()

    app = FastAPI(title="纸书智伴 · TTS（成员 3）", version="1.0")
    app.state.settings = settings
    app.state.tts_client = TTSClient(settings)
    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(200, fail(ErrorCode.INVALID_PARAM, "请求体不合法", new_trace_id()))

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(200, fail(ErrorCode.UNEXPECTED, "未预期错误", new_trace_id()))

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict:
        """非契约接口，仅用于本服务自检（契约 A7 由成员 1 提供）。"""
        return {
            "status": "ok",
            "engine": app.state.tts_client.engine_name,
            "ffmpeg": bool(settings.ffmpeg),
            "ffprobe": bool(settings.ffprobe),
            "llm_configured": bool(settings.llm_base_url and settings.llm_api_key),
            "data_dir": str(settings.data_dir),
        }

    return app
