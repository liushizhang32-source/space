"""Shared lifecycle behavior against actual SQLite, workers, Gate and publication."""
from pathlib import Path
from dataclasses import asdict,replace
from concurrent.futures import ThreadPoolExecutor
import json,threading,time
import pytest
from orchestrator.tests.test_m1_integration_reference import rig as authority_rig
from orchestrator.tests.test_m1_durable_stage_attempts import spec
from orchestrator.services.integration_reference import Authority,Denied
from orchestrator.services.vision_supervisor.shared import SharedFences
from orchestrator.services.vision_supervisor.durable import DurableSupervisor
from orchestrator.services.vision_supervisor.supervisor import Cancelled,VisionError
from orchestrator.services.vision_supervisor.gate import Gate
from orchestrator.services.vision_supervisor.pipeline import AtomicStore
from orchestrator.services.integration_reference.bridge import begin_from_gate


def assembly(authority_rig,tmp_path):
    a,k,n,service=authority_rig
    other=Authority(a.path,a.anchor,k,lambda:n[0],offline_test=True)
    first=SharedFences(a);second=SharedFences(other)
    record,_=first.begin('shared-job','book01_p03')
    image=tmp_path/'image.png';image.write_bytes(b'local-fixture')
    events=[];s=DurableSupervisor(tmp_path/'workers',authority=a,deadline=1,audit=events.append)
    return a,other,first,second,record,image,s,events,service

def gated(v):
    a,other,f1,f2,r,image,s,events,service=v
    c1=s.run(r,f1,'ocr',lambda n:spec(),image)
    c2=s.run(r,f1,'vlm',lambda n:spec(),image,c1=c1)
    gate=Gate({'local-fixture'});handoff=gate.accept(r,f1,c1,c2,(96,128))
    return c1,c2,gate,handoff


def test_two_instances_share_idempotent_begin_and_monotonic_epoch(authority_rig,tmp_path):
    a,b,f1,f2,r,image,s,events,service=assembly(authority_rig,tmp_path)
    same,created=f2.begin(r.job_id,r.page_id)
    assert not created and same.generation_id==r.generation_id and same.identity is None
    assert not created and same.epoch==r.epoch and f2.current(r)
    f2.cancel(same)
    with pytest.raises(Cancelled):f1.check(r)
    new,created=f1.begin('next-job',r.page_id,force=True)
    assert created and new.epoch==r.epoch+1 and new.generation_id!=r.generation_id
    f2.cancel(same)
    assert f1.current(new) and not f1.current(r)


def test_duplicate_stage_loser_does_not_revoke_authoritative_worker(authority_rig,tmp_path):
    a,b,f1,f2,r,image,s,events,service=assembly(authority_rig,tmp_path)
    first=f1.attempt(r);a.reserve_stage(first,'ocr','owner1');a.dispatch_stage(first,'owner1')
    r2=f2.restore(r.page_id);candidate=f2.attempt(r2)
    with pytest.raises(Denied,match='STAGE_UNRESOLVED'):b.reserve_stage(candidate,'ocr','owner2')
    f1.check(r,first)
    assert json.loads(a.vision_snapshot(r.page_id)['identity'])==asdict(first)


def test_cross_instance_cancel_drains_real_worker_before_replacement(authority_rig,tmp_path):
    a,b,f1,f2,r,image,s,events,service=assembly(authority_rig,tmp_path)
    started=threading.Event();s.audit=lambda e:(events.append(e),started.set() if e['event']=='started' else None)
    errors=[]
    def run():
        try:s.run(r,f1,'ocr',lambda n:spec('sleep'),image)
        except BaseException as e:errors.append(e)
    t=threading.Thread(target=run);t.start();assert started.wait(5)
    old=f2.restore(r.page_id);f2.cancel(old);t.join(8)
    assert not t.is_alive() and errors and isinstance(errors[0],Cancelled)
    assert any(e['event']=='reaped' for e in events)
    assert any(e['event']=='cleaned' for e in events)
    with a.tx() as db:assert db.execute('SELECT state FROM stage_attempts').fetchone()[0]=='CANCELLED'
    new,created=f2.begin('replacement',r.page_id,force=True)
    assert created and new.epoch>r.epoch


