"""Approved UNKNOWN decision: deny until trusted M1 confirms terminal settlement."""
import hashlib
import json
import threading
import pytest
from orchestrator.tests.test_member3_m1_callchain import chain, start, terminal, _drain
from orchestrator.services import member3_adapter as adapter
from orchestrator.vendor.member3_v116.agents.generation.m1_generation import M1GenerationConsumer
from orchestrator.vendor.member3_v116.agents.generation.m1_pipeline import open_session
from orchestrator.vendor.member3_v116.tests import m1_offline_rig as fixtures


def test_unknown_refuses_replacement_then_trusted_terminal_allows_new_job(chain,monkeypatch):
    client,jobs,rig,sessions=chain
    node=rig.page(3)
    rig.authority.finish_stage(node.identity,'m3-offline-fixture',outcome='SUCCEEDED',terminal_confirmed=True)
    def provider(*,page_id,job_id,request_id):
        record,created=rig.fences.begin(job_id,page_id,force=True)
        assert created
        identity=rig.fences.attempt(record)
        rig.authority.reserve_stage(identity,'vlm','closure-offline-fixture')
        rig.authority.finish_stage(identity,'closure-offline-fixture',outcome='SUCCEEDED',terminal_confirmed=True)
        c1,c2=fixtures._snapshots(identity,3)
        consumer=M1GenerationConsumer(rig.authority,rig.gate,rig.fences,record,service_token=rig.service_token)
        s=open_session(consumer,page_id=page_id,request_id=request_id,amount=1000,c1=c1,c2=c2,
            size=(96,128),image=rig.image,final_messages=[{'role':'user','content':'offline fixture story'}])
        sessions.append(s);return s
    jobs.adapter.m1_session_factory=provider
    entered,release=threading.Event(),threading.Event();video=adapter.compose_video;calls=[]
    def blocking_video(*args,**kw):
        calls.append(1)
        if len(calls)==1:entered.set();assert release.wait(15)
        return video(*args,**kw)
    monkeypatch.setattr(adapter,'compose_video',blocking_video)
    published=[];publish=adapter.Member3Session.publish
    def publish_spy(s):published.append(s.job_id);return publish(s)
    monkeypatch.setattr(adapter.Member3Session,'publish',publish_spy)
    old=start(client);assert entered.wait(15)
    attempt=sessions[0].attempt
    identity=dict(attempt.identity);digest=attempt.result_sha256
    denied=start(client,force=True);release.set()
    client.portal.call(lambda:_drain(jobs.tasks[old]))
    rejected=terminal(client,denied)
    assert rejected['status']=='failed'
    assert 'ATTEMPT_UNRESOLVED' in rejected['error']['msg']
    assert len(sessions)==1 and published==[]
    assert not (jobs.storage.root/'json/book01_p03_story.json').exists()
    assert sessions[0].attempt.identity==identity and sessions[0].attempt.result_sha256==digest
    assert not sessions[0].released
    assert rig.authority.totals()=={'spent':0,'held':1000,'available':14000}
    with rig.authority.tx() as db:
        row=db.execute('SELECT state,result,identity FROM attempts WHERE id=?',(attempt.attempt_id,)).fetchone()
        reservation=db.execute('SELECT state,amount FROM reservations WHERE id=?',(attempt.attempt_id,)).fetchone()
        assert row['state']=='SUBMITTED' and row['result']==digest
        assert json.loads(row['identity'])==identity
        assert reservation['state']=='UNKNOWN' and reservation['amount']==1000
    receipt=jobs.m1_receipts[(old,'book01_p03')]
    assert receipt['status']=='cancelled' and receipt['submission_state']=='UNKNOWN'
    for key in ['generation_mode','error','status','budget_release_error','m1_attempt_id','m1_result_sha256','request_id']:
        assert key in receipt
    assert (old,'book01_p03') in jobs.m1_reconciliation
    # Existing trusted M1 offline billing API, never exposed on M3 consumer.
    assert not hasattr(sessions[0].consumer,'settle')
    rig.authority.settle(attempt.attempt_id,200,'offline-billing-closure-002')
    assert rig.authority.totals()=={'spent':200,'held':0,'available':14800}
    rig.authority.settle(attempt.attempt_id,200,'offline-billing-closure-002')
    assert rig.authority.totals()['spent']==200
    replacement=start(client,force=True);result=terminal(client,replacement)
    assert result['status']=='done',result
    assert published==[replacement] and len(sessions)==2
    assert sessions[1].attempt_id!=attempt.attempt_id
    assert sessions[1].attempt.epoch>attempt.epoch
    raw=(jobs.storage.root/'json/book01_p03_story.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==sessions[1].attempt.result_sha256
    assert jobs.m1_receipts[(replacement,'book01_p03')]['m1_result_sha256']==hashlib.sha256(raw).hexdigest()
    assert rig.authority.totals()=={'spent':200,'held':1000,'available':13800}


@pytest.mark.parametrize('environment',['dev','production'])
def test_cancelled_and_revoked_generation_cannot_fetch_protected_assets(chain,monkeypatch,environment):
    client,jobs,rig,sessions=chain
    # Exercise a real submitted/cancelled job, then request even a leftover asset.
    entered,release=threading.Event(),threading.Event();video=adapter.compose_video
    def blocking(*a,**k):entered.set();assert release.wait(15);return video(*a,**k)
    monkeypatch.setattr(adapter,'compose_video',blocking)
    jid=start(client);assert entered.wait(15)
    client.portal.call(jobs.tasks[jid].cancel);release.set();client.portal.call(lambda:_drain(jobs.tasks[jid]))
    rig.fences.cancel(rig.page(3).record)
    from orchestrator.main import create_app
    from orchestrator.core.config import Settings
    from fastapi.testclient import TestClient
    protected=create_app(Settings(data_dir=jobs.storage.root,deployment_env=environment,asset_mode='blocked'))
    path=jobs.storage.root/'json/book01_p03_story.json';path.write_bytes(b'{"leftover":"never-public"}')
    with TestClient(protected) as denied:
        response=denied.get('/json/book01_p03_story.json')
        assert response.status_code==503 and response.json()['status']=='BLOCKED'
        assert b'never-public' not in response.content
    assert rig.authority.totals()['held']==1000
