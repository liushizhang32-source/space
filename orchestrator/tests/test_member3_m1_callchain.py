"""CI_ONLY: real HTTP Jobs chain with the hash-locked M1 V0.8.1 offline kit."""
import hashlib
import io
import json
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orchestrator.core.config import Settings
from orchestrator.main import create_app
from orchestrator.services import member3_adapter as adapter
from orchestrator.vendor.member3_v116.agents.generation import pipeline
from orchestrator.vendor.member3_v116.agents.generation.errors import AppError, ErrorCode, StoryInputError
from orchestrator.vendor.member3_v116.agents.generation.m1_generation import GenerationDenied
from orchestrator.vendor.member3_v116.agents.generation.m1_pipeline import open_session
from orchestrator.vendor.member3_v116.tests import m1_offline_rig as fixtures


@pytest.fixture
def chain(tmp_path, monkeypatch):
    image = io.BytesIO()
    Image.new('RGB', (96, 128), 'white').save(image, format='PNG')
    monkeypatch.setattr(fixtures, 'IMAGE', image.getvalue())
    rig = fixtures.make_rig(tmp_path/'m1')
    sessions = []

    def factory(*, page_id, job_id, request_id):
        node = rig.page(3)
        consumer = rig.consumer_for(3)
        session = open_session(consumer, page_id=page_id, request_id=request_id,
            amount=1000, c1=node.c1, c2=node.c2, size=(96, 128), image=rig.image,
            final_messages=[{'role': 'user', 'content': '为这一页生成儿童故事'}])
        sessions.append(session)
        return session

    app = create_app(Settings(data_dir=tmp_path/'data', generation_backend='member3',
        asset_base_url='http://testserver', queue_delay=.001, stage_delay=.001,
        ffmpeg_path=os.environ['FFMPEG_PATH'], ffprobe_path=os.environ['FFPROBE_PATH']),
        m1_session_factory=factory)
    with TestClient(app) as client:
        response = client.post('/api/v1/capture', data={'book_id':'book01','page_no':3},
            files={'image':('page.png',rig.image,'image/png')})
        assert response.json()['code'] == 0
        yield client, app.state.jobs, rig, sessions


def start(client, force=False):
    doc = client.post('/api/v1/generate', json={'page_ids':['book01_p03'],
        'age_level':'3-6','force':force}).json()
    assert doc['code'] == 0, doc
    return doc['data']['job_id']


def terminal(client, jid):
    deadline = time.monotonic()+40
    while time.monotonic() < deadline:
        doc = client.get('/api/v1/jobs/'+jid).json()['data']
        if doc['status'] in ('done','failed','partial_failed','cancelled'):
            return doc
        time.sleep(.005)
    pytest.fail('job did not finish')


def test_http_chain_calls_B_once_and_never_rewrites_submitted_story(chain, monkeypatch):
    client,jobs,rig,sessions=chain
    counts={'run':0,'builder':0,'tts':0}
    run,builder,synth=pipeline.run_page,pipeline.build_page_story,adapter.TTSClient.synthesize
    def run_spy(*args,**kwargs):
        counts['run']+=1;assert kwargs['m1'] is sessions[0]
        return run(*args,**kwargs)
    def build_spy(*args,**kwargs):
        counts['builder']+=1;return builder(*args,**kwargs)
    def synth_spy(*args,**kwargs):
        counts['tts']+=1;return synth(*args,**kwargs)
    monkeypatch.setattr(pipeline,'run_page',run_spy)
    monkeypatch.setattr(pipeline,'build_page_story',build_spy)
    monkeypatch.setattr(adapter.TTSClient,'synthesize',synth_spy)
    monkeypatch.setattr(adapter,'build_page_story',lambda *a,**k:pytest.fail('legacy builder executed'))
    jid=start(client);doc=terminal(client,jid)
    assert doc['status']=='done',doc
    raw=(jobs.storage.root/'json/book01_p03_story.json').read_bytes()
    story=json.loads(raw)
    assert counts=={'run':1,'builder':1,'tts':len(story['segments'])}
    receipt=jobs.m1_receipts[(jid,'book01_p03')]
    assert hashlib.sha256(raw).hexdigest()==receipt['m1_result_sha256']==sessions[0].attempt.result_sha256
    assert receipt['generation_mode']=='m1_authorized'
    assert rig.authority.totals()['held']==1000
    assert 'budget_release_error' not in json.dumps(doc)