def test_force_commits_revocation_but_unknown_blocks_replacement(authority_rig,tmp_path):
    a,b,f1,f2,r,image,s,events,service=assembly(authority_rig,tmp_path)
    i=f1.attempt(r);a.reserve_stage(i,'ocr','owner');a.dispatch_stage(i,'owner')
    with pytest.raises(Denied,match='VISION_DRAIN_REQUIRED'):f2.begin('replacement',r.page_id,force=True)
    assert a.vision_snapshot(r.page_id)['status']=='CANCELLED'
    with pytest.raises(Cancelled):f1.check(r,i)
    a.reconcile_stage(i,'owner',outcome='CANCELLED',terminal_confirmed=True)
    new,created=f2.begin('replacement',r.page_id,force=True)
    assert created and new.epoch==r.epoch+1


def test_real_gate_generation_tokens_revoke_with_upstream(authority_rig,tmp_path):
    v=assembly(authority_rig,tmp_path);a,b,f1,f2,r,image,s,events,service=v
    c1,c2,gate,handoff=gated(v)
    result=begin_from_gate(a,gate,r,f1,c1,c2,(96,128),service=service,project='M1',request_id='generation',amount=500,image=image.read_bytes())
    name='upstream/'+r.generation_id+'/'+c2.identity.attempt_id+'/c2.json'
    assert a.read(service,result['token'],result['identity'],name)==handoff.c2
    assert result['identity']['attempt_id'] not in (c1.identity.attempt_id,c2.identity.attempt_id)
    f2.cancel(f2.restore(r.page_id))
    with pytest.raises(Denied,match='TOKEN_REVOKED'):a.read(service,result['token'],result['identity'],name)
    with pytest.raises(Denied):a.submit(service,result['token'],result['identity'],b'late-result')
    assert a.totals()['held']==0


def test_publication_current_survives_adapter_restart_and_cancel_invalidates(authority_rig,tmp_path,monkeypatch):
    monkeypatch.setenv('M1_ASSET_MODE','offline_mock')
    v=assembly(authority_rig,tmp_path);a,b,f1,f2,r,image,s,events,service=v
    c1,c2,gate,handoff=gated(v)
    docs={f'json/{r.page_id}_ocr.json':handoff.c1,f'json/{r.page_id}_vlm.json':handoff.c2,f'json/{r.page_id}_refs.json':handoff.sidecar,'fixture-result.bin':b'output'}
    store=AtomicStore(tmp_path/'private',f1)
    manifest=store.publish(r,c2.identity,docs,verify=lambda contents:None)
    assert a.vision_snapshot(r.page_id)['status']=='DONE'
    restored=f2.restore(r.page_id);other=AtomicStore(store.root,f2)
    assert other.read(r.page_id)[0]==manifest
    f2.cancel(restored)
    assert store.read(r.page_id) is None and other.read(r.page_id) is None


def test_failed_or_cancelled_generation_cannot_roll_back_new_current(authority_rig,tmp_path):
    a,b,f1,f2,r,image,s,events,service=assembly(authority_rig,tmp_path)
    i=f1.attempt(r);a.reserve_stage(i,'ocr','owner');a.finish_stage(i,'owner',outcome='FAILED',terminal_confirmed=True)
    f2.cancel(f2.restore(r.page_id));new,_=f2.begin('new',r.page_id,force=True)
    assert not a.vision_finish(i,'FAILED')
    f1.cancel(r)
    assert f2.current(new)


