"""Offline integration harness; real M2 executable, explicitly fixture models."""
from pathlib import Path
import sys
from orchestrator.services.vision_supervisor.supervisor import WorkerSpec
from orchestrator.services.vision_supervisor.durable import DurableSupervisor
from orchestrator.services.vision_supervisor.gate import Gate

ROOT=Path(__file__).resolve().parents[2]
ENTRY=Path(__file__).parent/'fixtures/m2_mission_worker_entry.py'
M2=ROOT/'paperbook-ai-m2/paperbook-ai/src'
SOURCE='m2-pr9-offline-fixture'

def spec(ordinal, *, backend='fixture'):
    return WorkerSpec((sys.executable,'-I',str(ENTRY),str(M2)),SOURCE,
                      environment=(('VISION_BACKEND',backend),))

def process(rig,root,page_id,job_id,image,*,backend='fixture',deadline=10):
    record,_=rig.fences.begin(job_id,page_id)
    events=[]
    supervisor=DurableSupervisor(root/'workers',authority=rig.authority,deadline=deadline,audit=events.append)
    c1=supervisor.run(record,rig.fences,'ocr',lambda n:spec(n,backend=backend),image)
    c2=supervisor.run(record,rig.fences,'vlm',lambda n:spec(n,backend=backend),image,c1=c1)
    handoff=Gate({SOURCE}).accept(record,rig.fences,c1,c2,(96,128))
    return record,c1,c2,handoff,events
