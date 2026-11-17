"""Fault cases retain real M2 CLI dispatch; only fault boundaries are injected.

Test-only trusted callback assembly, not a production Session service.
"""
import hashlib,io,json,os,threading
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from orchestrator.main import create_app
from orchestrator.core.config import Settings
from orchestrator.core.errors import APIError
from orchestrator.services import member3_adapter as adapter
from orchestrator.services.vision_supervisor.gate import Gate
from orchestrator.services.vision_supervisor.supervisor import VisionError
from orchestrator.vendor.member3_v116.tests import m1_offline_rig as fixtures
from orchestrator.vendor.member3_v116.agents.generation import pipeline
from orchestrator.vendor.member3_v116.agents.generation.errors import StoryInputError,TTSUnavailable,AppError,ErrorCode
from orchestrator.vendor.member3_v116.agents.generation.m1_generation import M1GenerationConsumer
from orchestrator.vendor.member3_v116.agents.generation.m1_pipeline import open_session
from orchestrator.tests.m2_mission_support import process,SOURCE
from orchestrator.tests.test_member3_m1_callchain import terminal,_drain

@pytest.mark.parametrize('fault',['ocr','timeout','story','tts','video','duplicate','cancel'])
def test_actual_M2_chain_fault_boundaries(tmp_path,monkeypatch,fault):
    image=io.BytesIO();Image.new('RGB',(96,128),'white').save(image,format='PNG');raw_image=image.getvalue()
    rig=fixtures.make_rig(tmp_path/'m1',page_no=99);sessions=[];calls=[]
    entered,release=threading.Event(),threading.Event()
    def factory(*,page_id,job_id,request_id):
        path=tmp_path/'input.png';path.write_bytes(b'invalid-image' if fault=='ocr' else raw_image)
        try:record,c1,c2,handoff,events=process(rig,tmp_path/'vision',page_id,job_id,path,deadline=.001 if fault=='timeout' else 10)
        except VisionError as exc:raise APIError(exc.code,exc.msg) from exc
        calls.extend(events)
        consumer=M1GenerationConsumer(rig.authority,Gate({SOURCE}),rig.fences,record,service_token=rig.service_token)
        s=open_session(consumer,page_id=page_id,request_id=request_id,amount=1000,c1=c1,c2=c2,
            size=(96,128),image=raw_image,final_messages=[{'role':'user','content':'离线fixture故障验证'}])
        sessions.append(s);return s
    if fault=='story':
        def bad_story(*args,**kwargs):raise StoryInputError('injected story failure')
        monkeypatch.setattr(pipeline,'build_page_story',bad_story)
    if fault=='tts':
        def bad_tts(*args,**kwargs):raise TTSUnavailable('injected TTS failure')
        monkeypatch.setattr(adapter.TTSClient,'synthesize',bad_tts)
    if fault=='video':
        def bad_video(*args,**kwargs):raise AppError(ErrorCode.VIDEO_FAILED,'injected video failure')
        monkeypatch.setattr(adapter,'compose_video',bad_video)
    if fault=='cancel':
        original=adapter.compose_video
        def blocked_video(*args,**kwargs):
            entered.set();assert release.wait(15);return original(*args,**kwargs)
        monkeypatch.setattr(adapter,'compose_video',blocked_video)
    app=create_app(Settings(data_dir=tmp_path/'data',generation_backend='member3',queue_delay=.05,stage_delay=.001,
        asset_mode='blocked',ffmpeg_path=os.environ['FFMPEG_PATH'],ffprobe_path=os.environ['FFPROBE_PATH']),m1_session_factory=factory)
    with TestClient(app) as client:
        assert client.post('/api/v1/capture',data={'book_id':'book01','page_no':3},files={'image':('page.png',raw_image,'image/png')}).json()['code']==0
        body={'page_ids':['book01_p03'],'age_level':'3-6','force':False}
        jid=client.post('/api/v1/generate',json=body).json()['data']['job_id']
        if fault=='duplicate':assert client.post('/api/v1/generate',json=body).json()['data']['job_id']==jid
        if fault=='cancel':
            assert entered.wait(15)
            client.portal.call(app.state.jobs.tasks[jid].cancel);release.set()
            client.portal.call(lambda:_drain(app.state.jobs.tasks[jid]))
        job=terminal(client,jid)
        if fault in {'ocr','timeout'}:
            assert job['status']=='failed' and sessions==[]
            assert job['pages'][0]['error']['code']==(1006 if fault=='ocr' else 2002)
            assert rig.authority.totals()['held']==0
        elif fault=='story':
            assert job['status']=='failed' and rig.authority.totals()['held']==0
        elif fault=='tts':
            assert job['pages'][0]['status']=='partial'
            assert 'no_audio' in job['pages'][0]['degraded']
        elif fault=='video':
            # Existing rendering contract retains a submitted Story on ordinary
            # video failure (test_member3_integration.py); safety failure differs.
            assert job['status']=='partial_failed'
            assert job['pages'][0]['video_url'] is None
            assert job['pages'][0]['error']['code']==3007
            assert 'no_video' in job['pages'][0]['degraded']
        elif fault=='cancel':assert job['status']=='cancelled'
        else:assert job['status']=='done' and len(sessions)==1
        assert rig.authority.totals()['spent']==0
        if fault in {'tts','video','cancel','duplicate'}:assert rig.authority.totals()['held']==1000
        path=tmp_path/'data/json/book01_p03_story.json'
        if fault in {'tts','video','duplicate'}:
            assert hashlib.sha256(path.read_bytes()).hexdigest()==sessions[0].attempt.result_sha256
        else:assert not path.exists()
        denied=client.get('/json/book01_p03_story.json')
        assert denied.status_code==503 and denied.json()['status']=='BLOCKED'
        dest=__import__('pathlib').Path(os.environ['MISSION_EVIDENCE'])/'joint-fault-observations.jsonl'
        with dest.open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(fault=fault,job=job,budget=rig.authority.totals(),sessions=len(sessions),model='fixture',accounting='BLOCKED'),ensure_ascii=False)+'\n')
