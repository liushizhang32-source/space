import asyncio
from datetime import datetime, timezone
from time import perf_counter

from orchestrator.api.models import GenerateData, GenerateRequest, JobData, PageData, StageData
from orchestrator.core.errors import APIError
from orchestrator.core.ids import new_id
from orchestrator.services.storage import Storage

STAGES = ('ocr', 'vlm', 'story', 'tts', 'render')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


class Jobs:
    """Single-event-loop in-memory jobs. Creation/cancellation has no await gap."""
    def __init__(self, storage: Storage):
        self.storage = storage
        self.settings = storage.settings
        self.jobs: dict[str, JobData] = {}
        self.tasks: dict[str, asyncio.Task] = {}

    def create(self, request: GenerateRequest) -> GenerateData:
        ids = set(request.page_ids)
        if len(ids) != len(request.page_ids):
            raise APIError(1002, 'page_ids 不得重复')
        if not ids <= self.storage.pages.keys():
            raise APIError(1003, 'page_id 不存在，请先上传图片')
        active = [j for j in self.jobs.values() if j.status in ('queued', 'running')]
        overlapping = [j for j in active if ids.intersection(p.page_id for p in j.pages)]
        if overlapping and not request.force:
            existing = overlapping[0]
            if ids != {p.page_id for p in existing.pages}:
                raise APIError(2003, '部分页面已有运行任务，请等待完成或使用 force')
            return GenerateData(job_id=existing.job_id, status=existing.status)
        if len(active) - len(overlapping) >= self.settings.max_concurrent_jobs:
            raise APIError(2003, '并发任务数超出限制')
        for old in overlapping:
            self.tasks[old.job_id].cancel()
            old.status = 'cancelled'
            old.updated_at = now()
        stamp = now()
        job = JobData(job_id=new_id('job'), created_at=stamp, updated_at=stamp,
                      pages=[PageData(page_id=pid, page_no=self.storage.pages[pid]['page_no'],
                                      stages=[StageData(name=s) for s in STAGES])
                             for pid in sorted(ids, key=lambda p: self.storage.pages[p]['page_no'])])
        self.jobs[job.job_id] = job
        self.tasks[job.job_id] = asyncio.create_task(self.run(job, request.age_level))
        return GenerateData(job_id=job.job_id, status='queued')

    def get(self, job_id: str) -> JobData:
        if job_id not in self.jobs:
            # §1.7 / A3 error scenario uses 1003, despite general error table 3005.
            raise APIError(1003, 'job_id 不存在')
        return self.jobs[job_id].model_copy(deep=True)

    async def run(self, job: JobData, age_level: str):
        try:
            await asyncio.sleep(self.settings.queue_delay)
            job.status = 'running'
            for page in job.pages:
                page.status = 'processing'
                for stage in page.stages:
                    job.current_stage = stage.name
                    stage.status = 'running'
                    job.updated_at = now()
                    started = perf_counter()
                    await asyncio.sleep(self.settings.stage_delay)
                    # Tiny local fixture writes are synchronous, preventing cancelled
                    # jobs from overwriting replacements after their cancellation.
                    self.storage.produce(page.page_id, stage.name, age_level)
                    stage.elapsed_ms = round((perf_counter()-started)*1000)
                    stage.status = 'empty' if stage.name in ('ocr', 'vlm') else 'ok'
                    if stage.name == 'story':
                        page.story_url = self.settings.url(f'json/{page.page_id}_story.json')
                    if stage.name == 'render':
                        page.video_url = self.settings.url(f'videos/{page.page_id}_video.mp4')
                    completed = sum(s.status in ('ok', 'empty') for p in job.pages for s in p.stages)
                    job.progress = completed * 100 // (len(job.pages)*len(STAGES))
                    job.updated_at = now()
                page.status = 'done'
            job.status = 'done'
            job.updated_at = now()
        except asyncio.CancelledError:
            raise
        except Exception:
            job.status = 'failed'
            job.error = {'code': 9001, 'msg': 'Mock 本地产物生成失败'}
            for page in job.pages:
                if page.status == 'processing':
                    page.status = 'failed'
                    page.error = job.error.copy()
                    for stage in page.stages:
                        if stage.status == 'running':
                            stage.status = 'failed'
            job.updated_at = now()

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
