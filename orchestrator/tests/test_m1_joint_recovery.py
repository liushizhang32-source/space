"""Recovery must authenticate database schema and retain the owning authority path."""
from pathlib import Path
import sqlite3,shutil
import pytest
from orchestrator.tests.test_m1_integration_reference import rig
from orchestrator.services.integration_reference import Authority,Denied


def test_schema_trigger_tamper_rejected_before_any_authorized_operation(rig):
    a,k,n,service=rig
    with sqlite3.connect(a.path) as db:
        db.execute('CREATE TRIGGER reset_spending AFTER UPDATE OF spent ON projects BEGIN UPDATE projects SET spent=0; END')
    with pytest.raises(Denied,match='ROLLBACK_DETECTED'):a.totals()


def test_database_copy_cannot_run_as_second_authority_against_same_anchor(rig,tmp_path):
    a,k,n,service=rig;copy=tmp_path/'forked.sqlite';shutil.copyfile(a.path,copy)
    with pytest.raises(Denied,match='AUTHORITY_PATH_MISMATCH'):
        Authority(copy,a.anchor,k,lambda:n[0],offline_test=True)

from orchestrator.tests.test_m1_shared_current import assembly,gated
from orchestrator.services.integration_reference.recovery import JointSnapshot
from orchestrator.services.vision_supervisor.shared import SharedFences
from orchestrator.services.vision_supervisor.pipeline import AtomicStore
from orchestrator.services.vision_supervisor.supervisor import Cancelled
from orchestrator.services.integration_reference.bridge import begin_from_gate
import hashlib,json,os,subprocess,sys,threading
from concurrent.futures import ThreadPoolExecutor


def published(rig,tmp_path,*,pending=False):
    a,k,n,old_service=rig;v=assembly(rig,tmp_path)
    a,b,f1,f2,r,image,s,events,old_service=v
    k.rotate('offline-2');service=a.service_token('M3',ttl=300)
    c1,c2,gate,handoff=gated(v)
    task=begin_from_gate(a,gate,r,f1,c1,c2,(96,128),service=service,project='M1',request_id='joint-gen',amount=500,image=image.read_bytes())
    a.submit(service,task['token'],task['identity'],b'joint-result');a.settle(task['identity']['attempt_id'],300,'joint-bill');a.revoke(task['token'])
    unknown=None
    if pending:
        unknown=begin_from_gate(a,gate,r,f1,c1,c2,(96,128),service=service,project='M1',request_id='joint-pending',amount=700,image=image.read_bytes())
        a.submit(service,unknown['token'],unknown['identity'],b'unknown-result')
    k.revoke('offline-1')
    store=AtomicStore(tmp_path/'published',f1)
    docs={f'json/{r.page_id}_ocr.json':handoff.c1,f'json/{r.page_id}_vlm.json':handoff.c2,f'json/{r.page_id}_refs.json':handoff.sidecar,'output/result.bin':b'joint-result'}
    manifest=store.publish(r,c2.identity,docs,verify=lambda data:None)
    return a,k,n,service,task,unknown,store,manifest,r


def test_joint_snapshot_restores_missing_db_files_budget_revocation_and_fencing(rig,tmp_path,monkeypatch):
    monkeypatch.setenv('M1_ASSET_MODE','offline_mock')
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path,pending=True)
    manager=JointSnapshot.for_store(a,store);snapshot=tmp_path/'joint-snapshot';doc=manager.create(snapshot)
    assert manager.verify(snapshot)['files']==5
    expected=a.totals();assert expected==dict(spent=300,held=700,available=14000)
    retained=a.anchor.read_bytes()
    # Simulated disaster targets only these verified, newly-created test resources.
    assert store.root.resolve().is_relative_to(tmp_path.resolve())
    shutil.rmtree(store.root);a.path.unlink()
    recovery=JointSnapshot(a.path,a.anchor,store.root,clock=lambda:n[0],offline_test=True)
    assert recovery.restore(snapshot,operation_id='test-recovery',services_stopped=True)['status']=='RESTORED_OFFLINE'
    assert a.anchor.read_bytes()==retained
    reopened=Authority(a.path,a.anchor,k,lambda:n[0],offline_test=True)
    assert reopened.totals()==expected
    f=SharedFences(reopened);restored=f.restore(r.page_id)
    assert restored.epoch==r.epoch and restored.identity==r.identity
    assert AtomicStore(store.root,f).read(r.page_id)[0]==manifest
    with pytest.raises(Denied,match='REVOKED'):reopened.read(service,task['token'],task['identity'],'unused')
    assert set(reopened.public_keys())=={'offline-2'}
    reopened.recover();assert reopened.totals()['held']==700
    reopened.settle(unknown['identity']['attempt_id'],200,'recovered-bill')
    assert reopened.totals()==dict(spent=500,held=0,available=14500)
    f.cancel(restored);new,created=f.begin('next',r.page_id,force=True)
    assert created and new.epoch==r.epoch+1