def test_video_blocked_keeps_attempt_and_unknown_budget(chain,monkeypatch):
    client,jobs,rig,sessions=chain
    def blocked(*args,**kwargs):raise AppError(ErrorCode.SAFETY_BLOCKED,'blocked')
    monkeypatch.setattr(adapter,'compose_video',blocked)
    jid=start(client);doc=terminal(client,jid)
    assert doc['pages'][0]['status']=='blocked'
    receipt=jobs.m1_receipts[(jid,'book01_p03')]
    assert receipt['m1_attempt_id']==sessions[0].attempt_id
    assert receipt['generation_mode']=='m1_authorized'
    assert receipt['submission_state']=='UNKNOWN'
    assert receipt['m1_result_sha256']
    assert rig.authority.totals()['held']==1000
    assert not (jobs.storage.root/'json/book01_p03_story.json').exists()


def test_release_failure_survives_business_error_and_is_audited(chain,monkeypatch):
    client,jobs,rig,sessions=chain
    original=jobs.adapter.m1_session_factory
    def factory(**kw):
        s=original(**kw)
        def broken(*a):raise GenerationDenied('CORRUPT')
        monkeypatch.setattr(s.consumer,'cancel',broken)
        return s
    def fail(*a,**kw):raise StoryInputError('fixture failure')
    jobs.adapter.m1_session_factory=factory
    monkeypatch.setattr(pipeline,'build_page_story',fail)
    jid=start(client);doc=terminal(client,jid)
    assert doc['status']=='failed'
    key=(jid,'book01_p03');receipt=jobs.m1_receipts[key]
    assert receipt['error']
    assert receipt['budget_release_error']['m1_code']=='CORRUPT'
    assert jobs.m1_reconciliation[key]['budget_release_error']==receipt['budget_release_error']
    audit=(jobs.storage.root/'.member3/m1-reconciliation.jsonl').read_text(encoding='utf-8')
    assert 'CORRUPT' in audit
    assert 'budget_release_error' not in json.dumps(doc)
    assert rig.authority.totals()['held']==1000


def test_submit_response_lost_retains_unknown_and_never_cancels(chain,monkeypatch):
    client,jobs,rig,sessions=chain
    original=jobs.adapter.m1_session_factory
    def factory(**kw):
        s=original(**kw);submit=s.consumer.submit
        def ambiguous(*args):
            submit(*args)
            raise RuntimeError('response lost')
        monkeypatch.setattr(s.consumer,'submit',ambiguous)
        monkeypatch.setattr(s.consumer,'cancel',lambda *a:pytest.fail('UNKNOWN cancelled'))
        return s
    jobs.adapter.m1_session_factory=factory
    jid=start(client);doc=terminal(client,jid)
    assert doc['status']=='failed'
    key=(jid,'book01_p03')
    assert jobs.m1_reconciliation[key]['submission_state']=='UNKNOWN'
    assert not sessions[0].released
    assert rig.authority.totals()['held']==1000
    assert not (jobs.storage.root/'json/book01_p03_story.json').exists()
    assert len(sessions)==1


@pytest.mark.parametrize('force',[False,True])
def test_cancel_or_force_during_worker_cannot_publish(chain,monkeypatch,force):
    client,jobs,rig,sessions=chain
    entered,release=threading.Event(),threading.Event()
    original=pipeline.build_page_story
    def blocked(*args,**kw):
        entered.set();assert release.wait(10)
        return original(*args,**kw)
    monkeypatch.setattr(pipeline,'build_page_story',blocked)
    jid=start(client);assert entered.wait(10)
    if force:
        replacement=start(client,force=True)
    else:
        client.portal.call(jobs.tasks[jid].cancel)
    release.set()
    client.portal.call(lambda: _drain(jobs.tasks[jid]))
    receipt=jobs.m1_receipts[(jid,'book01_p03')]
    assert receipt['status']=='cancelled'
    assert sessions[0].released
    assert not sessions[0].submission_started
    # No old publication, even if a replacement is still executing.
    if force:
        terminal(client,replacement)
        assert jobs.m1_receipts[(jid,'book01_p03')]['m1_result_sha256'] is None
    else:
        assert not (jobs.storage.root/'json/book01_p03_story.json').exists()


async def _drain(task):
    import asyncio
    await asyncio.gather(task,return_exceptions=True)


