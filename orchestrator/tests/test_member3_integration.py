import io
import json
import re
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orchestrator.core.config import Settings
from orchestrator.main import create_app
from orchestrator.schemas.story import StoryData
from orchestrator.services import member3_adapter as bridge
from orchestrator.vendor.member3_v116.agents.generation.errors import AppError, ErrorCode, VideoPublishError


@pytest.fixture
def client(tmp_path):
    import os
    app = create_app(Settings(data_dir=tmp_path, asset_base_url='http://testserver',
        generation_backend='member3', queue_delay=.02, stage_delay=.01,
        ffmpeg_path=os.environ['FFMPEG_PATH'], ffprobe_path=os.environ['FFPROBE_PATH']))
    with TestClient(app, raise_server_exceptions=False) as session:
        yield session


def envelope(response):
    assert response.status_code == 200
    doc = response.json()
    assert set(doc) == {'code', 'msg', 'data', 'trace_id'}
    assert re.fullmatch(r'tr_[0-9A-HJKMNP-TV-Z]{26}', doc['trace_id'])
    assert response.headers['X-Trace-ID'] == doc['trace_id']
    assert doc['code'] == 0, doc
    return doc['data']


def upload(client, page=3):
    data = io.BytesIO()
    Image.new('RGB', (96, 128), 'white').save(data, format='PNG')
    return envelope(client.post('/api/v1/capture', data={'page_no':page, 'book_id':'book01'},
        files={'image':('page.png', data.getvalue(), 'image/png')}))


def start(client, pages=None, force=False):
    return envelope(client.post('/api/v1/generate', json={'page_ids':pages or ['book01_p03'],
        'age_level':'3-6', 'force':force}))['job_id']


def terminal(client, jid):
    history = []
    deadline = time.monotonic()+35
    while time.monotonic() < deadline:
        doc = envelope(client.get('/api/v1/jobs/'+jid))
        history.append(doc)
        if doc['status'] in ('done', 'failed', 'partial_failed', 'cancelled'):
            return doc, history
        time.sleep(.01)
    pytest.fail('job did not reach a terminal state')


def run(client):
    upload(client)
    return terminal(client, start(client))[0]


def assert_private_clean(client):
    assert list((client.app.state.storage.root/'.member3').iterdir()) == []


def test_full_member3_chain_and_public_files(client):
    capture = upload(client)
    assert client.get(capture['preview_url']).status_code == 200
    jid = start(client)
    assert start(client) == jid
    job, history = terminal(client, jid)
    assert job['status'] == 'done' and job['progress'] == 100
    assert [h['progress'] for h in history] == sorted(h['progress'] for h in history)
    assert any(h['status'] == 'running' for h in history)
    page = job['pages'][0]
    assert [s['status'] for s in page['stages']] == ['ok']*5
    assert page['degraded'] == [] and page['error'] is None
    story = StoryData.model_validate(client.get(page['story_url']).json())
    assert story.model.name == 'mock-template'
    assert all(s.scene and s.duration_source == 'tts' and s.audio_url for s in story.segments)
    assert all(oid.startswith(story.page_id+'_o') for s in story.segments for oid in s.highlight_object_ids)
    settings = client.app.state.jobs.adapter.storage.settings
    media_settings = bridge.MemberSettings(ffmpeg_path=settings.ffmpeg_path, ffprobe_path=settings.ffprobe_path)
    root = settings.data_dir
    for segment in story.segments:
        assert client.get(segment.audio_url).status_code == 200
        path = root/'audios'/segment.audio_url.rsplit('/', 1)[-1]
        assert bridge.validate_audio(path, media_settings, deep=True).ok
    assert client.get(page['video_url']).headers['content-type'] == 'video/mp4'
    assert bridge.validate_video(root/'videos/book01_p03_video.mp4', media_settings, deep=True).ok
    assert_private_clean(client)


@pytest.mark.parametrize('change,code', [('blocked',3004), ('bad_bbox',1002), ('cross_page',1002), ('no_content',3001)])
def test_visual_boundary_stops_downstream(client, change, code, monkeypatch):
    factory = bridge.fixed_visual
    def fixture(stage, page):
        doc = factory(stage, page)
        if stage == 'vlm':
            if change == 'blocked':doc['safety']['pass'] = False
            if change == 'bad_bbox':doc['objects'][0]['bbox'][2] = page['image_width']+1
            if change == 'cross_page':doc['objects'][0]['object_id'] = 'book01_p04_o01'
            if change == 'no_content':doc.update(status='empty', objects=[], description='', scene_tags=[])
        elif change == 'no_content':doc.update(status='empty', text_blocks=[], page_confidence=0)
        return doc
    client.app.state.jobs.adapter.fixture_factory = fixture
    monkeypatch.setattr(bridge, 'compose_video', lambda *a, **k: pytest.fail('render must not run'))
    job = run(client)
    assert job['status'] == 'failed' and job['error']['code'] == code
    page = job['pages'][0]
    assert page['status'] == ('blocked' if code == 3004 else 'failed')
    assert page['story_url'] is None and page['video_url'] is None
    assert page['stages'][-1]['status'] == 'skipped'
    assert_private_clean(client)