def test_real_other_process_cancel_observed_by_running_worker(authority_rig,tmp_path):
    import subprocess,sys
    a,b,f1,f2,r,image,s,events,service=assembly(authority_rig,tmp_path)
    s.deadline=3;started=threading.Event();errors=[]
    s.audit=lambda e:(events.append(e),started.set() if e['event']=='started' else None)
    def run():
        try:s.run(r,f1,'ocr',lambda n:spec('sleep'),image)
        except BaseException as e:errors.append(e)
    t=threading.Thread(target=run);t.start();assert started.wait(5)
    code='''import sys,json
from orchestrator.services.integration_reference import Authority,OfflineKMS
v=json.loads(sys.stdin.read())
a=Authority(v['path'],v['anchor'],OfflineKMS(seed=b'm1-shared-offline-fixture-root-seed'),lambda:1000,offline_test=True)
assert a.vision_cancel(v['lineage'])
print('CANCELLED')
'''
    p=subprocess.run([sys.executable,'-B','-c',code],input=json.dumps(dict(path=str(a.path),anchor=str(a.anchor),lineage=f1._lineage(r))),capture_output=True,text=True,timeout=15)
    assert p.returncode==0,p.stderr
    t.join(8);assert not t.is_alive() and errors and isinstance(errors[0],Cancelled)
    assert any(e['event']=='cleaned' for e in events)


def test_submitted_generation_budget_survives_upstream_revocation(authority_rig,tmp_path):
    v=assembly(authority_rig,tmp_path);a,b,f1,f2,r,image,s,events,service=v
    c1,c2,gate,handoff=gated(v)
    g=begin_from_gate(a,gate,r,f1,c1,c2,(96,128),service=service,project='M1',request_id='submitted',amount=500,image=image.read_bytes())
    a.submit(service,g['token'],g['identity'],b'candidate')
    f2.cancel(f2.restore(r.page_id))
    assert a.totals()['held']==500
    with pytest.raises(Denied):a.submit(service,g['token'],g['identity'],b'candidate')
    a.settle(g['identity']['attempt_id'],300,'trusted-old-attempt-receipt')
    assert a.totals()==dict(spent=300,held=0,available=14700)


def test_publication_and_other_instance_cancel_share_linearization_guard(authority_rig,tmp_path,monkeypatch):
    import orchestrator.services.vision_supervisor.pipeline as pipeline
    v=assembly(authority_rig,tmp_path);a,b,f1,f2,r,image,s,events,service=v
    c1,c2,gate,handoff=gated(v);old=f2.restore(r.page_id)
    store=AtomicStore(tmp_path/'private',f1)
    docs={f'json/{r.page_id}_ocr.json':handoff.c1,f'json/{r.page_id}_vlm.json':handoff.c2,f'json/{r.page_id}_refs.json':handoff.sidecar}
    replacing=threading.Event();release=threading.Event();cancelling=threading.Event();cancelled=threading.Event();errors=[];published=[]
    original=pipeline.os.replace
    def replace_pointer(source,target):
        if Path(target).parent==store.root/'pointers':
            replacing.set();assert release.wait(5)
        return original(source,target)
    monkeypatch.setattr(pipeline.os,'replace',replace_pointer)
    def publish():
        try:published.append(store.publish(r,c2.identity,docs,verify=lambda contents:None))
        except BaseException as e:errors.append(e)
    def cancel():
        cancelling.set()
        try:f2.cancel(old)
        except BaseException as e:errors.append(e)
        finally:cancelled.set()
    t=threading.Thread(target=publish);t.start();assert replacing.wait(5)
    other=threading.Thread(target=cancel);other.start();assert cancelling.wait(5)
    assert not cancelled.wait(.05)
    release.set();t.join(8);other.join(8)
    assert not t.is_alive() and not other.is_alive() and not errors and published
    assert a.vision_snapshot(r.page_id)['status']=='CANCELLED'
    assert not f1.accept_manifest(r,published[0])


def test_cancel_before_publication_never_exposes_candidate(authority_rig,tmp_path):
    v=assembly(authority_rig,tmp_path);a,b,f1,f2,r,image,s,events,service=v
    c1,c2,gate,handoff=gated(v);store=AtomicStore(tmp_path/'private',f1)
    docs={f'json/{r.page_id}_ocr.json':handoff.c1,f'json/{r.page_id}_vlm.json':handoff.c2,f'json/{r.page_id}_refs.json':handoff.sidecar}
    f2.cancel(f2.restore(r.page_id))
    with pytest.raises(Cancelled):store.publish(r,c2.identity,docs,verify=lambda contents:None)
    assert not list((store.root/'pointers').iterdir())

