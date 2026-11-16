"""Lost responses at real offline API boundaries; no paid or HTTP provider.

Authentication, project authorization, token validation, hold and attempt creation
are one begin transaction. They must never be split into independently committed
steps just to populate an acceptance matrix.
"""
import hashlib,json
import pytest
from orchestrator.tests.test_m1_integration_reference import rig
from orchestrator.tests.test_m1_shared_current import assembly,gated
from orchestrator.services.integration_reference import Authority,Denied,OfflineKMS
from orchestrator.services.integration_reference.bridge import begin_from_gate
from orchestrator.services.integration_reference.recovery import JointSnapshot
from orchestrator.services.vision_supervisor.shared import SharedFences
from orchestrator.services.vision_supervisor.pipeline import AtomicStore
from orchestrator.services.vision_supervisor.supervisor import VisionError


def audit_chain(authority):
    with authority.snapshot_guard() as (db,state):
        previous='';kinds=[]
        for row in db.execute('SELECT * FROM events ORDER BY seq'):
            assert row['previous']==previous
            assert row['hash']==hashlib.sha256((previous+row['payload']).encode()).hexdigest()
            previous=row['hash'];kinds.append(json.loads(row['payload'])['kind'])
        total=db.execute('SELECT sum(spent) FROM projects').fetchone()[0]
        held=db.execute("SELECT coalesce(sum(amount),0) FROM reservations WHERE state IN ('RESERVED','UNKNOWN')").fetchone()[0]
        assert 0<=total+held<=15000
        assert authority.anchor.read_text()==state
        return kinds


@pytest.mark.parametrize('boundary',['begin','read','submit','settle','publish','revoke','restore'])
@pytest.mark.parametrize('loss',['before_dispatch','after_commit'])
def test_timeout_restart_reconcile_and_duplicate_keep_one_charge(rig,tmp_path,boundary,loss):
    v=assembly(rig,tmp_path);a,_,f,_,record,image,worker,events,service=v
    c1,c2,gate,handoff=gated(v)
    root=tmp_path/'published';store=AtomicStore(root,f)
    producer_store=store;producer_record=record
    docs={f'json/{record.page_id}_ocr.json':handoff.c1,f'json/{record.page_id}_vlm.json':handoff.c2,
          f'json/{record.page_id}_refs.json':handoff.sidecar,'output/result.bin':b'result'}
    task=None;manifest=None;last_reply=None

    def action(name):
        nonlocal task,manifest
        if name=='begin':
            reply=begin_from_gate(a,gate,record,f,c1,c2,(96,128),service=service,project='M1',
                request_id='chain-timeout',amount=1000,image=image.read_bytes())
            task=reply;return reply
        if name=='read':
            asset='upstream/'+record.generation_id+'/'+c2.identity.attempt_id+'/c2.json'
            return a.read(service,task['token'],task['identity'],asset)
        if name=='submit':return a.submit(service,task['token'],task['identity'],b'result')
        if name=='settle':return a.settle(task['identity']['attempt_id'],700,'one-trusted-fixture-receipt')
        if name=='publish':
            # Publication has a reconciliation read, not a promised retry API.
            existing=producer_store.read(producer_record.page_id)
            if existing is not None:return existing[0]
            manifest=producer_store.publish(producer_record,c2.identity,docs,verify=lambda content:None)
            return manifest
        if name=='revoke':return a.revoke(task['token'])
        if name=='restore':
            manager=JointSnapshot.for_store(a,store)
            snapshot=tmp_path/'joint-snapshot'
            if not snapshot.exists():manager.create(snapshot)
            return manager.restore(snapshot,operation_id='chain-recovery',services_stopped=True)
        raise AssertionError(name)

    for name in ('begin','read','submit','settle','publish','revoke','restore'):
        if name==boundary:
            def lost_response():
                if loss=='after_commit':action(name)
                raise TimeoutError('offline caller did not receive a response')
            with pytest.raises(TimeoutError):lost_response()
            # Restart the consumer/control adapter, while the real local supervisor
            # retains its own drained-worker proof. Whole supervisor death is
            # tested separately and must not invent a drain proof on restore.
            a=Authority(a.path,a.anchor,OfflineKMS(seed=b'm1-shared-offline-fixture-root-seed'),lambda:rig[2][0],offline_test=True)
            f=SharedFences(a);record=f.restore(record.page_id);store=AtomicStore(root,f)
        reply=action(name)
        # Same request/result/receipt, plus a reconciled publication and restore.
        assert action(name)==reply
        kinds=audit_chain(a)
        expected=(0,1000) if name in ('begin','read','submit') else (700,0)
        totals=a.totals();assert (totals['spent'],totals['held'])==expected
        assert kinds.count('reserved')==1
        assert kinds.count('submitted')==(0 if name in ('begin','read') else 1)
        assert kinds.count('settled')==(0 if name in ('begin','read','submit') else 1)
        last_reply=reply
    assert last_reply['status']=='RESTORED_OFFLINE'
    reader_fences=SharedFences(a);reader_fences.restore(record.page_id)
    assert AtomicStore(root,reader_fences).read(record.page_id)[0]==manifest
    with pytest.raises(Denied,match='TOKEN_REVOKED'):
        a.submit(service,task['token'],task['identity'],b'result')
    audit_chain(a)


def test_restarted_supervisor_cannot_invent_drain_before_publication(rig,tmp_path):
    v=assembly(rig,tmp_path);a,_,f,_,record,image,worker,events,service=v
    c1,c2,gate,handoff=gated(v)
    restarted=SharedFences(a);restored=restarted.restore(record.page_id)
    gate.accept(restored,restarted,c1,c2,(96,128))
    docs={f'json/{record.page_id}_ocr.json':handoff.c1,f'json/{record.page_id}_vlm.json':handoff.c2,
          f'json/{record.page_id}_refs.json':handoff.sidecar,'output/result.bin':b'result'}
    store=AtomicStore(tmp_path/'published',restarted)
    with pytest.raises(VisionError,match='before worker drain'):
        store.publish(restored,c2.identity,docs,verify=lambda content:None)
    assert not list((store.root/'pointers').iterdir())
    restarted.cancel(restored)
    new,created=restarted.begin('recovered-new-job',record.page_id,force=True)
    assert created and new.epoch==record.epoch+1
    audit_chain(a)
