"""Frozen F08: real worker dispatch, durable global ordinal and crash/restart proof."""
from dataclasses import replace,asdict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json,subprocess,sys,threading
import pytest
from orchestrator.tests.test_m1_integration_reference import rig as authority_rig
from orchestrator.services.integration_reference import Authority,Denied,OfflineKMS
from orchestrator.services.vision_supervisor.supervisor import Fences,Generation,Identity,VisionError,WorkerSpec
from orchestrator.services.vision_supervisor.durable import DurableSupervisor,frozen_retryable

FAKE=Path(__file__).parent/'fixtures/m1_vision_worker.py'

def setup(authority_rig,tmp_path):
    a,k,now,service=authority_rig;fences=Fences();record,_=fences.begin('stage-job','book01_p03')
    image=tmp_path/'image.png';image.write_bytes(b'credential-free-image-fixture')
    events=[];supervisor=DurableSupervisor(tmp_path/'workers',authority=a,deadline=1,audit=events.append)
    return a,k,now,fences,record,image,events,supervisor

def spec(mode='ok',code=2002):
    return WorkerSpec((sys.executable,'-I',str(FAKE.resolve()),'--mode',mode,'--code',str(code),'--transient'),'local-fixture')

def identity():return Identity('job','book01_p03','generation',1,1,'attempt-1','token-1')

def test_first_retry_then_restart_cannot_dispatch_third(authority_rig,tmp_path):
    a,k,n,f,r,image,events,s=setup(authority_rig,tmp_path)
    with pytest.raises(VisionError) as error:s.run(r,f,'ocr',lambda ordinal:spec('fail'),image)
    assert error.value.code==2002 and sum(e['event']=='started' for e in events)==2
    reopened=Authority(a.path,a.anchor,k,lambda:n[0],offline_test=True)
    other=DurableSupervisor(tmp_path/'workers2',authority=reopened,deadline=1,audit=events.append)
    f2=Fences();r2=Generation(r.job_id,r.page_id,r.generation_id,r.input_revision,r.epoch)
    f2.pages[r.page_id]=r2;f2.serial[r.page_id]=threading.Lock()
    calls=[]
    with pytest.raises(VisionError,match='STAGE_LIMIT'):other.run(r2,f2,'ocr',lambda ordinal:calls.append(ordinal) or spec(),image)
    assert not calls and sum(e['event']=='started' for e in events)==2
    with a.tx() as db:assert [tuple(x) for x in db.execute('SELECT ordinal,state FROM stage_attempts ORDER BY ordinal')]==[(1,'FAILED'),(2,'FAILED')]

def test_duplicate_entry_after_success_never_redispatches(authority_rig,tmp_path):
    a,k,n,f,r,image,events,s=setup(authority_rig,tmp_path)
    result=s.run(r,f,'ocr',lambda ordinal:spec(),image);assert result.documents['c1']
    with pytest.raises(VisionError,match='STAGE_FINAL'):s.run(r,f,'ocr',lambda ordinal:spec(),image)
    assert sum(e['event']=='started' for e in events)==1

def test_frozen_2004_without_approved_subtype_never_retries(authority_rig,tmp_path):
    a,k,n,f,r,image,events,s=setup(authority_rig,tmp_path)
    assert not frozen_retryable(VisionError(2004,'unavailable',transient=True),'ocr')
    with pytest.raises(VisionError) as error:s.run(r,f,'ocr',lambda ordinal:spec('fail',2004),image)
    assert error.value.code==2004 and sum(e['event']=='started' for e in events)==1
    with a.tx() as db:assert tuple(db.execute('SELECT ordinal,state,retry_allowed FROM stage_attempts').fetchone())==(1,'FAILED',0)

def test_reservation_and_dispatch_idempotency_preserve_one_slot(authority_rig):
    a,k,n,service=authority_rig;i=identity()
    one=a.reserve_stage(i,'ocr','owner');assert a.reserve_stage(i,'ocr','owner')==one
    a.dispatch_stage(i,'owner')
    with pytest.raises(Denied,match='STAGE_DISPATCH_REPLAY'):a.dispatch_stage(i,'owner')
    with pytest.raises(Denied,match='STAGE_UNRESOLVED'):a.reserve_stage(replace(i,attempt_id='new',fencing_token='new-token'),'ocr','owner2')
    with a.tx() as db:assert db.execute('SELECT count(*) FROM stage_attempts').fetchone()[0]==1

def test_unknown_never_releases_slot_or_allows_retry(authority_rig):
    a,k,n,service=authority_rig;i=identity();a.reserve_stage(i,'ocr','owner');a.dispatch_stage(i,'owner')
    a.finish_stage(i,'owner',outcome='FAILED',terminal_confirmed=False,retry_allowed=True)
    with pytest.raises(Denied,match='STAGE_UNRESOLVED'):a.reserve_stage(replace(i,attempt_id='new',fencing_token='new-token'),'ocr','next')
    with a.tx() as db:assert tuple(db.execute('SELECT state,retry_allowed FROM stage_attempts').fetchone())==('UNKNOWN',0)

