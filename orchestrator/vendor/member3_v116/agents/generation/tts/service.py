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
from orchestrator.core.config import Settings as M1Settings
from orchestrator.services.vision_supervisor.authorization.asset_policy import (
    AssetFiles, offline_mock_enabled,
)

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


def create_app(settings: Settings | None = None, *, m1_assets=None) -> FastAPI:
    settings = settings or Settings.from_env()
    # M1 owns configuration validation and release policy, including direct
    # factory calls. Never infer authorization from Member3 settings or headers.
    asset_settings = M1Settings(data_dir=settings.data_dir)
    settings.ensure_dirs()

    app = FastAPI(title="纸书智伴 · TTS（成员 3）", version="1.0")
    app.state.settings = settings
    app.state.tts_client = TTSClient(settings)
    app.include_router(router)
    if m1_assets is not None:
        from orchestrator.services.offline_protocols.assets import PrivateAssets
        if type(m1_assets) is not PrivateAssets or asset_settings.deployment_env != 'local' or asset_settings.asset_mode != 'blocked':
            raise ValueError('Private offline assets require local M1 authority')
        app.mount('/_m1/assets', m1_assets.http_app(), name='m1-private-assets')
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected)

    @app.middleware("http")
    async def protect_cached_tts_reads(request: Request, call_next):
        # Synthesis may read an existing private cache (ffprobe/ffmpeg) before
        # returning its URL. Deny before entering that path outside Mock demos.
        if request.method == "POST" and request.url.path == "/api/v1/tts":
            if asset_settings.asset_mode != "offline_mock" or not offline_mock_enabled():
                return JSONResponse(status_code=200, content=fail(
                    ErrorCode.UNAVAILABLE, "资产授权不可用", new_trace_id()))
        return await call_next(request)

    # 让 A6 返回的 audio_url 在本服务下真的可访问（默认 8001 而非 8000）
    app.mount("/audios", AssetFiles(directory=settings.audios_dir,
                                    mode=asset_settings.asset_mode), name="audios")

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
