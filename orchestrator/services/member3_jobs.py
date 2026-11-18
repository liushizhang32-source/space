"""Async orchestration around isolated, synchronous member3 stage workers."""
import asyncio
import logging
import threading
import json
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

from orchestrator.core.errors import APIError
from orchestrator.services.jobs import Jobs, now
from orchestrator.services.member3_adapter import AppError, Member3Adapter

logger = logging.getLogger(__name__)


class Member3Jobs(Jobs):
    def __init__(self, storage, m1_session_factory=None,m1_publisher=None):
        super().__init__(storage)
        self.adapter = Member3Adapter(storage, m1_session_factory=m1_session_factory,m1_publisher=m1_publisher)
        if self.settings.persist_state:
            from orchestrator.api.models import JobData
            for key,raw in storage.read_state('jobs').items():
                job=JobData.model_validate(raw)
                if key!=job.job_id:raise ValueError('Job checkpoint identity mismatch')
                if job.status in {'queued','running'}:
                    job.status='cancelled';job.updated_at=now()
                    job.error={'code':2004,'msg':'服务重启中断；M1预算按权威状态保留，未自动重试'}
                    for page in job.pages:
                        if page.status in {'pending','processing'}:
                            page.status='failed';page.error=job.error.copy()
                            for stage in page.stages:
                                if stage.status=='running':stage.status='failed'
                                elif stage.status=='pending':stage.status='skipped'
                self.jobs[key]=job
        self.m1_receipts = {}
        self.m1_reconciliation = {}
        self._executor = ThreadPoolExecutor(max_workers=self.settings.max_concurrent_jobs,
                                            thread_name_prefix='member3')
        self._workers = set()
        self._cancel_flags = {}
        self._shutdown_task = None
        self._shutting_down = False
        self._job_drain = None
        self._worker_drain = None

    def create(self, request):
        if self._shutting_down:
            raise APIError(2004, '生成服务正在关闭')
        result=super().create(request);self.checkpoint();return result

    def checkpoint(self):
        if self.settings.persist_state:self.storage.write_state('jobs',{key:job.model_dump(mode='json') for key,job in self.jobs.items()})

    async def work(self, fn, *args):
        if self._shutting_down:
            raise asyncio.CancelledError
        owner = asyncio.current_task()
        flag = self._cancel_flags.setdefault(owner, threading.Event())
        if flag.is_set():
            raise asyncio.CancelledError
        def invoke():
            if flag.is_set():
                return None
            return fn(*args)
        # Retain the real executor Future; cancelling an asyncio wrapper does not
        # stop a thread. There is exactly one wrapper/drain for this submission.
        worker = self._executor.submit(invoke)
        self._workers.add(worker)
        drain = asyncio.wrap_future(worker)
        cancelled = False
        try:
            while True:
                try:
                    result = await asyncio.shield(drain)
                    break
                except asyncio.CancelledError:
                    cancelled = True
                    flag.set()
                    if drain.done():
                        if not drain.cancelled():
                            drain.exception()  # retrieve a coincident worker error
                        raise
                    continue
                except BaseException:
                    if cancelled:
                        raise asyncio.CancelledError from None
                    raise
            if cancelled or flag.is_set():
                raise asyncio.CancelledError
            return result
        finally:
            # Reached only after the real Future has completed.
            self._workers.discard(worker)

    async def close(self):
        if self._shutdown_task is None:
            self._shutting_down = True
            self._shutdown_task = asyncio.create_task(self._shutdown())
        cancelled = False
        while True:
            try:
                await asyncio.shield(self._shutdown_task)
                break
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError

    async def _shutdown(self):
        for flag in self._cancel_flags.values():
            flag.set()
        for task in self.tasks.values():
            if not task.done() and not task.cancelling():
                task.cancel()
        for job in self.jobs.values():
            if job.status in ('queued', 'running'):
                job.status = 'cancelled'
                job.updated_at = now()
        self._job_drain = asyncio.gather(*self.tasks.values(), return_exceptions=True)
        await asyncio.shield(self._job_drain)
        self._worker_drain = asyncio.gather(
            *(asyncio.wrap_future(f) for f in self._workers), return_exceptions=True)
        await asyncio.shield(self._worker_drain)
        self._executor.shutdown(wait=True)
        self.checkpoint()

    @staticmethod
    def progress(job):
        job.progress = sum(s.status in ('ok', 'empty', 'failed', 'skipped')
                           for p in job.pages for s in p.stages)*100//sum(len(p.stages) for p in job.pages)
        job.updated_at = now()

    async def run(self, job, age_level):
        try:
            await self._run(job, age_level)
        except asyncio.CancelledError:
            job.status = 'cancelled'
            job.updated_at = now()
            raise
        finally:
            self._cancel_flags.pop(asyncio.current_task(), None)
            self.checkpoint()

    async def _run(self, job, age_level):
        await asyncio.sleep(self.settings.queue_delay)
        job.status = 'running'
        for page in job.pages:
            session = None
            page.status = 'processing'
            started = perf_counter()
            try:
                session = self.adapter.session(page.page_id, job.job_id)
                flag = self._cancel_flags.setdefault(asyncio.current_task(), threading.Event())
                session.cancelled = flag.is_set
                for stage in page.stages:
                    stage.status = 'running'
                    job.current_stage = stage.name
                    job.updated_at = now()
                    started = perf_counter()
                    await asyncio.sleep(self.settings.stage_delay)
                    result = await self.work(session.step, stage.name, age_level)
                    stage.status = result.status
                    stage.elapsed_ms = round((perf_counter()-started)*1000)
                    if result.degraded and result.degraded not in page.degraded:
                        page.degraded.append(result.degraded)
                    if result.error:
                        page.error = result.error
                        job.error = result.error.copy()
                    self.progress(job)
                # No await between cancellation check and publication: old workers
                # never write public assets after a force replacement starts.
                if job.status == 'cancelled':
                    return
                page.story_url, page.video_url = session.publish()
                page.status = 'partial' if page.degraded else 'done'
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception('member3 page failed: job=%s page=%s', job.job_id, page.page_id)
                error = {'code': int(exc.code), 'msg': exc.msg} if isinstance(exc, (APIError, AppError)) else {
                    'code': 9001, 'msg': '成员3本地产物生成失败'}
                page.error = error
                job.error = error.copy()
                page.status = 'blocked' if error['code'] == 3004 else 'failed'
                page.story_url = page.video_url = None
                if page.status == 'blocked':
                    page.degraded.clear()
                if all(stage.status != 'running' for stage in page.stages):
                    # Final publication is part of render acceptance. A failed
                    # final gate must not leave an all-green stage list.
                    page.stages[-1].status = 'failed'
                for stage in page.stages:
                    if stage.status == 'running':
                        stage.status = 'failed'
                        stage.elapsed_ms = round((perf_counter()-started)*1000)
                    elif stage.status == 'pending':
                        stage.status = 'skipped'
                self.progress(job)
            finally:
                if session is not None:
                    try:
                        receipt = (session.finalize_m1(
                            'cancelled' if flag.is_set() else page.status, page.error)
                            if getattr(session, 'm1', None) is not None else None)
                        if receipt is not None:
                            key = (job.job_id, page.page_id)
                            self.m1_receipts[key] = receipt
                            if receipt['budget_release_error'] or receipt['submission_state'] == 'UNKNOWN':
                                self.m1_reconciliation[key] = receipt.copy()
                            logger.info('M1 internal receipt: %s', json.dumps(receipt, ensure_ascii=False))
                            audit = self.storage.root / '.member3' / 'm1-reconciliation.jsonl'
                            try:
                                with audit.open('a', encoding='utf-8') as handle:
                                    handle.write(json.dumps({**receipt, 'job_id': job.job_id,
                                                             'page_id': page.page_id}, ensure_ascii=False)+'\n')
                            except OSError:
                                logger.exception('M1 audit persistence failed; receipt retained for reconciliation')
                        # No worker can still access this session: work drains the
                        # same real Future even across repeated cancellation. Do
                        # not register a new executor job during shutdown cleanup.
                        session.close()
                    except OSError:
                        logger.exception('member3 workspace cleanup failed: job=%s page=%s',
                                         job.job_id, page.page_id)
        job.status = ('done' if all(p.status == 'done' for p in job.pages) else
                      'partial_failed' if any(p.status in ('done', 'partial') for p in job.pages) else 'failed')
        self.progress(job)
