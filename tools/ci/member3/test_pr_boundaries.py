"""Review-only fault probes. Source files are never patched on disk."""
import asyncio
import json
import threading
from pathlib import Path

import pytest

from orchestrator.api.models import GenerateRequest
from orchestrator.core.config import Settings
from orchestrator.services.storage import Storage
from orchestrator.services.member3_adapter import Member3Adapter, MemberSettings, Outcome
from orchestrator.services.member3_jobs import Member3Jobs

ROOT = Path(__import__('os').environ['CI_RUN_DIR'])


def test_force_then_shutdown_does_not_cleanup_a_running_worker(tmp_path):
    entered, release, finished, closed = (threading.Event() for _ in range(4))
    class Session:
        def step(self, *args):
            entered.set()
            try:
                assert release.wait(5), 'review probe must release the thread'
                return Outcome()
            finally:
                finished.set()
        def close(self):
            closed.set()

    async def scenario():
        settings = Settings(data_dir=tmp_path, generation_backend='member3', queue_delay=0, stage_delay=0)
        storage = Storage(settings)
        storage.pages['book01_p03'] = {'page_no':3}
        jobs = Member3Jobs(storage)
        jobs.adapter.session = lambda *args: Session()
        request = GenerateRequest(page_ids=['book01_p03'], age_level='3-6')
        original = jobs.create(request).job_id
        close_task = None
        observation = {}
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            # Keep the replacement queued; its worker cannot affect our observation.
            object.__setattr__(settings, 'queue_delay', 10)
            replacement = jobs.create(request.model_copy(update={'force':True})).job_id
            await asyncio.sleep(.03)
            close_task = asyncio.create_task(jobs.close())
            deadline = asyncio.get_running_loop().time()+1
            while not closed.is_set() and asyncio.get_running_loop().time()<deadline:
                await asyncio.sleep(.01)
            observation = {'cleanup_before_worker_finished':closed.is_set() and not finished.is_set(),
                           'shutdown_returned_before_worker_finished':close_task.done() and not finished.is_set(),
                           'original_status':jobs.get(original).status,
                           'replacement_created':replacement != original}
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 3)
            if close_task:
                await asyncio.gather(close_task, return_exceptions=True)
            else:
                await jobs.close()
            await asyncio.gather(*jobs.tasks.values(), return_exceptions=True)
        (ROOT/'logs/repeated-cancel-observation.json').write_text(json.dumps(observation, indent=2), encoding='utf-8')
        return observation

    result = asyncio.run(scenario())
    assert not result['cleanup_before_worker_finished'], 'force + shutdown cleaned the session while its thread was still running'


def test_session_initialization_failure_cleans_its_new_directory(tmp_path, monkeypatch):
    storage = Storage(Settings(data_dir=tmp_path, generation_backend='member3'))
    adapter = Member3Adapter(storage)
    def fail(*args):
        raise PermissionError('MOCK workspace initialization failure')
    monkeypatch.setattr(MemberSettings, 'ensure_dirs', fail)
    with pytest.raises(PermissionError):
        adapter.session('book01_p03', 'job_REVIEW')
    leftovers = list((tmp_path/'.member3').iterdir())
    (ROOT/'logs/initialization-observation.json').write_text(
        json.dumps({'leftover_directories':len(leftovers)}, indent=2), encoding='utf-8')
    assert not leftovers, 'session constructor left an unowned private directory after ensure_dirs failed'