def test_real_process_restores_shared_current_and_exact_fencing(authority_rig,tmp_path):
    import subprocess,sys
    v=assembly(authority_rig,tmp_path);a,b,f1,f2,r,image,s,events,service=v
    c1,c2,gate,handoff=gated(v)
    code='''import sys,json
from dataclasses import asdict
from orchestrator.services.integration_reference import Authority,OfflineKMS
from orchestrator.services.vision_supervisor.shared import SharedFences
v=json.loads(sys.stdin.read())
a=Authority(v['path'],v['anchor'],OfflineKMS(seed=b'm1-shared-offline-fixture-root-seed'),lambda:1000,offline_test=True)
f=SharedFences(a);r=f.restore(v['page']);f.check(r,r.identity)
assert asdict(r.identity)==v['identity']
print('CURRENT_AND_FENCING_RESTORED')
'''
    p=subprocess.run([sys.executable,'-B','-c',code],input=json.dumps(dict(path=str(a.path),anchor=str(a.anchor),page=r.page_id,identity=asdict(c2.identity))),capture_output=True,text=True,timeout=15)
    assert p.returncode==0,p.stderr
    assert p.stdout.strip()=='CURRENT_AND_FENCING_RESTORED'


def test_shared_snapshot_restore_preserves_cancellation_and_epoch(authority_rig,tmp_path):
    v=assembly(authority_rig,tmp_path);a,b,f1,f2,r,image,s,events,service=v
    c1,c2,gate,handoff=gated(v)
    old=tmp_path/'old.sqlite';a.backup(old)
    f2.cancel(f2.restore(r.page_id));latest=tmp_path/'latest.sqlite';a.backup(latest)
    a.path.write_bytes(latest.read_bytes())
    reopened=Authority(a.path,a.anchor,authority_rig[1],lambda:1000,offline_test=True)
    restored=SharedFences(reopened);cancelled=restored.restore(r.page_id)
    with pytest.raises(Cancelled):restored.check(cancelled,c2.identity)
    new,created=restored.begin('after-recovery',r.page_id,force=True)
    assert created and new.epoch==r.epoch+1
    retained=a.anchor.read_bytes();a.path.write_bytes(old.read_bytes())
    with pytest.raises(Denied,match='ROLLBACK_DETECTED'):Authority(a.path,a.anchor,authority_rig[1],lambda:1000,offline_test=True)
    assert a.anchor.read_bytes()==retained

@pytest.mark.parametrize('bad_image',[None,b'different-input'])
def test_shared_bridge_requires_exact_original_image(authority_rig,tmp_path,bad_image):
    v=assembly(authority_rig,tmp_path);a,b,f1,f2,r,image,s,events,service=v
    c1,c2,gate,handoff=gated(v)
    with a.tx() as db:before=db.execute('SELECT count(*) FROM assets').fetchone()[0]
    with pytest.raises(Denied,match='IMAGE_BINDING'):
        begin_from_gate(a,gate,r,f1,c1,c2,(96,128),service=service,project='M1',request_id='wrong-image',amount=500,image=bad_image)
    assert a.totals()['held']==0
    with a.tx() as db:assert db.execute('SELECT count(*) FROM assets').fetchone()[0]==before

def test_shared_generation_proof_binds_all_four_actual_inputs(authority_rig,tmp_path):
    import hashlib
    v=assembly(authority_rig,tmp_path);a,b,f1,f2,r,image,s,events,service=v
    c1,c2,gate,handoff=gated(v)
    g=begin_from_gate(a,gate,r,f1,c1,c2,(96,128),service=service,project='M1',request_id='all-inputs',amount=500,
                      image=image.read_bytes(),final_messages=[{'role':'user','content':' exact fixture prompt '}])
    a.submit(service,g['token'],g['identity'],b'fixture-result')
    proof=a.provenance(service,g['token'],g['identity'])
    doc=a.verify_provenance(proof,expected_identity=g['identity'],expected_result=b'fixture-result')
    prefix='upstream/'+r.generation_id+'/'+c2.identity.attempt_id
    assert set(doc['inputs'])=={prefix+'/image.bin',prefix+'/c1.json',prefix+'/c2.json',prefix+'/sidecar.json'}
    assert doc['inputs'][prefix+'/image.bin']==hashlib.sha256(image.read_bytes()).hexdigest()