def test_story_mutated_after_submit_is_never_published(chain,monkeypatch):
    client,jobs,rig,sessions=chain
    original=adapter.Member3Session.publish
    def tampered(s):
        path=s.settings.json_dir/f'{s.page_id}_story.json'
        path.write_bytes(path.read_bytes()+b' ')
        return original(s)
    monkeypatch.setattr(adapter.Member3Session,'publish',tampered)
    jid=start(client);doc=terminal(client,jid)
    assert doc['status']=='failed'
    assert not (jobs.storage.root/'json/book01_p03_story.json').exists()
    assert jobs.m1_receipts[(jid,'book01_p03')]['m1_result_sha256']
    assert rig.authority.totals()['held']==1000


def test_local_mode_does_not_request_M1(chain):
    client,jobs,rig,sessions=chain
    jobs.adapter.m1_session_factory=None
    jid=start(client);doc=terminal(client,jid)
    assert doc['status']=='done'
    assert not sessions and not jobs.m1_receipts


def test_receipt_serializes_every_internal_field():
    r=pipeline.PageRunResult('book01_p03',3,'failed',generation_mode='m1_authorized',
        error={'code':1005,'msg':'denied'},budget_release_error={'m1_code':'CORRUPT'},
        m1_attempt_id='a',m1_result_sha256='b')
    data=r.to_dict()
    for key in ('generation_mode','error','status','budget_release_error','m1_attempt_id','m1_result_sha256'):
        assert data[key]==getattr(r,key)


def test_tts_failure_degrades_once_without_changing_committed_story(chain,monkeypatch):
    client,jobs,rig,sessions=chain
    calls=[]
    # Use the existing public TTS error code without a real provider.
    from orchestrator.vendor.member3_v116.agents.generation.errors import TTSUnavailable
    def unavailable(self,text):
        calls.append(text);raise TTSUnavailable('fixture TTS failure')
    monkeypatch.setattr(adapter.TTSClient,'synthesize',unavailable)
    jid=start(client);doc=terminal(client,jid)
    assert doc['pages'][0]['status']=='partial',doc
    assert 'no_audio' in doc['pages'][0]['degraded']
    raw=(jobs.storage.root/'json/book01_p03_story.json').read_bytes()
    assert len(calls)==len(json.loads(raw)['segments'])
    assert hashlib.sha256(raw).hexdigest()==sessions[0].attempt.result_sha256


def test_cancel_after_submit_keeps_unknown_and_cannot_publish(chain,monkeypatch):
    client,jobs,rig,sessions=chain
    entered,release=threading.Event(),threading.Event()
    original=adapter.compose_video
    def block(*args,**kwargs):
        entered.set();assert release.wait(10)
        return original(*args,**kwargs)
    monkeypatch.setattr(adapter,'compose_video',block)
    jid=start(client);assert entered.wait(10)
    client.portal.call(jobs.tasks[jid].cancel);release.set()
    client.portal.call(lambda:_drain(jobs.tasks[jid]))
    receipt=jobs.m1_receipts[(jid,'book01_p03')]
    assert receipt['status']=='cancelled'
    assert receipt['submission_state']=='UNKNOWN'
    assert receipt['m1_result_sha256']
    assert not sessions[0].released
    assert rig.authority.totals()['held']==1000
    assert not (jobs.storage.root/'json/book01_p03_story.json').exists()


def test_B_video_blocked_return_retains_internal_attempt(chain,monkeypatch,tmp_path):
    client,jobs,rig,sessions=chain
    s=jobs.adapter.m1_session_factory(page_id='book01_p03',job_id='direct',request_id='direct:page')
    config=adapter.MemberSettings(data_dir=tmp_path/'direct',tts_engine='silent',
        ffmpeg_path=os.environ['FFMPEG_PATH'],ffprobe_path=os.environ['FFPROBE_PATH'])
    config.ensure_dirs()
    def blocked(*args,**kwargs):raise AppError(ErrorCode.SAFETY_BLOCKED,'fixture')
    monkeypatch.setattr(pipeline,'compose_video',blocked)
    result=pipeline.run_page('book01_p03','3-6',config,m1=s)
    data=result.to_dict()
    assert data['status']=='blocked' and data['generation_mode']=='m1_authorized'
    assert data['m1_attempt_id']==s.attempt_id
    assert data['m1_result_sha256']==s.attempt.result_sha256
    assert data['budget_release_error'] is None
