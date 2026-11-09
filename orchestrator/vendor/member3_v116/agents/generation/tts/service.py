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
from fastapi.staticfiles import StaticFiles

from ..config import Settings
from ..envelope import fail
from ..errors import ErrorCode
from ..ids import new_trace_id
from .api import router
from .client import TTSClient


async def handle_validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    """请求体类型错误：HTTP 仍为 200，业务码 1002。"""
    return JSONResponse(
        status_code=200,
        content=fail(ErrorCode.INVALID_PARAM, "请求体不合法", new_trace_id()),
    )


async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
    """兜底：绝不能让 FastAPI 返回 500（契约要求 HTTP 恒 200）。"""
    return JSONResponse(
        status_code=200,
        content=fail(ErrorCode.UNEXPECTED, "未预期错误", new_trace_id()),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_dirs()

    app = FastAPI(title="纸书智伴 · TTS（成员 3）", version="1.0")
    app.state.settings = settings
    app.state.tts_client = TTSClient(settings)
    app.include_router(router)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected)

    # 让 A6 返回的 audio_url 在本服务下真的可访问（默认 8001 而非 8000）
    app.mount("/audios", StaticFiles(directory=str(settings.audios_dir)), name="audios")

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
