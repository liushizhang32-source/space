import asyncio
import concurrent.futures
import threading

import pytest

from orchestrator.api.models import GenerateRequest
from orchestrator.core.config import Settings
from orchestrator.core.errors import APIError
from orchestrator.services.storage import Storage
from orchestrator.services import member3_adapter as adapter
from orchestrator.services.member3_jobs import Member3Jobs


@pytest.mark.parametrize('repeat', [0, 3])
def test_force_repeated_cancel_and_shared_shutdown(tmp_path, repeat):
    async def scenario():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        release, finished = threading.Event(), threading.Event()
        closed = []
        class Session:
            def step(self, *args):
                loop.call_soon_threadsafe(entered.set)
                try:
                    assert release.wait(10)
                    return adapter.Outcome()
                finally:
                    finished.set()
            def close(self):
                assert finished.is_set(), 'cleanup raced with the executor thread'
                closed.append(1)
        settings = Settings(data_dir=tmp_path, generation_backend='member3', queue_delay=0, stage_delay=0)
        storage = Storage(settings)
        storage.pages['book01_p03'] = {'page_no':3}
        jobs = Member3Jobs(storage)
        jobs.adapter.session = lambda *args: Session()
        request = GenerateRequest(page_ids=['book01_p03'], age_level='3-6')
        first = jobs.create(request).job_id
        callers = []
        try:
            await asyncio.wait_for(entered.wait(), 3)
            real_future = next(iter(jobs._workers))
            assert isinstance(real_future, concurrent.futures.Future)
            flag = jobs._cancel_flags[jobs.tasks[first]]
            object.__setattr__(settings, 'queue_delay', 10)
            second = jobs.create(request.model_copy(update={'force':True})).job_id
            assert await asyncio.to_thread(flag.wait, 3)
            for _ in range(repeat):
                jobs.tasks[first].cancel()
                await asyncio.sleep(0)  # scheduler yield, not a timed cleanup delay
            ready = asyncio.Event()
            async def close_caller():
                ready.set()
                await jobs.close()
            callers.append(asyncio.create_task(close_caller()))
            await ready.wait()
            shutdown = jobs._shutdown_task
            callers.append(asyncio.create_task(jobs.close()))
            for _ in range(repeat):
                callers[0].cancel()
                await asyncio.sleep(0)
            assert jobs._shutdown_task is shutdown
            assert not shutdown.done() and not real_future.done() and not real_future.cancelled()
            assert not closed
            with pytest.raises(APIError, match='正在关闭'):
                jobs.create(request)
            with pytest.raises(asyncio.CancelledError):
                await jobs.work(lambda: pytest.fail('new worker registered during shutdown'))
            assert jobs.get(first).status == 'cancelled'
        finally:
            release.set()
            await asyncio.gather(*callers, return_exceptions=True)
            await jobs.close()
        assert finished.is_set() and closed == [1]
        assert jobs.get(second).status == 'cancelled'
        assert jobs._shutdown_task is shutdown and not jobs._workers
        await jobs.close()
        assert closed == [1]
    asyncio.run(scenario())


@pytest.mark.parametrize('phase', ['settings', 'directories'])
@pytest.mark.parametrize('cleanup_fails', [False, True, 'runtime'])
def test_initialization_failure_preserves_original_and_other_session(tmp_path, monkeypatch, caplog, phase, cleanup_fails):
    storage = Storage(Settings(data_dir=tmp_path))
    bridge = adapter.Member3Adapter(storage)
    other = bridge.session('book01_p03', 'job_OTHER')
    marker = other.root/'keep.txt'
    marker.write_text('other session', encoding='utf-8')
    original = ValueError('original initialization failure')
    def fail(*args, **kwargs):raise original
    if phase == 'settings':monkeypatch.setattr(adapter, 'MemberSettings', fail)
    else:monkeypatch.setattr(adapter.MemberSettings, 'ensure_dirs', fail)
    real_rmtree = adapter.shutil.rmtree
    targets = []
    def cleanup(path):
        targets.append(path)
        assert path != other.root and path.parent == other.root.parent
        if cleanup_fails == 'runtime':raise RuntimeError('MOCK cleanup runtime failure')
        if cleanup_fails:raise PermissionError('MOCK cleanup denied')
        real_rmtree(path)
    monkeypatch.setattr(adapter.shutil, 'rmtree', cleanup)
    with pytest.raises(ValueError) as caught:
        bridge.session('book01_p03', 'job_BROKEN')
    assert caught.value is original and len(targets) == 1
    assert marker.read_text(encoding='utf-8') == 'other session'
    assert other.root.parent.exists()
    assert targets[0].exists() == bool(cleanup_fails)
    if cleanup_fails:assert 'initialization cleanup failed' in caplog.text


def test_cancelled_worker_exception_is_drained(tmp_path):
    async def scenario():
        jobs = Member3Jobs(Storage(Settings(data_dir=tmp_path)))
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def work():
            entered.set()
            try:
                assert release.wait(5)
                raise OSError('MOCK worker failure while cancelled')
            finally:finished.set()
        task = asyncio.create_task(jobs.work(work))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel()
            flag = jobs._cancel_flags[task]
            assert await asyncio.to_thread(flag.wait, 3)
            task.cancel()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):await task
        assert finished.is_set() and not jobs._workers
        await jobs.close()
    asyncio.run(scenario())


def test_session_cleanup_is_idempotent(tmp_path):
    bridge = adapter.Member3Adapter(Storage(Settings(data_dir=tmp_path)))
    session = bridge.session('book01_p03', 'job_ONCE')
    session.close()
    session.close()
    assert not session.root.exists() and session.root.parent.exists()
