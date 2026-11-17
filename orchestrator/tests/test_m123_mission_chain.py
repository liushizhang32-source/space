"""Actual HTTP Jobs -> pinned M2 subprocess -> Gate/Session -> M3 media.

Offline KMS, fixture vision and silent TTS only. No accounting consumer is faked.
"""
import hashlib,io,json,os,time
from pathlib import Path
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from orchestrator.main import create_app
from orchestrator.core.config import Settings
from orchestrator.services.vision_supervisor.gate import Gate
from orchestrator.vendor.member3_v116.tests import m1_offline_rig as fixtures
from orchestrator.vendor.member3_v116.agents.generation.m1_generation import M1GenerationConsumer
from orchestrator.vendor.member3_v116.agents.generation.m1_pipeline import open_session
from orchestrator.tests.m2_mission_support import process,SOURCE
from orchestrator.tests.test_member3_m1_callchain import terminal

@pytest.mark.parametrize('pages',[[3],[3,4]])
def test_HTTP_actual_worker_generation_media_and_unknown_retained(tmp_path,monkeypatch,pages):
    data=io.BytesIO();Image.new('RGB',(96,128),'white').save(data,format='PNG');image=data.getvalue()
    rig=fixtures.make_rig(tmp_path/'authority',page_no=99);sessions=[];dispatches=[]
    def factory(*,page_id,job_id,request_id):
        path=tmp_path/(page_id+'.png');path.write_bytes(image)
        record,c1,c2,handoff,events=process(rig,tmp_path/page_id,page_id,job_id,path)
        dispatches.extend(events)
        consumer=M1GenerationConsumer(rig.authority,Gate({SOURCE}),rig.fences,record,service_token=rig.service_token)
        s=open_session(consumer,page_id=page_id,request_id=request_id,amount=1000,
            c1=c1,c2=c2,size=(96,128),image=image,
            final_messages=[{'role':'user','content':'明确声明的离线fixture故事'}])
        sessions.append(s);return s
    app=create_app(Settings(data_dir=tmp_path/'data',generation_backend='member3',asset_base_url='http://testserver',
        deployment_env='local',asset_mode='offline_mock',queue_delay=.001,stage_delay=.001,
        ffmpeg_path=os.environ['FFMPEG_PATH'],ffprobe_path=os.environ['FFPROBE_PATH']),m1_session_factory=factory)
    with TestClient(app) as client:
        ids=[f'book01_p{p:02d}' for p in pages]
        for p in pages:
            assert client.post('/api/v1/capture',data={'book_id':'book01','page_no':p},files={'image':('page.png',image,'image/png')}).json()['code']==0
        response=client.post('/api/v1/generate',json={'page_ids':ids,'age_level':'3-6','force':False}).json()
        assert response['code']==0,response
        jid=response['data']['job_id'];job=terminal(client,jid)
        assert job['status']=='done',job
        assert len(sessions)==len(pages)
        assert sum(e['event']=='started' for e in dispatches)==2*len(pages)
        for pid in ids:
            raw=(tmp_path/'data/json'/f'{pid}_story.json').read_bytes()
            receipt=app.state.jobs.m1_receipts[(jid,pid)]
            assert hashlib.sha256(raw).hexdigest()==receipt['m1_result_sha256']
            assert receipt['submission_state']=='UNKNOWN'
            story=client.get('/json/'+pid+'_story.json')
            assert story.status_code==200 and story.content==raw
            assert client.get('/videos/'+pid+'_video.mp4').status_code==200
        assert rig.authority.totals()['held']==1000*len(pages)
        assert rig.authority.totals()['spent']==0
        audit=Path(os.environ['MISSION_EVIDENCE'])/'joint-receipts.jsonl'
        with audit.open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(job_id=jid,pages=ids,receipts=list(app.state.jobs.m1_receipts.values()),budget=rig.authority.totals(),worker_processes=2*len(pages),model_mode='fixture',accounting_handoff='BLOCKED'),ensure_ascii=False)+'\n')
