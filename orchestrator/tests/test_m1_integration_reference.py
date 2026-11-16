"""Executable offline integration acceptance; no network/provider calls."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json, sqlite3, subprocess, sys
import pytest
from orchestrator.services.integration_reference import Authority, Denied, OfflineKMS

@pytest.fixture
def rig(tmp_path):
    now=[1000];keys=OfflineKMS(seed=b'm1-shared-offline-fixture-root-seed')
    a=Authority.provision(tmp_path/'authority.sqlite',tmp_path/'retained.anchor',keys,lambda:now[0],offline_test=True)
    a.provision_project('M1');a.grant('M3','M1','generate');a.grant('M3','M1','assets.read')
    a.put_asset('M1','inputs/c2.json',b'fixture');a.put_asset('M1','private/secret',b'deny')
    return a,keys,now,a.service_token('M3',ttl=300)

def begin(rig,request='req',page='page',amount=1000,**kwargs):
    return rig[0].begin(rig[3],'M1',page,request,amount,['inputs/c2.json'],**kwargs)

def test_full_chain_idempotency_and_audit(rig):
    a,keys,now,s=rig;b=begin(rig)
    assert begin(rig)==b and a.totals()==dict(spent=0,held=1000,available=14000)
    assert a.read(s,b['token'],b['identity'],'inputs/c2.json')==b'fixture'
    result=a.submit(s,b['token'],b['identity'],b'output')
    assert a.submit(s,b['token'],b['identity'],b'output')==result
    a.settle(b['identity']['attempt_id'],700,'receipt');a.settle(b['identity']['attempt_id'],700,'receipt')
    assert a.totals()==dict(spent=700,held=0,available=14300)
    with a.tx() as db:
        previous=''
        from orchestrator.services.integration_reference.authority import digest
        events=db.execute('SELECT * FROM events ORDER BY seq').fetchall()
        for e in events:
            assert e['previous']==previous
            assert e['hash']==digest((previous+e['payload']).encode());previous=e['hash']
        assert sum(json.loads(e['payload'])['kind']=='settled' for e in events)==1

@pytest.mark.parametrize('bad',['../secret','inputs/../secret','/inputs/c2.json','C:/x','inputs\\c2.json','inputs//c2.json','inputs/%2e%2e/secret','inputs/c2.json.','inputs/./c2.json','inputs/c2.json '])
def test_path_denial(rig,bad):
    b=begin(rig)
    with pytest.raises(Denied,match='INVALID_PATH'):rig[0].read(rig[3],b['token'],b['identity'],bad)

def test_grant_revoke_asset_scope_and_version(rig):
    a,k,n,s=rig;b=begin(rig)
    with pytest.raises(Denied,match='ASSET_FORBIDDEN'):a.read(s,b['token'],b['identity'],'private/secret')
    a.grant('M3','M1','assets.read',False)
    with pytest.raises(Denied,match='FORBIDDEN'):a.read(s,b['token'],b['identity'],'inputs/c2.json')
    a.grant('M3','M1','assets.read');a.put_asset('M1','inputs/c2.json',b'changed')
    with pytest.raises(Denied,match='ASSET_VERSION'):a.read(s,b['token'],b['identity'],'inputs/c2.json')

def test_service_binding_and_forgery(rig):
    a,k,n,s=rig;b=begin(rig);other=a.service_token('M2')
    with pytest.raises(Denied,match='SERVICE_MISMATCH'):a.read(other,b['token'],b['identity'],'inputs/c2.json')
    doc=json.loads(s);doc['signature']='00'*64
    with pytest.raises(Denied,match='INVALID_SIGNATURE'):a.begin(json.dumps(doc),'M1','p','r2',1,['inputs/c2.json'])
    with pytest.raises(Denied,match='TOKEN_KIND'):a.read(b['token'],b['token'],b['identity'],'inputs/c2.json')
    with pytest.raises(Denied):a.read('',b['token'],b['identity'],'inputs/c2.json')

def test_expiry_is_persistent_after_rejection(rig):
    a,k,n,s=rig;b=begin(rig,ttl=1);n[0]+=1
    with pytest.raises(Denied,match='TOKEN_EXPIRED'):a.read(s,b['token'],b['identity'],'inputs/c2.json')
    with a.tx() as db: assert db.execute("SELECT status FROM tokens WHERE kind='attempt'").fetchone()[0]=='EXPIRED'
    n[0]-=1
    with pytest.raises(Denied,match='CLOCK_ROLLBACK'):a.totals()

def test_revoked_and_stale_attempt(rig):
    a,k,n,s=rig;b=begin(rig);a.cancel(b['identity']['attempt_id']);new=begin(rig,request='r2')
    assert new['identity']['epoch']>b['identity']['epoch']
    assert new['identity']['attempt_id']!=b['identity']['attempt_id']
    with pytest.raises(Denied,match='TOKEN_REVOKED'):a.read(s,b['token'],b['identity'],'inputs/c2.json')
    a.revoke(new['token']);a.revoke(new['token'])
    with pytest.raises(Denied,match='TOKEN_REVOKED'):a.submit(s,new['token'],new['identity'],b'x')

def test_key_rotation_revoke_fail_closed(rig):
    a,k,n,s=rig;b=begin(rig);k.rotate('offline-2')
    assert a.read(s,b['token'],b['identity'],'inputs/c2.json')==b'fixture'
    k.revoke('offline-1')
    with pytest.raises(Denied,match='UNKNOWN_KEY'):a.read(s,b['token'],b['identity'],'inputs/c2.json')

def test_concurrent_budget_no_overrun(rig):
    a,k,n,s=rig
    def run(i):
        other=Authority(a.path,a.anchor,k,lambda:n[0],offline_test=True)
        try: return other.begin(s,'M1','page'+str(i),'req'+str(i),4000,['inputs/c2.json'])
        except Denied as e: assert str(e)=='BUDGET_EXHAUSTED';return None
    with ThreadPoolExecutor(max_workers=8) as pool: result=list(pool.map(run,range(12)))
    assert sum(x is not None for x in result)==3
    assert a.totals()==dict(spent=0,held=12000,available=3000)

def test_concurrent_same_request_single_hold(rig):
    with ThreadPoolExecutor(max_workers=8) as pool: result=list(pool.map(lambda i:begin(rig),range(16)))
    assert all(x==result[0] for x in result)
    assert rig[0].totals()['held']==1000

@pytest.mark.parametrize('value',[True,False,-1,0,15001,1.1,'1000',None])
def test_invalid_budget_inputs(rig,value):
    with pytest.raises(Denied,match='INVALID_AMOUNT'):begin(rig,amount=value)
    assert rig[0].totals()['held']==0

def test_project_fixed_and_attempt_fencing(rig):
    a,k,n,s=rig;b=begin(rig)
    with pytest.raises(Denied,match='PROJECT_ACCOUNT_FIXED'):a.provision_project('M1-other-module')
    with pytest.raises(Denied,match='FENCING_MISMATCH'):a.submit(s,b['token'],dict(b['identity'],epoch=True),b'x')
    with pytest.raises(Denied,match='FENCING_MISMATCH'):a.submit(s,b['token'],dict(b['identity'],attempt_id='old'),b'x')
    with pytest.raises(Denied,match='IDEMPOTENCY_CONFLICT'):begin(rig,amount=1001)
    with pytest.raises(Denied,match='ATTEMPT_UNRESOLVED'):begin(rig,request='r2')

def test_unknown_retains_hold_across_restart_and_settles(rig):
    a,k,n,s=rig;b=begin(rig);a.submit(s,b['token'],b['identity'],b'x')
    a=Authority(a.path,a.anchor,k,lambda:n[0],offline_test=True);a.recover()
    with pytest.raises(Denied,match='UNKNOWN_RETAINS_BUDGET'):a.cancel(b['identity']['attempt_id'])
    with pytest.raises(Denied,match='ATTEMPT_UNRESOLVED'):a.begin(s,'M1','page','r2',1,['inputs/c2.json'])
    assert a.totals()['held']==1000
    a.settle(b['identity']['attempt_id'],1000,'receipt');assert a.totals()['spent']==1000

def test_backup_restore_retains_revocation_and_rejects_old_snapshot(rig,tmp_path):
    a,k,n,s=rig;b=begin(rig);backup=tmp_path/'old.sqlite';a.backup(backup)
    a.revoke(b['token']);latest=tmp_path/'latest.sqlite';a.backup(latest)
    # Restore at exact same owning path; retain separate current anchor.
    a.path.write_bytes(latest.read_bytes())
    reopened=Authority(a.path,a.anchor,k,lambda:n[0],offline_test=True)
    with pytest.raises(Denied,match='TOKEN_REVOKED'):reopened.read(s,b['token'],b['identity'],'inputs/c2.json')
    # Read denial has same clock/status and no new audit, current state unchanged.
    anchor=a.anchor.read_bytes();a.path.write_bytes(backup.read_bytes())
    for _ in range(2):
        with pytest.raises(Denied,match='ROLLBACK_DETECTED'):Authority(a.path,a.anchor,k,lambda:n[0],offline_test=True)
        assert a.anchor.read_bytes()==anchor

def test_failure_rolls_back_partial_business_writes(rig,monkeypatch):
    a,k,n,s=rig
    monkeypatch.setattr(k,'sign',lambda *args: (_ for _ in ()).throw(Denied('KMS_DOWN')))
    with pytest.raises(Denied,match='KMS_DOWN'):begin(rig)
    assert a.totals()['held']==0
    with a.tx() as db:
        assert db.execute('SELECT count(*) FROM attempts').fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM tokens WHERE kind='attempt'").fetchone()[0]==0

def test_failed_before_dispatch_releases_once(rig):
    a,k,n,s=rig;b=begin(rig);a.cancel(b['identity']['attempt_id']);a.cancel(b['identity']['attempt_id'])
    assert a.totals()==dict(spent=0,held=0,available=15000)

def test_bad_settlement_and_duplicate_receipt(rig):
    a,k,n,s=rig;b=begin(rig);a.submit(s,b['token'],b['identity'],b'x')
    with pytest.raises(Denied,match='INVALID_SETTLEMENT'):a.settle(b['identity']['attempt_id'],1001,'r')
    assert a.totals()['held']==1000
    a.settle(b['identity']['attempt_id'],1000,'r')
    c=begin(rig,request='r2');a.submit(s,c['token'],c['identity'],b'x')
    with pytest.raises(Denied,match='RECEIPT_REPLAY'):a.settle(c['identity']['attempt_id'],1000,'r')
    assert a.totals()==dict(spent=1000,held=1000,available=13000)

def test_production_and_missing_state_denied(rig,tmp_path):
    a,k,n,s=rig
    with pytest.raises(Denied,match='PRODUCTION_BLOCKED'):Authority(a.path,a.anchor,k,lambda:1000)
    with pytest.raises(Denied,match='UNPROVISIONED'):Authority(tmp_path/'missing',a.anchor,k,lambda:1000,offline_test=True)

def test_real_process_crash_before_commit_rolls_back(rig):
    a,k,n,s=rig
    code="import sqlite3,os,sys; d=sqlite3.connect(sys.argv[1]);d.execute('BEGIN IMMEDIATE');d.execute(\"UPDATE projects SET spent=15000\");os._exit(7)"
    result=subprocess.run([sys.executable,'-B','-c',code,str(a.path)],capture_output=True)
    assert result.returncode==7 and a.totals()['spent']==0

def test_second_process_reads_durable_budget(rig):
    a,k,n,s=rig;begin(rig,amount=15000)
    code="import sqlite3,sys;d=sqlite3.connect(sys.argv[1]);print(d.execute('SELECT sum(amount) FROM reservations').fetchone()[0])"
    result=subprocess.run([sys.executable,'-B','-c',code,str(a.path)],capture_output=True,text=True,check=True)
    assert result.stdout.strip()=='15000'
    with pytest.raises(Denied,match='BUDGET_EXHAUSTED'):begin(rig,request='r2',page='p2',amount=1)

# Real Gate fixture: public models, frozen Sidecar and real policy code, no paid model.
from orchestrator.tests.test_m1_gate_authorization import rig as gate_rig
from orchestrator.services.integration_reference.bridge import begin_from_gate
from orchestrator.services.vision_supervisor.supervisor import VisionError

def test_real_gate_to_generation_budget_asset_result(rig,gate_rig):
    a,k,n,s=rig;r=gate_rig
    b=begin_from_gate(a,r.gate,r.record,r.fences,r.c1,r.c2,(96,128),service=s,project='M1',request_id='gate-e2e',amount=500)
    for field in ('job_id','page_id','generation_id','input_revision','epoch'):
        assert b['identity'][field]==getattr(r.identity,field)
    assert b['identity']['attempt_id'] not in (r.c1.identity.attempt_id,r.c2.identity.attempt_id)
    assert b['identity']['fencing_token'] not in (r.c1.identity.fencing_token,r.c2.identity.fencing_token)
    prefix='upstream/'+r.identity.generation_id+'/'+r.identity.attempt_id
    assert a.read(s,b['token'],b['identity'],prefix+'/c2.json')==r.c2.documents['c2']
    a.submit(s,b['token'],b['identity'],b'fixture-result');a.settle(b['identity']['attempt_id'],300,'offline-gate-receipt')
    assert a.totals()==dict(spent=300,held=0,available=14700)

def test_real_gate_denial_cannot_reserve(rig,gate_rig):
    from dataclasses import replace
    a,k,n,s=rig;r=gate_rig
    bad=json.loads(r.c2.documents['c2']);bad['safety']['pass']=False
    c2=replace(r.c2,documents=dict(r.c2.documents,c2=json.dumps(bad).encode()))
    with pytest.raises(VisionError):
        begin_from_gate(a,r.gate,r.record,r.fences,r.c1,c2,(96,128),service=s,project='M1',request_id='bad',amount=500)
    assert a.totals()['held']==0

def test_service_revocation(rig):
    a,k,n,s=rig;b=begin(rig);a.revoke(s,kind='service');a.revoke(s,kind='service')
    with pytest.raises(Denied,match='TOKEN_REVOKED'):a.read(s,b['token'],b['identity'],'inputs/c2.json')

def test_atomic_anchor_publication_failure_blocks_reopen(rig,monkeypatch):
    import orchestrator.services.integration_reference.authority as impl
    a,k,n,s=rig;original=impl.os.replace
    def fail(*args): raise OSError('injected anchor IO failure')
    monkeypatch.setattr(impl.os,'replace',fail)
    with pytest.raises(OSError):begin(rig)
    monkeypatch.setattr(impl.os,'replace',original)
    assert a.totals()['held']==0

def test_anchor_commit_gap_fails_closed(rig,monkeypatch):
    a,k,n,s=rig;original=a._write_anchor
    def fail_after_publish(value): original(value);raise OSError('crash after anchor publish')
    monkeypatch.setattr(a,'_write_anchor',fail_after_publish)
    with pytest.raises(OSError):begin(rig)
    with pytest.raises(Denied,match='ROLLBACK_DETECTED'):Authority(a.path,a.anchor,k,lambda:n[0],offline_test=True)

def test_prompt_binding_and_signed_offline_provenance(rig):
    a,k,n,s=rig;b=begin(rig,final_messages=[{'content':' exact ','role':'user'}])
    with pytest.raises(Denied,match='IDEMPOTENCY_CONFLICT'):begin(rig,final_messages=[{'role':'user','content':'exact'}])
    a.submit(s,b['token'],b['identity'],b'output')
    proof=a.provenance(s,b['token'],b['identity'])
    doc=a.verify_provenance(proof,expected_identity=b['identity'],expected_result=b'output')
    assert doc['provider']=='fixture' and doc['source_mode']=='fixture'
    with pytest.raises(Denied,match='PROVENANCE_MISMATCH'):a.verify_provenance(proof,expected_identity=b['identity'],expected_result=b'other')
    tampered=dict(proof,signature='00'*64)
    with pytest.raises(Denied,match='INVALID_SIGNATURE'):a.verify_provenance(tampered,expected_identity=b['identity'],expected_result=b'output')
    k.revoke('offline-1')
    with pytest.raises(Denied,match='UNKNOWN_KEY'):a.verify_provenance(proof,expected_identity=b['identity'],expected_result=b'output')

def test_no_paid_provider_can_be_selected(rig):
    with pytest.raises(Denied,match='PROVIDER_BLOCKED'):begin(rig,provider='real')
    assert rig[0].totals()['held']==0

def test_cross_process_authorities_cannot_multiply_budget(rig):
    a,k,n,s=rig
    code='''import sys
from orchestrator.services.integration_reference import Authority,OfflineKMS,Denied
x=Authority(sys.argv[1],sys.argv[2],OfflineKMS(seed=b'm1-shared-offline-fixture-root-seed'),lambda:1000,offline_test=True)
s=x.service_token('M3')
try:
 x.begin(s,'M1','process'+sys.argv[3],'process-request'+sys.argv[3],4000,['inputs/c2.json'])
 print('ACCEPTED')
except Denied as e:
 print(str(e))
'''
    processes=[subprocess.Popen([sys.executable,'-B','-c',code,str(a.path),str(a.anchor),str(i)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for i in range(8)]
    results=[]
    for p in processes:
        out,err=p.communicate(timeout=40);assert p.returncode==0,err;results.append(out.strip())
    assert results.count('ACCEPTED')==3 and results.count('BUDGET_EXHAUSTED')==5
    assert a.totals()['held']==12000

def test_audited_denial_does_not_log_tokens(rig):
    a,k,n,s=rig;b=begin(rig)
    with pytest.raises(Denied):a.read(s,b['token'],b['identity'],'private/secret')
    with a.tx() as db:
        raw=db.execute('SELECT payload FROM events ORDER BY seq DESC LIMIT 1').fetchone()[0]
        assert json.loads(raw)['kind']=='denied' and s not in raw and b['token'] not in raw

@pytest.mark.parametrize('environment',['dev','production','unknown'])
def test_mock_assets_never_enabled_in_deployed_modes(monkeypatch,tmp_path,environment):
    from orchestrator.core.config import Settings
    from orchestrator.services.vision_supervisor.authorization.asset_policy import offline_mock_enabled
    monkeypatch.setenv('M1_DEPLOYMENT_ENV',environment);monkeypatch.setenv('M1_ASSET_MODE','offline_mock')
    assert not offline_mock_enabled()
    with pytest.raises(ValueError):Settings(data_dir=tmp_path)

@pytest.mark.parametrize('environment',['dev','production'])
def test_deployed_blocked_mode_still_allowed(monkeypatch,tmp_path,environment):
    from orchestrator.core.config import Settings
    monkeypatch.setenv('M1_DEPLOYMENT_ENV',environment);monkeypatch.setenv('M1_ASSET_MODE','blocked')
    assert Settings(data_dir=tmp_path).asset_mode=='blocked'

# Completion-audit regressions: these are required behavior, not report assertions.
def test_submitted_unbilled_attempt_cannot_be_replaced(rig):
    a,k,n,s=rig;b=begin(rig);a.submit(s,b['token'],b['identity'],b'output')
    with pytest.raises(Denied,match='ATTEMPT_UNRESOLVED'):begin(rig,request='replacement')
    assert a.totals()['held']==1000

def test_completed_submit_retry_keeps_original_result_and_single_charge(rig):
    a,k,n,s=rig;b=begin(rig)
    result=a.submit(s,b['token'],b['identity'],b'output')
    a.settle(b['identity']['attempt_id'],700,'receipt')
    assert a.submit(s,b['token'],b['identity'],b'output')==result
    with pytest.raises(Denied,match='IDEMPOTENCY_CONFLICT'):a.submit(s,b['token'],b['identity'],b'changed')
    assert a.totals()==dict(spent=700,held=0,available=14300)

def test_retired_key_identifier_never_reused(rig):
    a,k,n,s=rig;k.revoke('offline-1')
    with pytest.raises(Denied,match='KEY_ID_REUSE'):k.rotate('offline-1')

def test_bridge_denied_service_cannot_register_assets(rig,gate_rig):
    a,k,n,s=rig;r=gate_rig
    with a.tx() as db:before=[tuple(row) for row in db.execute('SELECT * FROM assets ORDER BY name')]
    with pytest.raises(Denied):
        begin_from_gate(a,r.gate,r.record,r.fences,r.c1,r.c2,(96,128),service='invalid',project='M1',request_id='unauth',amount=500)
    with a.tx() as db:assert [tuple(row) for row in db.execute('SELECT * FROM assets ORDER BY name')]==before

def test_replayed_begin_never_returns_superseded_attempt(rig):
    a,k,n,s=rig;b=begin(rig);a.submit(s,b['token'],b['identity'],b'output');a.settle(b['identity']['attempt_id'],700,'r')
    begin(rig,request='replacement')
    with pytest.raises(Denied,match='STALE_ATTEMPT'):begin(rig)

def test_authorized_native_file_read_and_wrong_version(rig,tmp_path):
    from orchestrator.services.integration_reference.files import WindowsAssetReader
    a,k,n,s=rig;b=begin(rig);(tmp_path/'inputs').mkdir();p=tmp_path/'inputs/c2.json';p.write_bytes(b'fixture')
    reader=WindowsAssetReader(tmp_path)
    assert a.read_file(s,b['token'],b['identity'],'inputs/c2.json',reader)==b'fixture'
    p.write_bytes(b'wrong')
    with pytest.raises(Denied,match='ASSET_VERSION'):a.read_file(s,b['token'],b['identity'],'inputs/c2.json',reader)

def test_native_files_reject_hardlinks(rig,tmp_path):
    from orchestrator.services.integration_reference.files import WindowsAssetReader
    source=tmp_path/'source';source.write_bytes(b'fixture');(tmp_path/'alias').hardlink_to(source)
    with pytest.raises(Denied,match='FILE_HARDLINK_DENIED'):WindowsAssetReader(tmp_path).read_bytes('alias')

def test_native_files_reject_junction_ancestor(rig,tmp_path):
    from orchestrator.services.integration_reference.files import WindowsAssetReader
    target=tmp_path/'outside';target.mkdir();(target/'secret').write_bytes(b'private')
    root=tmp_path/'root';root.mkdir();link=root/'link'
    completed=subprocess.run(['cmd','/d','/c','mklink','/J',str(link),str(target)],capture_output=True)
    assert completed.returncode==0,completed.stderr
    try:
        with pytest.raises(Denied,match='FILE_REPARSE_DENIED'):WindowsAssetReader(root).read_bytes('link/secret')
    finally:link.rmdir()

def test_native_file_reader_not_called_without_authorization(rig):
    a,k,n,s=rig;b=begin(rig)
    class NeverRead:
        def read_bytes(self,name):pytest.fail('unauthorized request reached native IO')
    with pytest.raises(Denied):a.read_file('invalid',b['token'],b['identity'],'inputs/c2.json',NeverRead())

def test_native_file_rechecks_revocation_after_io(rig):
    a,k,n,s=rig;b=begin(rig)
    class RevokeDuringRead:
        def read_bytes(self,name):a.revoke(b['token']);return b'fixture'
    with pytest.raises(Denied,match='TOKEN_REVOKED'):a.read_file(s,b['token'],b['identity'],'inputs/c2.json',RevokeDuringRead())

@pytest.mark.parametrize('name',['../secret','C:/secret','inputs\\c2.json','inputs/c2.json:secret','CON','LPT1.txt','nul.json','a\x00b'])
def test_native_reader_rejects_name_aliases(tmp_path,name):
    from orchestrator.services.integration_reference.files import WindowsAssetReader
    with pytest.raises(Denied):WindowsAssetReader(tmp_path).read_bytes(name)

def test_native_file_limits_and_missing_files(tmp_path):
    from orchestrator.services.integration_reference.files import WindowsAssetReader
    p=tmp_path/'large';p.write_bytes(b'abcd')
    with pytest.raises(Denied,match='FILE_TOO_LARGE'):WindowsAssetReader(tmp_path,max_bytes=3).read_bytes('large')
    with pytest.raises(Denied,match='FILE_OPEN_DENIED'):WindowsAssetReader(tmp_path).read_bytes('missing')

def test_native_handle_denies_concurrent_write_and_replace(tmp_path,monkeypatch):
    from orchestrator.services.integration_reference.files import WindowsAssetReader,kernel
    p=tmp_path/'asset';p.write_bytes(b'original');replacement=tmp_path/'replacement';replacement.write_bytes(b'attacker')
    original=kernel.ReadFile;observed=[]
    def read(*args):
        for operation in (lambda:p.write_bytes(b'attacker'),lambda:replacement.replace(p)):
            try:operation()
            except OSError:observed.append('blocked')
            else:pytest.fail('Pinned read handle allowed write or replacement')
        return original(*args)
    monkeypatch.setattr(kernel,'ReadFile',read)
    assert WindowsAssetReader(tmp_path).read_bytes('asset')==b'original'
    assert observed==['blocked','blocked']

def test_backup_snapshot_serializes_concurrent_writer(rig,tmp_path,monkeypatch):
    import threading
    a,k,n,s=rig;b=begin(rig);entered=threading.Event();release=threading.Event()
    original=a._state;backup_path=tmp_path/'snapshot.sqlite';anchor=a.anchor.read_bytes()
    def state(db):
        result=original(db)
        if threading.current_thread().name=='snapshot-owner':
            entered.set();assert release.wait(5)
        return result
    monkeypatch.setattr(a,'_state',state)
    errors=[]
    def backup():
        try:a.backup(backup_path)
        except BaseException as e:errors.append(e)
    t=threading.Thread(target=backup,name='snapshot-owner');t.start();assert entered.wait(5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(a.cancel,b['identity']['attempt_id'])
        assert not future.done()
        release.set();t.join(8);future.result(timeout=8)
    assert not errors and not t.is_alive()
    # Backup is the exact pre-cancel state; live DB advances and retains revocation.
    with sqlite3.connect(backup_path) as db:
        assert original(db)==anchor.decode()
        assert db.execute("SELECT state FROM attempts").fetchone()[0]=='RESERVED'
    with a.tx() as db:assert db.execute("SELECT state FROM attempts").fetchone()[0]=='CANCELLED'

def test_deterministic_offline_identity_and_kms_access_audit():
    one=OfflineKMS(seed=b'deterministic-offline-test-seed-32-bytes')
    two=OfflineKMS(seed=b'deterministic-offline-test-seed-32-bytes')
    payload=b'fixture';signature=one.sign('offline-1',payload)
    assert signature==two.sign('offline-1',payload)
    two.public_keys()['offline-1'].verify(signature,payload)
    one.verify('offline-1',signature,payload)
    one.revoke('offline-1');one.revoke('offline-1')
    with pytest.raises(Denied,match='UNKNOWN_KEY'):one.sign('offline-1',payload)
    assert [e['action'] for e in one.audit]==['rotate','sign','verify','revoke','sign']
    assert one.audit[-1]['outcome']=='DENY'
    assert all(set(e)=={'seq','component','action','key_id','outcome'} for e in one.audit)

def test_transient_windows_anchor_sharing_denial_retries_without_double_reservation(rig,monkeypatch):
    import orchestrator.services.integration_reference.authority as impl
    a,k,n,s=rig;original=impl.os.replace;calls=[]
    def replace(*args):
        calls.append(1)
        if len(calls)<=2:raise PermissionError('injected sharing violation')
        return original(*args)
    monkeypatch.setattr(impl.os,'replace',replace)
    b=begin(rig);assert len(calls)==3
    assert a.totals()['held']==1000
    assert begin(rig)==b

def test_native_reader_rejects_junction_above_selected_root(tmp_path):
    from orchestrator.services.integration_reference.files import WindowsAssetReader
    outside=tmp_path/'outside';(outside/'private').mkdir(parents=True);(outside/'private/asset').write_bytes(b'fixture')
    alias=tmp_path/'alias'
    p=subprocess.run(['cmd','/d','/c','mklink','/J',str(alias),str(outside)],capture_output=True)
    assert p.returncode==0,p.stderr
    try:
        with pytest.raises(Denied,match='FILE_PATH_DENIED'):WindowsAssetReader(alias/'private').read_bytes('asset')
    finally:alias.rmdir()


def test_native_reader_remains_on_pinned_root_if_ancestor_moves(tmp_path,monkeypatch):
    from orchestrator.services.integration_reference.files import WindowsAssetReader,kernel
    parent=tmp_path/'parent';root=parent/'owned';root.mkdir(parents=True);(root/'asset').write_bytes(b'original')
    reader=WindowsAssetReader(root);original=kernel.ReadFile;observed=[]
    def read(*args):
        try:parent.rename(tmp_path/'moved')
        except OSError:observed.append('rename-denied')
        else:
            observed.append('ancestor-moved');root.mkdir(parents=True);(root/'asset').write_bytes(b'attacker')
        return original(*args)
    monkeypatch.setattr(kernel,'ReadFile',read)
    assert reader.read_bytes('asset')==b'original'
    assert observed in (['rename-denied'],['ancestor-moved'])

def test_native_reader_rejects_network_drive_before_io(tmp_path,monkeypatch):
    from orchestrator.services.integration_reference.files import WindowsAssetReader,kernel
    monkeypatch.setattr(kernel,'GetDriveTypeW',lambda root:4)
    with pytest.raises(Denied,match='FILE_PLATFORM_UNSUPPORTED'):WindowsAssetReader(tmp_path)


def test_native_reader_rejects_unvalidated_filesystem(tmp_path,monkeypatch):
    from orchestrator.services.integration_reference.files import WindowsAssetReader,kernel
    def volume(*args):args[6].value='ReFS';return 1
    monkeypatch.setattr(kernel,'GetVolumeInformationW',volume)
    with pytest.raises(Denied,match='FILE_PLATFORM_UNSUPPORTED'):WindowsAssetReader(tmp_path)

def test_resigning_old_token_under_new_key_cannot_bypass_revoked_issuer(rig):
    import json
    from orchestrator.services.poc_security.crypto import canonical,parse
    a,k,n,service=rig
    claims=parse(bytes.fromhex(json.loads(service)['body']))
    k.rotate('offline-2');k.revoke('offline-1')
    claims['key_id']='offline-2';body=canonical(claims)
    resigned=json.dumps(dict(body=body.hex(),signature=k.sign('offline-2',body).hex()))
    with pytest.raises(Denied,match='TOKEN_KEY_MISMATCH'):
        a.begin(resigned,'M1','page','resigned-service',100,['inputs/c2.json'])