def test_wordless_story_fallback(client):
    def fixture(stage, page):
        doc = bridge.fixed_visual(stage, page)
        if stage == 'ocr':doc.update(status='empty', text_blocks=[], page_confidence=0)
        return doc
    client.app.state.jobs.adapter.fixture_factory = fixture
    job = run(client)
    assert job['status'] == 'done'
    story = StoryData.model_validate(client.get(job['pages'][0]['story_url']).json())
    assert all(s.scene for s in story.segments)


@pytest.mark.parametrize('failure', ['timeout', 'html'])
def test_http_tts_failure_degrades_without_invalid_audio(client, failure, monkeypatch):
    from orchestrator.vendor.member3_v116.agents.generation.tts import engine
    class Response:
        status = 200
        headers = {'Content-Type':'text/html'}
        body = b'<html>MOCK upstream failure</html>'
        def read(self, *args):
            body, self.body = self.body, b''
            return body
        def close(self):pass
        def __enter__(self):return self
        def __exit__(self, *args):self.close()
    def request(*a, **k):
        if failure == 'timeout':raise TimeoutError('MOCK timeout')
        return Response()
    monkeypatch.setattr(engine.urllib.request, 'urlopen', request)
    def factory(settings):
        return bridge.TTSClient(settings.replace(tts_engine='http', tts_http_url='http://127.0.0.1:9/mock'))
    client.app.state.jobs.adapter.client_factory = factory
    job = run(client)
    assert job['status'] == 'partial_failed'
    page = job['pages'][0]
    assert page['status'] == 'partial' and page['degraded'] == ['no_audio']
    assert page['stages'][3]['status'] == 'failed' and page['stages'][4]['status'] == 'ok'
    assert page['error']['code'] == (2002 if failure == 'timeout' else 3008)
    story = client.get(page['story_url']).json()
    assert all(s['duration_source'] == 'estimate' and not s.get('audio_url') for s in story['segments'])
    assert list((client.app.state.storage.root/'audios').iterdir()) == []
    assert page['video_url']
    assert_private_clean(client)


@pytest.mark.parametrize('where', ['tts', 'video'])
def test_downstream_safety_rejection_is_not_degraded(client, where, monkeypatch):
    def blocked(*a, **k):raise AppError(ErrorCode.SAFETY_BLOCKED, 'MOCK safety rejection')
    if where == 'tts':
        client.app.state.jobs.adapter.client_factory = lambda s: type('Blocked', (), {'synthesize':blocked})()
        monkeypatch.setattr(bridge, 'compose_video', lambda *a, **k: pytest.fail('blocked TTS must stop render'))
    else:
        monkeypatch.setattr(bridge, 'compose_video', blocked)
    job = run(client)
    page = job['pages'][0]
    assert job['status'] == 'failed' and page['status'] == 'blocked'
    assert page['error']['code'] == 3004 and page['degraded'] == []
    assert page['story_url'] is None and page['video_url'] is None
    assert list((client.app.state.storage.root/'audios').iterdir()) == []
    assert_private_clean(client)


@pytest.mark.parametrize('failure', ['missing_image', 'render', 'corrupt_video'])
def test_missing_or_bad_artifact_is_not_published(client, failure, monkeypatch):
    upload(client)
    root = client.app.state.storage.root
    if failure == 'missing_image':(root/'uploads/book01_p03_orig.png').unlink()
    elif failure == 'render':
        def bad(*a, **k):raise AppError(ErrorCode.VIDEO_FAILED, 'MOCK encoder failure')
        monkeypatch.setattr(bridge, 'compose_video', bad)
    else:
        original = bridge.compose_video
        def bad(pid, story, settings):
            result = original(pid, story, settings)
            (settings.videos_dir/f'{pid}_video.mp4').write_bytes(b'not an MP4')
            return result
        monkeypatch.setattr(bridge, 'compose_video', bad)
    job, _ = terminal(client, start(client))
    page = job['pages'][0]
    assert page['video_url'] is None
    assert not (root/'videos/book01_p03_video.mp4').exists()
    if failure == 'missing_image':assert job['status'] == 'failed' and page['error']['code'] == 1003
    else:assert job['status'] == 'partial_failed' and page['degraded'] == ['no_video'] and page['error']['code'] == 3007
    assert_private_clean(client)


