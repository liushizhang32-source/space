import hashlib,io,json,os,time
import httpx,pytest
from orchestrator.services.bailian.engine import BookEngine
from orchestrator.services.bailian.errors import IntegrationError
from orchestrator.services.bailian.authority import SUBJECT,PROJECT
from orchestrator.services.integration_reference.authority import Denied
from conftest import image_bytes,start_book,finish

def test_local_failure_before_first_paid_dispatch_releases_only_reserved(rig):
    engine,cloud=rig
    def broken(*args,**kwargs):raise IntegrationError('OCR_LOCAL_FAILURE')
    engine.local.ocr=broken
    book,q,job=start_book(engine);result=finish(engine,job)
    assert result['status']=='FAILED' and result['billing_status']=='NOT_CHARGED_RELEASED'
    assert not cloud.requests and engine.authority.m1.totals()==dict(spent=0,held=0,available=15000)
    lease=engine.authority.get('lease/'+job['id'])
    with engine.authority.m1.tx() as db:
        assert db.execute('SELECT state FROM reservations WHERE id=?',(lease['identity']['attempt_id'],)).fetchone()[0]=='RELEASED'

def test_actual_wan_task_id_recovers_without_paid_resubmission(rig):
    engine,cloud=rig;cloud.task_status='PENDING'
    def interrupt(request,body):
        if '/tasks/' in request.url.path and request.method=='GET':engine.shutdown_requested=True
    cloud.before=interrupt;book,q,job=start_book(engine);result=finish(engine,job)
    assert result['status']=='RECOVERY_REQUIRED' and result['billing_status']=='UNKNOWN'
    posts=sum(r[0]=='POST' for r in cloud.requests)
    engine.close();cloud.before=None;cloud.task_status='SUCCEEDED'
    resumed=BookEngine(engine.authority.root,local=engine.local,transport=httpx.MockTransport(cloud));resumed._key='fixture-not-real'
    try:
        resumed.resume(job['id']);result=finish(resumed,job)
        assert result['status']=='COMPLETED' and result['identity']==job['identity']
        assert sum(r[0]=='POST' for r in cloud.requests)==posts
        assert sum(r[1].endswith('/video-synthesis') for r in cloud.requests)==1
        assert resumed.authority.m1.totals()['held']==q['estimate_fen']
    finally:resumed.close()

def test_cancel_pending_wan_waits_and_cannot_release_unknown(rig):
    engine,cloud=rig;cloud.task_status='PENDING'
    def cancel(request,body):
        if '/tasks/' in request.url.path and request.method=='GET':
            engine.cancel(engine.authority.all('job/')[0]['id'])
    cloud.before=cancel;book,q,job=start_book(engine);result=finish(engine,job)
    assert engine.futures[job['id']].done() and result['status']=='CANCELLED'
    assert any(r[1].endswith('/cancel') for r in cloud.requests)
    assert engine.authority.m1.totals()['held']==q['estimate_fen']
    lease=engine.authority.get('lease/'+job['id'])
    with pytest.raises(Denied,match='UNKNOWN_RETAINS_BUDGET'):engine.authority.m1.cancel(lease['identity']['attempt_id'])

def test_lease_renewal_preserves_identity_and_fences(rig):
    engine,cloud=rig;book,q,job=start_book(engine);finish(engine,job)
    original=engine.authority.get('lease/'+job['id']);engine.authority.m1.clock=lambda:int(time.time())+400
    raw=engine.authority.input(job['id'],book['pages'][0]['asset']);renewed=engine.authority.get('lease/'+job['id'])
    assert hashlib.sha256(raw).hexdigest()==book['pages'][0]['sha256']
    assert original['identity']==renewed['identity'] and original['token']!=renewed['token']
    assert engine.authority.m1.totals()['held']==q['estimate_fen']

def test_revoked_lease_cannot_renew_after_expiry(rig):
    engine,cloud=rig;book,q,job=start_book(engine);finish(engine,job)
    original=engine.authority.get('lease/'+job['id']);engine.authority.m1.revoke(original['token'])
    engine.authority.m1.clock=lambda:int(time.time())+400
    with pytest.raises(Denied,match='TOKEN_REVOKED'):engine.authority.bound(job['id'])
    assert engine.authority.get('lease/'+job['id'])['token']==original['token']

