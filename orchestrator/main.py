from contextlib import asynccontextmanager
from contextlib import nullcontext

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from orchestrator.services.vision_supervisor.authorization.asset_policy import AssetFiles

from orchestrator.api.routes import router
from orchestrator.core.config import Settings
from orchestrator.core.errors import APIError
from orchestrator.core.ids import new_id
from orchestrator.schemas.common import APIResponse
from orchestrator.services.jobs import Jobs
from orchestrator.services.storage import Storage


def create_app(settings: Settings | None = None, *, m1_session_factory=None, m1_assets=None, m1_publisher=None, m1_runtime_guard=None) -> FastAPI:
    settings = settings or Settings()
    storage = Storage(settings)
    if settings.generation_backend == 'member3':
        from orchestrator.services.member3_jobs import Member3Jobs
        jobs_class = Member3Jobs
    else:
        jobs_class = Jobs

    @asynccontextmanager
    async def lifespan(app):
        with m1_runtime_guard() if m1_runtime_guard is not None else nullcontext():
            app.state.jobs = (jobs_class(storage, m1_session_factory=m1_session_factory,m1_publisher=m1_publisher)
                              if m1_session_factory is not None and settings.generation_backend == 'member3'
                              else jobs_class(storage))
            try:yield
            finally:await app.state.jobs.close()

    app = FastAPI(title='纸书智伴 Orchestrator Mock', version='1.0', lifespan=lifespan)
    app.state.storage = storage

    @app.middleware('http')
    async def trace(request: Request, call_next):
        request.state.trace_id = new_id('tr')
        response = await call_next(request)
        response.headers['X-Trace-ID'] = request.state.trace_id
        return response

    def error(request: Request, code: int, msg: str):
        payload = APIResponse[dict](code=code, msg=msg, trace_id=request.state.trace_id)
        return JSONResponse(payload.model_dump(mode='json'), status_code=200)

    @app.exception_handler(APIError)
    async def business_error(request: Request, exc: APIError):
        return error(request, exc.code, exc.msg)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        missing = [e for e in exc.errors() if e['type'] == 'missing']
        names = ', '.join(str(e['loc'][-1]) for e in (missing or exc.errors()))
        return error(request, 1001 if missing else 1002,
                     ('缺少参数 ' if missing else '参数非法 ') + names)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error(request, 1003 if exc.status_code == 404 else 1002, str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        return error(request, 9001, '未预期错误')

    app.include_router(router)
    if m1_assets is not None:
        from orchestrator.services.offline_protocols.assets import PrivateAssets
        if type(m1_assets) is not PrivateAssets or settings.deployment_env != 'local' or settings.asset_mode != 'blocked':
            raise ValueError('Private offline assets require local M1 authority')
        app.mount('/_m1/assets', m1_assets.http_app(), name='m1-private-assets')
    for directory in ('previews', 'json', 'audios', 'videos'):
        app.mount('/' + directory, AssetFiles(directory=storage.root / directory,
                                             mode=settings.asset_mode), name=directory)
    return app


app = create_app()