def test_recovery_error_preserves_private_backups_and_reference(client, monkeypatch):
    def bad(pid, story, settings):
        backup = settings.videos_dir/'MOCK-recovery.bak'
        backup.write_bytes(b'old valid bytes')
        raise VideoPublishError(detail=str(backup))
    monkeypatch.setattr(bridge, 'compose_video', bad)
    job = run(client)
    assert job['status'] == 'partial_failed' and job['pages'][0]['video_url'] is None
    root = client.app.state.storage.root
    assert len(list((root/'.member3').rglob('MOCK-recovery.bak'))) == 1
    event = json.loads((root/'logs/book01_p03_publish_errors.jsonl').read_text(encoding='utf-8').splitlines()[0])
    assert Path(event['detail']).exists()
    assert event['recovery_id'].startswith('rec_')
    assert 'MOCK-recovery.bak' not in json.dumps(job)


def test_force_during_thread_work_cannot_publish_stale_result(client, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = bridge.build_page_story
    calls = []
    def slow(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
        return original(*a, **k)
    monkeypatch.setattr(bridge, 'build_page_story', slow)
    upload(client)
    first = start(client)
    try:
        assert entered.wait(5)
        before = time.monotonic()
        second = start(client, force=True)
        assert time.monotonic()-before < 1
        assert envelope(client.get('/api/v1/jobs/'+first))['status'] == 'cancelled'
    finally:
        release.set()
    assert terminal(client, second)[0]['status'] == 'done'
    deadline = time.monotonic()+5
    while list((client.app.state.storage.root/'.member3').iterdir()) and time.monotonic() < deadline:time.sleep(.01)
    assert_private_clean(client)
    assert envelope(client.get('/api/v1/jobs/'+first))['status'] == 'cancelled'


def test_batch_failure_does_not_prevent_later_page(client):
    def fixture(stage, page):
        doc = bridge.fixed_visual(stage, page)
        if stage == 'vlm' and page['page_no'] == 1:doc['safety']['pass'] = False
        return doc
    client.app.state.jobs.adapter.fixture_factory = fixture
    upload(client, 1)
    upload(client, 2)
    job, _ = terminal(client, start(client, ['book01_p02','book01_p01']))
    assert job['status'] == 'partial_failed' and job['progress'] == 100
    assert [p['status'] for p in job['pages']] == ['blocked','done']
    assert [p['page_no'] for p in job['pages']] == [1,2]


def test_unknown_backend_rejected():
    with pytest.raises(ValueError, match='GENERATION_BACKEND'):
        Settings(generation_backend='unknown')


def test_configured_content_safety_stops_tts(client, monkeypatch):
    object.__setattr__(client.app.state.storage.settings, 'safety_blocklist', ('小兔子',))
    client.app.state.jobs.adapter.client_factory = lambda s: pytest.fail('safety failure must stop TTS')
    job = run(client)
    assert job['status'] == 'failed' and job['pages'][0]['status'] == 'blocked'
    assert job['error']['code'] == 3004
    assert_private_clean(client)


def test_corrupt_audio_is_never_published(client):
    class CorruptClient:
        def __init__(self, settings):self.client = bridge.TTSClient(settings)
        def synthesize(self, text):
            call = self.client.synthesize(text)
            call.audio_path.write_bytes(b'MOCK broken audio')
            return call
    client.app.state.jobs.adapter.client_factory = CorruptClient
    job = run(client)
    page = job['pages'][0]
    assert job['status'] == 'partial_failed' and page['degraded'] == ['no_audio']
    assert page['error']['code'] == 3008 and page['video_url']
    assert list((client.app.state.storage.root/'audios').iterdir()) == []
    assert_private_clean(client)


def test_audio_lost_before_publication_fails_without_dangling_url(client, monkeypatch):
    original = bridge.compose_video
    def lose_audio(pid, story, settings):
        result = original(pid, story, settings)
        next(settings.audios_dir.glob('*.mp3')).unlink()
        return result
    monkeypatch.setattr(bridge, 'compose_video', lose_audio)
    job = run(client)
    page = job['pages'][0]
    assert job['status'] == 'failed' and page['error']['code'] == 3008
    assert page['stages'][-1]['status'] == 'failed'
    assert page['story_url'] is None and page['video_url'] is None
    assert list((client.app.state.storage.root/'json').iterdir()) == []
    assert_private_clean(client)


def test_final_publication_safety_error_preserves_blocked_semantics(client, monkeypatch):
    def blocked(*a, **k):
        raise AppError(ErrorCode.SAFETY_BLOCKED, 'MOCK final safety rejection')
    monkeypatch.setattr(bridge.Member3Session, 'publish', blocked)
    job = run(client)
    page = job['pages'][0]
    assert job['status'] == 'failed' and page['status'] == 'blocked'
    assert page['error']['code'] == 3004
    assert page['stages'][-1]['status'] == 'failed'
    assert page['story_url'] is None and page['video_url'] is None
    assert list((client.app.state.storage.root/'json').iterdir()) == []
    assert_private_clean(client)
