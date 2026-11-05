from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from orchestrator.api.models import CaptureForm, GenerateData, GenerateRequest, JobData
from orchestrator.core.errors import APIError
from orchestrator.schemas.capture import CaptureResponse
from orchestrator.schemas.common import APIResponse
from orchestrator.services.storage import MAX_IMAGE_BYTES

router = APIRouter(prefix='/api/v1')


@router.post('/capture', response_model=CaptureResponse)
async def capture(request: Request, image: Annotated[UploadFile, File()],
                  page_no: Annotated[int, Form()], book_id: Annotated[str | None, Form()] = None):
    try:
        form = CaptureForm(page_no=page_no, book_id=book_id)
    except ValidationError as exc:
        raise APIError(1002, 'page_no 或 book_id 非法（页码需为 1–99）') from exc
    try:
        content = await image.read(MAX_IMAGE_BYTES + 1)
        data = await run_in_threadpool(request.app.state.storage.capture, content,
                                      image.filename or '', image.content_type or '',
                                      form.page_no, form.book_id)
    finally:
        await image.close()
    return CaptureResponse(data=data, trace_id=request.state.trace_id)


@router.post('/generate', response_model=APIResponse[GenerateData])
async def generate(request: Request, body: GenerateRequest):
    data = request.app.state.jobs.create(body)
    return APIResponse[GenerateData](data=data, trace_id=request.state.trace_id)


@router.get('/jobs/{job_id}', response_model=APIResponse[JobData])
async def get_job(request: Request, job_id: str):
    data = request.app.state.jobs.get(job_id)
    return APIResponse[JobData](data=data, trace_id=request.state.trace_id)
