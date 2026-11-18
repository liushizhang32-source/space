"""New source-bound validation, not a relabelling of the historical 266 XML."""
import hashlib
import threading
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import pytest
from PIL import Image
from orchestrator.vendor.member3_v116.tests.m1_offline_rig import make_rig
from orchestrator.services.vision_supervisor.supervisor import VisionError,Cancelled
from orchestrator.services.vision_supervisor.durable import DurableSupervisor
from orchestrator.services.vision_supervisor.gate import Gate
from orchestrator.tests.m2_mission_support import process,spec,SOURCE

@pytest.fixture
def vision(tmp_path):
    image=tmp_path/'page.png';Image.new('RGB',(96,128),'white').save(image)
    return make_rig(tmp_path/'m1',page_no=99),image

def test_real_M2_cli_ocr_vlm_gate(vision,tmp_path):
    rig,image=vision
    record,c1,c2,handoff,events=process(rig,tmp_path,'book01_p03','actual-m2-job',image)
    assert b'FIXTURE TEXT' in handoff.c1
    assert handoff.c2_sha256==hashlib.sha256(c2.documents['c2']).hexdigest()
    assert c1.identity.attempt_id!=c2.identity.attempt_id
    assert sum(e['event']=='started' for e in events)==2
    assert record.worker_state=='reaped'

def test_real_M2_stub_safety_failure_has_no_consumable_C2(vision,tmp_path):
    rig,image=vision;record,_=rig.fences.begin('blocked','book01_p03')
    s=DurableSupervisor(tmp_path/'worker',authority=rig.authority,deadline=10)
    c1=s.run(record,rig.fences,'ocr',lambda n:spec(n,backend='stub'),image)
    with pytest.raises(VisionError) as exc:
        s.run(record,rig.fences,'vlm',lambda n:spec(n,backend='stub'),image,c1=c1)
    assert exc.value.code==3004 and record.worker_state=='reaped'
    assert record.c2_sha256 is None

def test_real_M2_deadline_reaps_tree_and_persists_retry_limit(vision,tmp_path):
    rig,image=vision;record,_=rig.fences.begin('deadline','book01_p03');events=[]
    s=DurableSupervisor(tmp_path/'worker',authority=rig.authority,deadline=.001,audit=events.append)
    with pytest.raises(VisionError) as exc:s.run(record,rig.fences,'ocr',spec,image)
    assert exc.value.code==2002 and record.worker_state=='reaped'
    assert sum(e['event']=='started' for e in events)==2
    again=DurableSupervisor(tmp_path/'restart',authority=rig.reopen().authority,deadline=10)
    with pytest.raises(VisionError,match='STAGE_LIMIT'):
        again.run(record,rig.fences,'ocr',spec,image)

def test_real_M2_cancel_and_old_identity_rejected(vision,tmp_path):
    rig,image=vision;record,_=rig.fences.begin('cancel','book01_p03');started=threading.Event()
    def audit(event):
        if event['event']=='started':started.set();rig.fences.cancel(record)
    s=DurableSupervisor(tmp_path/'worker',authority=rig.authority,deadline=10,audit=audit)
    with pytest.raises(Cancelled):s.run(record,rig.fences,'ocr',spec,image)
    assert started.is_set() and record.worker_state=='reaped'
    with pytest.raises(Cancelled):rig.fences.check(record,record.identity)

def test_real_M2_two_pages_concurrent_do_not_mix_hashes(vision,tmp_path):
    rig,image=vision
    def run(no):return process(rig,tmp_path/str(no),f'book01_p{no:02d}',f'job{no}',image)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[3,4]))
    assert {x[3].identity.page_id for x in results}=={'book01_p03','book01_p04'}
    for record,c1,c2,handoff,events in results:
        assert handoff.identity==record.identity
        assert handoff.c2_sha256==hashlib.sha256(c2.documents['c2']).hexdigest()