def test_joint_snapshot_rejects_old_snapshot_against_retained_new_anchor(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'old';manager.create(snap)
    store.fences.cancel(r);retained=a.anchor.read_bytes()
    with pytest.raises(Denied,match='SNAPSHOT_ROLLBACK'):manager.restore(snap,operation_id='rollback',services_stopped=True)
    assert a.anchor.read_bytes()==retained and not a.maintenance_path.exists()


@pytest.mark.parametrize('fault_phase',['maintenance_ready','files_staged','old_assets_quarantined','assets_installed','database_installed','before_release'])
def test_interrupted_joint_restore_blocks_services_and_resumes_same_operation(rig,tmp_path,fault_phase):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'snapshot';manager.create(snap)
    def fail(phase):
        if phase==fault_phase:raise OSError('injected restore interruption')
    with pytest.raises(OSError,match='interruption'):manager.restore(snap,operation_id='restore-owner',services_stopped=True,fault=fail)
    assert a.maintenance_path.exists()
    with pytest.raises(Denied,match='MAINTENANCE'):a.totals()
    with pytest.raises(Denied,match='RESTORE_OWNER_MISMATCH'):manager.restore(snap,operation_id='different-owner',services_stopped=True)
    assert manager.restore(snap,operation_id='restore-owner',services_stopped=True)['status']=='RESTORED_OFFLINE'
    assert not a.maintenance_path.exists() and a.totals()['spent']==300
    assert list(store.root.parent.glob(store.root.name+'.before-restore-*'))


def test_joint_restore_survives_real_process_death(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'snapshot';manager.create(snap)
    code='''import json,sys,os
from orchestrator.services.integration_reference.recovery import JointSnapshot
v=json.loads(sys.stdin.read())
r=JointSnapshot(v['db'],v['anchor'],v['assets'],clock=lambda:1000,offline_test=True)
def fault(phase):
 if phase=='assets_installed':os._exit(7)
r.restore(v['snapshot'],operation_id='crash-owner',services_stopped=True,fault=fault)
'''
    p=subprocess.run([sys.executable,'-B','-c',code],input=json.dumps(dict(db=str(a.path),anchor=str(a.anchor),assets=str(store.root),snapshot=str(snap))),capture_output=True,text=True,timeout=30)
    assert p.returncode==7,p.stderr
    with pytest.raises(Denied,match='MAINTENANCE'):a.totals()
    other=JointSnapshot(a.path,a.anchor,store.root,clock=lambda:n[0],offline_test=True)
    assert other.restore(snap,operation_id='crash-owner',services_stopped=True)['status']=='RESTORED_OFFLINE'
    assert a.totals()['spent']==300


@pytest.mark.parametrize('tamper',['bundle','catalogue','database-trigger','path'])
def test_joint_snapshot_tamper_rejected_without_live_mutation(rig,tmp_path,tamper):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'snapshot';manager.create(snap)
    header=snap/'snapshot.json';doc=json.loads(header.read_text())
    if tamper=='bundle':
        name=next(n for n in doc['files'] if n.endswith('result.bin'));(snap/'files'/name).write_bytes(b'tampered')
        doc['files'][name]=hashlib.sha256(b'tampered').hexdigest()
    elif tamper=='catalogue':doc['files']['../../escape']='a'*64
    elif tamper=='database-trigger':
        with sqlite3.connect(snap/'authority.sqlite') as db:db.execute('CREATE TRIGGER hostile AFTER UPDATE OF spent ON projects BEGIN UPDATE projects SET spent=0; END')
        doc['db_sha256']=hashlib.sha256((snap/'authority.sqlite').read_bytes()).hexdigest()
    else:doc['asset_root']=str(tmp_path/'escape')
    header.write_text(json.dumps(doc))
    retained=a.anchor.read_bytes();original=a.path.read_bytes()
    with pytest.raises(Denied):manager.restore(snap,operation_id='tamper',services_stopped=True)
    assert a.anchor.read_bytes()==retained and a.path.read_bytes()==original and not a.maintenance_path.exists()


def test_joint_create_serializes_publication_lifecycle_writers(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'snapshot'
    entered=threading.Event();release=threading.Event();errors=[]
    def fault(phase):
        if phase=='database_copied':entered.set();assert release.wait(5)
    def create():
        try:manager.create(snap,fault=fault)
        except BaseException as e:errors.append(e)
    t=threading.Thread(target=create);t.start();assert entered.wait(5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        cancelled=pool.submit(store.fences.cancel,r)
        assert not cancelled.done();release.set();t.join(8);cancelled.result(timeout=8)
    assert not errors and not t.is_alive()
    with sqlite3.connect(snap/'authority.sqlite') as db:assert db.execute('SELECT status FROM vision_current').fetchone()[0]=='DONE'
    assert a.vision_snapshot(r.page_id)['status']=='CANCELLED'
    with pytest.raises(Denied,match='SNAPSHOT_ROLLBACK'):manager.verify(snap)


def test_joint_restore_requires_explicit_offline_stop_contract(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'snapshot';manager.create(snap)
    with pytest.raises(Denied,match='REQUIRES_STOP'):manager.restore(snap,operation_id='not-stopped')
    assert not a.maintenance_path.exists()


def test_completed_restore_retry_is_idempotent_and_audited(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'snapshot';manager.create(snap)
    result=manager.restore(snap,operation_id='idempotent',services_stopped=True)
    quarantines=list(store.root.parent.glob(store.root.name+'.before-restore-*'))
    assert manager.restore(snap,operation_id='idempotent',services_stopped=True)==result
    assert list(store.root.parent.glob(store.root.name+'.before-restore-*'))==quarantines
    records=manager._journal_read()
    assert sum(row['payload']['action']=='RESTORE_COMPLETED' for row in records)==1
    assert any(row['payload']['action']=='SNAPSHOT_CREATED' for row in records)
    assert all('token' not in row['payload'] and 'signature' not in row['payload'] for row in records)


def test_crash_after_audit_commit_before_gate_release_resumes(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'snapshot';manager.create(snap)
    def fault(phase):
        if phase=='completion_recorded':raise OSError('after audit commit')
    with pytest.raises(OSError):manager.restore(snap,operation_id='audited',services_stopped=True,fault=fault)
    with pytest.raises(Denied,match='MAINTENANCE'):a.totals()
    assert manager.restore(snap,operation_id='audited',services_stopped=True)['status']=='RESTORED_OFFLINE'
    assert sum(r['payload']['action']=='RESTORE_COMPLETED' for r in manager._journal_read())==1
    assert a.totals()['spent']==300


def test_safe_abort_releases_only_verified_live_state(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'snapshot';manager.create(snap)
    def fault(phase):
        if phase=='files_staged':raise OSError('staging interruption')
    with pytest.raises(OSError):manager.restore(snap,operation_id='abortable',services_stopped=True,fault=fault)
    assert manager.abort(operation_id='abortable',services_stopped=True)['status']=='ABORTED_WITH_VALID_LIVE_STATE'
    assert a.totals()['spent']==300 and not a.maintenance_path.exists()
    assert manager._journal_read()[-1]['payload']['action']=='RESTORE_ABORTED'


def test_abort_refuses_unverified_db_or_missing_assets(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'snapshot';manager.create(snap)
    def fault(phase):
        if phase=='old_assets_quarantined':raise OSError('between root renames')
    with pytest.raises(OSError):manager.restore(snap,operation_id='not-abortable',services_stopped=True,fault=fault)
    with pytest.raises(Denied):manager.abort(operation_id='not-abortable',services_stopped=True)
    assert a.maintenance_path.exists()
    assert manager.restore(snap,operation_id='not-abortable',services_stopped=True)['status']=='RESTORED_OFFLINE'


def test_two_recovery_operators_cannot_run_concurrently(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'snapshot';manager.create(snap)
    entered=threading.Event();release=threading.Event();errors=[]
    def fault(phase):
        if phase=='maintenance_ready':entered.set();assert release.wait(5)
    def restore():
        try:manager.restore(snap,operation_id='one-owner',services_stopped=True,fault=fault)
        except BaseException as e:errors.append(e)
    t=threading.Thread(target=restore);t.start();assert entered.wait(5)
    other=JointSnapshot(a.path,a.anchor,store.root,clock=lambda:n[0],offline_test=True)
    with pytest.raises(Denied,match='RECOVERY_BUSY'):other.restore(snap,operation_id='one-owner',services_stopped=True)
    release.set();t.join(8);assert not t.is_alive() and not errors


def test_recovery_journal_tamper_fails_closed(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'snapshot';manager.create(snap)
    records=manager.journal_path.read_bytes();manager.journal_path.write_bytes(records.replace(b'SNAPSHOT_CREATED',b'SNAPSHOT_FORGED!'))
    with pytest.raises(Denied,match='RECOVERY_AUDIT_CORRUPT'):manager.restore(snap,operation_id='tampered-journal',services_stopped=True)
    assert not a.maintenance_path.exists()


@pytest.mark.parametrize('phase',['database_copied','before_complete'])
def test_incomplete_snapshot_never_accepted(rig,tmp_path,phase):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'incomplete'
    def fault(at):
        if at==phase:raise OSError('snapshot interruption')
    with pytest.raises(OSError):manager.create(snap,fault=fault)
    with pytest.raises(Denied,match='SNAPSHOT_INCOMPLETE'):manager.restore(snap,operation_id='incomplete',services_stopped=True)
    assert not a.maintenance_path.exists() and a.totals()['spent']==300


def test_missing_retained_anchor_never_bootstraps_a_new_budget(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'snapshot';manager.create(snap)
    a.anchor.unlink()
    with pytest.raises(Denied):manager.restore(snap,operation_id='no-trusted-anchor',services_stopped=True)
    a.path.unlink()
    with pytest.raises(Denied,match='ALREADY_PROVISIONED'):Authority.provision(a.path,a.anchor,k,lambda:n[0],offline_test=True)


def test_recovery_refuses_asset_root_containing_the_authority(rig,tmp_path):
    a,k,n,service=rig
    with pytest.raises(Denied,match='RECOVERY_PATHS'):JointSnapshot(a.path,a.anchor,tmp_path,clock=lambda:1000,offline_test=True)


def test_oversized_snapshot_fails_without_live_mutation(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);manager.max_bytes=1
    with pytest.raises(Denied,match='TOO_LARGE'):manager.create(tmp_path/'too-large')
    assert not a.maintenance_path.exists() and a.totals()['spent']==300

def test_failed_rotation_during_maintenance_does_not_publish_key_material(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snap=tmp_path/'snapshot';manager.create(snap)
    def fault(phase):
        if phase=='maintenance_ready':raise OSError('pause recovery')
    with pytest.raises(OSError):manager.restore(snap,operation_id='blocked-key',services_stopped=True,fault=fault)
    before=set(k.public_keys())
    with pytest.raises(Denied,match='MAINTENANCE'):k.rotate('rejected-key')
    assert set(k.public_keys())==before and k.active=='offline-2'
    manager.abort(operation_id='blocked-key',services_stopped=True)


def test_standalone_checkpoint_capture_never_loads_kms(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot(a.path,a.anchor,store.root,clock=lambda:n[0],offline_test=True)
    before=len(k.audit)
    doc=manager.create(tmp_path/'without-kms')
    assert doc['state_sha256']==a.anchor.read_text() and len(k.audit)==before


def test_offline_recovery_cli_verifies_without_printing_credentials(rig,tmp_path):
    a,k,n,service,task,unknown,store,manifest,r=published(rig,tmp_path)
    manager=JointSnapshot.for_store(a,store);snapshot=tmp_path/'snapshot';manager.create(snapshot)
    script=Path(__file__).resolve().parents[2]/'tools/m1_acceptance/recover_offline.py'
    args=[sys.executable,'-B',str(script),'verify','--database',str(a.path),'--anchor',str(a.anchor),'--asset-root',str(store.root),'--snapshot',str(snapshot),'--offline-test']
    result=subprocess.run(args,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['files']==5 and service not in result.stdout and task['token'] not in result.stdout
    result=subprocess.run([*args[:3],'restore',*args[4:],'--operation-id','cli-no-stop'],capture_output=True,text=True,timeout=20)
    assert result.returncode==1 and json.loads(result.stdout)['reason']=='OFFLINE_RESTORE_REQUIRES_STOP'
    assert not a.maintenance_path.exists()


def test_offline_recovery_cli_constructor_failure_is_structured(rig,tmp_path):
    a,k,n,service=rig
    command=[sys.executable,'-B','tools/m1_acceptance/recover_offline.py','verify','--offline-test',
        '--database',str(a.path),'--anchor',str(a.anchor),'--asset-root',str(tmp_path),'--snapshot',str(tmp_path/'missing')]
    result=subprocess.run(command,capture_output=True,text=True,timeout=15)
    assert result.returncode==1
    assert json.loads(result.stdout)['status']=='BLOCKED'
    assert 'Traceback' not in result.stderr and service not in result.stdout