def test_crash_after_reservation_consumes_slot_and_blocks_reentry(authority_rig):
    a,k,n,service=authority_rig;i=identity()
    code='''import sys,json,os
from orchestrator.services.integration_reference import Authority,OfflineKMS
from orchestrator.services.vision_supervisor.supervisor import Identity
x=Authority(sys.argv[1],sys.argv[2],OfflineKMS(seed=b'm1-shared-offline-fixture-root-seed'),lambda:1000,offline_test=True)
x.reserve_stage(Identity(**json.loads(sys.argv[3])),'ocr','crashed-owner')
os._exit(7)
'''
    p=subprocess.run([sys.executable,'-B','-c',code,str(a.path),str(a.anchor),json.dumps(asdict(i))],capture_output=True,text=True)
    assert p.returncode==7,p.stderr
    with pytest.raises(Denied,match='STAGE_UNRESOLVED'):a.reserve_stage(replace(i,attempt_id='next',fencing_token='next-token'),'ocr','new-owner')
    with a.tx() as db:assert tuple(db.execute('SELECT ordinal,state FROM stage_attempts').fetchone())==(1,'RESERVED')

def test_concurrent_authorities_only_one_reservation(authority_rig):
    a,k,n,service=authority_rig;i=identity()
    def reserve(number):
        x=Authority(a.path,a.anchor,k,lambda:n[0],offline_test=True)
        try:return x.reserve_stage(replace(i,attempt_id='attempt'+str(number),fencing_token='token'+str(number)),'ocr','owner'+str(number))
        except Denied as e:assert str(e)=='STAGE_UNRESOLVED';return None
    with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(reserve,range(12)))
    assert sum(row is not None for row in rows)==1

def test_success_cancel_and_nonretry_failure_are_terminal(authority_rig):
    a,k,n,service=authority_rig
    for index,outcome in enumerate(('SUCCEEDED','CANCELLED','FAILED')):
        i=replace(identity(),generation_id='g'+str(index),attempt_id='a'+str(index),fencing_token='t'+str(index))
        a.reserve_stage(i,'ocr','owner');a.dispatch_stage(i,'owner')
        a.finish_stage(i,'owner',outcome=outcome,terminal_confirmed=True)
        with pytest.raises(Denied,match='STAGE_FINAL'):a.reserve_stage(replace(i,attempt_id='again'+str(index),fencing_token='again-token'+str(index)),'ocr','owner2')

def test_cross_process_stage_contention_has_one_dispatch_slot(authority_rig):
    a,k,n,service=authority_rig
    code='''import sys
from orchestrator.services.integration_reference import Authority,OfflineKMS,Denied
from orchestrator.services.vision_supervisor.supervisor import Identity
x=Authority(sys.argv[1],sys.argv[2],OfflineKMS(seed=b'm1-shared-offline-fixture-root-seed'),lambda:1000,offline_test=True)
i=Identity('job','book01_p03','generation',1,1,'attempt'+sys.argv[3],'token'+sys.argv[3])
try:
 x.reserve_stage(i,'ocr','owner'+sys.argv[3]);print('ACCEPTED')
except Denied as e:print(str(e))
'''
    processes=[subprocess.Popen([sys.executable,'-B','-c',code,str(a.path),str(a.anchor),str(i)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for i in range(8)]
    results=[]
    for p in processes:
        stdout,stderr=p.communicate(timeout=30);assert p.returncode==0,stderr;results.append(stdout.strip())
    assert results.count('ACCEPTED')==1 and results.count('STAGE_UNRESOLVED')==7
    with a.tx() as db:assert db.execute('SELECT count(*) FROM stage_attempts').fetchone()[0]==1

def test_exact_original_owner_reconciles_unknown_without_refunding_ordinal(authority_rig):
    a,k,n,service=authority_rig;i=identity();a.reserve_stage(i,'ocr','owner');a.dispatch_stage(i,'owner')
    a.finish_stage(i,'owner',outcome='FAILED',terminal_confirmed=False)
    with pytest.raises(Denied,match='STAGE_OWNER_MISMATCH'):a.reconcile_stage(i,'replacement-owner',outcome='FAILED',terminal_confirmed=True,retry_allowed=True)
    a.reconcile_stage(i,'owner',outcome='FAILED',terminal_confirmed=True,retry_allowed=True)
    a.reconcile_stage(i,'owner',outcome='FAILED',terminal_confirmed=True,retry_allowed=True)
    second=replace(i,attempt_id='attempt2',fencing_token='token2')
    assert a.reserve_stage(second,'ocr','owner2')['ordinal']==2
    a.dispatch_stage(second,'owner2');a.finish_stage(second,'owner2',outcome='FAILED',terminal_confirmed=True,retry_allowed=True)
    with pytest.raises(Denied,match='STAGE_LIMIT'):a.reserve_stage(replace(i,attempt_id='attempt3',fencing_token='token3'),'ocr','owner3')

def test_frozen_supervisor_rejects_unvalidated_os_before_dispatch(authority_rig,tmp_path,monkeypatch):
    from types import SimpleNamespace
    import orchestrator.services.vision_supervisor.durable as module
    monkeypatch.setattr(module,'os',SimpleNamespace(name='posix'))
    with pytest.raises(VisionError,match='validated Windows NTFS'):
        DurableSupervisor(tmp_path/'unsupported',authority=authority_rig[0])
    assert not (tmp_path/'unsupported').exists()
