from typing import Annotated, Literal

from pydantic import BaseModel, Field

PageID = Annotated[str, Field(pattern=r'^[a-z][a-z0-9]{3,11}_p\d{2}$')]


class CaptureForm(BaseModel):
    page_no: int = Field(ge=1, le=99)
    book_id: Annotated[str, Field(pattern=r'^[a-z][a-z0-9]{3,11}$')] | None = None


class GenerateRequest(BaseModel):
    page_ids: list[PageID] = Field(min_length=1, max_length=30)
    age_level: Literal['3-6', '6-9']
    force: bool = False


class GenerateData(BaseModel):
    job_id: str
    status: Literal['queued', 'running']
    poll_after_ms: int = 2000


class StageData(BaseModel):
    name: Literal['ocr', 'vlm', 'story', 'tts', 'render']
    status: Literal['ok', 'empty', 'failed', 'skipped', 'running', 'pending'] = 'pending'
    elapsed_ms: int | None = None


class PageData(BaseModel):
    page_id: str
    page_no: int
    status: Literal['pending', 'processing', 'done', 'partial', 'blocked', 'failed'] = 'pending'
    stages: list[StageData]
    video_url: str | None = None
    story_url: str | None = None
    degraded: list[str] = Field(default_factory=list)
    error: dict | None = None


class JobData(BaseModel):
    job_id: str
    status: Literal['queued', 'running', 'done', 'partial_failed', 'failed', 'cancelled'] = 'queued'
    progress: int = Field(default=0, ge=0, le=100)
    current_stage: Literal['ocr', 'vlm', 'story', 'tts', 'render'] = 'ocr'
    pages: list[PageData]
    error: dict | None = None
    created_at: str
    updated_at: str