def test_original_m1_grant_revocation_denies_all_cloud_assets(rig):
    engine,cloud=rig;book,q,job=start_book(engine);result=finish(engine,job)
    engine.authority.m1.grant(SUBJECT,PROJECT,'generate',False)
    with pytest.raises(Denied,match='FORBIDDEN'):engine.authority.read(result['outputs']['video'].removeprefix('/studio/assets/'),job=job['id'])
    assert engine.authority.m1.totals()['held']==q['estimate_fen']

def test_book_input_revision_is_frozen_after_attempt(rig):
    engine,cloud=rig;book,q,job=start_book(engine);finish(engine,job)
    with pytest.raises(IntegrationError,match='BOOK_IMMUTABLE_AFTER_ATTEMPT'):engine.reorder(book['id'],[book['pages'][0]['id']])

def test_voice_question_uses_real_decoding_and_mock_asr_then_agent(rig,native_media):
    engine,cloud=rig;book,q,job=start_book(engine);finish(engine,job)
    result=engine.ask(job['id'],1,'',100,True,'audio-qa',native_media['audio'])
    assert result['question']=='小兔子为什么帮助朋友？' and result['answer']
    req=next(r[2] for r in cloud.requests if r[2] and r[2].get('model')=='qwen3-asr-flash')
    assert req['messages'][0]['content'][0]['input_audio']['data'].startswith('data:audio/wav;base64,')
    assert 'enable_thinking' not in req and req['asr_options']['enable_itn'] is False
    engine.cancel(job['id'])
    with pytest.raises(Denied):engine.authority.read(result['audio_url'].removeprefix('/studio/assets/'),job=result['job_id'])

def test_cloud_attempt_cannot_use_fixture_billing_or_provenance(rig):
    engine,cloud=rig;book,q,job=start_book(engine);finish(engine,job)
    lease=engine.authority.get('lease/'+job['id'])
    with pytest.raises(Denied,match='REAL_BILLING_ADAPTER_REQUIRED'):
        engine.authority.m1.settle(lease['identity']['attempt_id'],1,'fictional-offline-receipt')
    with pytest.raises(Denied,match='OFFLINE_PROVENANCE_ONLY'):
        engine.authority.m1.provenance(engine.authority.service(),lease['token'],lease['identity'])
    assert engine.authority.m1.totals()['held']==q['estimate_fen'] and engine.authority.m1.totals()['spent']==0

def test_native_cancellation_waits_for_detached_descendant_handles(tmp_path,monkeypatch):
    import sys
    from orchestrator.services.bailian.local import run
    from orchestrator.services.bailian.errors import Cancelled
    from orchestrator.services.vision_supervisor.tree import WindowsTree
    marker=tmp_path/'should-not-appear';child=tmp_path/'child.py';parent=tmp_path/'parent.py'
    child.write_text('import time,pathlib,sys;time.sleep(3);pathlib.Path(sys.argv[1]).write_text("leak");time.sleep(30)',encoding='utf-8')
    parent.write_text('import subprocess,sys,time;subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2]],creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP);time.sleep(30)',encoding='utf-8')
    observations=[];original=WindowsTree.wait_members
    def witnessed(self):
        original(self);observations.append(dict(active=self.active(),handles=len(self.exit_witness),all_signalled=all(self.exit_witness.values())))
    monkeypatch.setattr(WindowsTree,'wait_members',witnessed)
    started=time.monotonic()
    with pytest.raises(Cancelled):run([sys.executable,parent,child,marker],cancel=lambda:time.monotonic()-started>1,timeout=10)
    assert observations and observations[-1]['active']==0 and observations[-1]['handles']>=3 and observations[-1]['all_signalled']
    assert not marker.exists()

def test_published_output_cannot_be_replaced_with_different_bytes(rig):
    engine,cloud=rig;book,q,job=start_book(engine);result=finish(engine,job)
    name=result['outputs']['video'].removeprefix('/studio/assets/');original,meta=engine.authority.read(name,job=job['id'])
    with pytest.raises(Denied,match='OUTPUT_IMMUTABLE'):engine.authority.store(name,b'other bytes','video/mp4',job=job['id'])
    assert engine.authority.read(name,job=job['id'])[0]==original

def test_completion_race_cannot_overwrite_cancel_state(rig):
    engine,cloud=rig;book,q,job=start_book(engine);finish(engine,job);engine.cancel(job['id'])
    result=engine.update(job['id'],status='COMPLETED',outputs={'video':'untrusted'})
    assert result['status']=='CANCELLED' and result['cancel_requested'] is True and result['outputs']=={}
