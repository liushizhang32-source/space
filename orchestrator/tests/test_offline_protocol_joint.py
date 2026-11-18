"""M1 -> real M2 CLI -> M3 -> private positive reads -> offline settlement."""
import hashlib,io,json,os
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient
from orchestrator.main import create_app
from orchestrator.core.config import Settings
from orchestrator.services.offline_protocols.assets import PrivateAssets
from orchestrator.services.offline_protocols.billing import OfflineSettlementAdapter,ReconciliationConsumer
from orchestrator.services.vision_supervisor.gate import Gate
from orchestrator.vendor.member3_v116.tests import m1_offline_rig as fixtures
from orchestrator.vendor.member3_v116.agents.generation.m1_generation import M1GenerationConsumer
from orchestrator.vendor.member3_v116.agents.generation.m1_pipeline import open_session
from orchestrator.vendor.member3_v116.agents.generation.tts.service import create_app as tts_app
from orchestrator.vendor.member3_v116.agents.generation.config import Settings as TTSSettings
from orchestrator.tests.m2_mission_support import process,SOURCE
from orchestrator.tests.test_member3_m1_callchain import terminal

def test_full_offline_private_publication_and_consumer_settlement(tmp_path,monkeypatch):
    monkeypatch.setenv('M1_ASSET_MODE','blocked')
    im=io.BytesIO();Image.new('RGB',(96,128),'white').save(im,format='PNG');image=im.getvalue()
    rig=fixtures.make_rig(tmp_path/'m1',page_no=99);sessions=[];data=tmp_path/'data'
    assets=PrivateAssets(rig.authority,data,offline_test=True)
    consumer=ReconciliationConsumer(rig.authority,tmp_path/'inbox.sqlite',offline_test=True)
    def factory(*,page_id,job_id,request_id):
        path=tmp_path/'page.png';path.write_bytes(image)
        record,c1,c2,hand,events=process(rig,tmp_path/'workers',page_id,job_id,path)
        gen=M1GenerationConsumer(rig.authority,Gate({SOURCE}),rig.fences,record,service_token=rig.service_token)
        session=open_session(gen,page_id=page_id,request_id=request_id,amount=1000,c1=c1,c2=c2,size=(96,128),image=image,
            final_messages=[{'role':'user','content':'离线端到端验证'}])
        sessions.append(session);return session
    app=create_app(Settings(data_dir=data,generation_backend='member3',asset_base_url='http://testserver',asset_mode='blocked',
        queue_delay=.001,stage_delay=.001,ffmpeg_path=os.environ['FFMPEG_PATH'],ffprobe_path=os.environ['FFPROBE_PATH']),
        m1_session_factory=factory,m1_assets=assets)
    with TestClient(app) as client:
        client.post('/api/v1/capture',data={'book_id':'book01','page_no':3},files={'image':('page.png',image,'image/png')})
        jid=client.post('/api/v1/generate',json={'page_ids':['book01_p03'],'age_level':'3-6','force':False}).json()['data']['job_id']
        job=terminal(client,jid);assert job['status']=='done',job
        session=sessions[0];attempt=session.attempt
        story_raw=(data/'json/book01_p03_story.json').read_bytes();story=json.loads(story_raw)
        assert hashlib.sha256(story_raw).hexdigest()==attempt.result_sha256
        assert client.get('/json/book01_p03_story.json').status_code==503
        journal=data/'.member3/m1-reconciliation.jsonl'
        assert consumer.ingest_observations(journal,'M3-journal')==1
        assert consumer.ingest_observations(journal,'M3-journal')==0
        assert rig.authority.totals()['held']==1000 and rig.authority.totals()['spent']==0
        audio='audios/'+story['segments'][0]['audio_url'].rsplit('/',1)[-1]
        refs=[('audio1',audio,'audio/mpeg'),('video1','videos/book01_p03_video.mp4','video/mp4'),('story1','json/book01_p03_story.json','application/json')]
        tokenmap={};hashes={}
        for aid,name,mime in refs:
            raw=(data/name).read_bytes();hashes[aid]=hashlib.sha256(raw).hexdigest()
            assets.register_output(rig.service_token,attempt.token,dict(attempt.identity),dict(asset_id=aid,project_id='M1',job_id=jid,
                attempt_id=attempt.attempt_id,sha256=hashes[aid],relative_path=name,content_type=mime))
            tokenmap[aid]=assets.issue(rig.service_token,aid,project='M1',job=jid)
            h={'Authorization':'Bearer '+rig.service_token,'X-M1-Asset-Token':tokenmap[aid],'X-M1-Project':'M1','X-M1-Job':jid}
            r=client.get('/_m1/assets/'+aid,headers=h)
            assert r.status_code==200 and r.content==raw and r.headers['content-type'].startswith(mime)
        with TestClient(tts_app(TTSSettings(data_dir=data,tts_engine='silent'),m1_assets=assets)) as tts:
            h={'Authorization':'Bearer '+rig.service_token,'X-M1-Asset-Token':tokenmap['audio1'],'X-M1-Project':'M1','X-M1-Job':jid}
            response=tts.get('/_m1/assets/audio1',headers=h)
            assert hashlib.sha256(response.content).hexdigest()==hashes['audio1']
            assert response.status_code==200
            denied=tts.get('/audios/'+audio.rsplit('/',1)[-1]);assert denied.status_code==503
        adapter=OfflineSettlementAdapter(rig.authority,offline_test=True)
        evidence=adapter.evidence(attempt.attempt_id,200,event_id='offline-final-1',receipt_id='offline-receipt-1')
        ledger=tmp_path/'signed-bills.jsonl';ledger.write_text(json.dumps(evidence)+'\n',encoding='utf-8')
        assert consumer.ingest_jsonl(ledger,'offline-bills')==1
        assert consumer.ingest_jsonl(ledger,'offline-bills')==0
        assert rig.authority.totals()==dict(spent=200,held=0,available=14800)
        assets.revoke_task('M1',jid)
        r=client.get('/_m1/assets/audio1',headers=h)
        assert r.status_code==403 and hashlib.sha256(r.content).hexdigest()!=hashes['audio1']
        output=Path(os.environ['MISSION_EVIDENCE'])/'new-protocol-joint.json'
        output.write_text(json.dumps(dict(model='offline_fixture',settlement='offline_fixture',job_id=jid,
            attempt_id=attempt.attempt_id,result_sha256=attempt.result_sha256,asset_sha256=hashes,budget=rig.authority.totals(),
            private_authorized_http=200,revoked_http=403),ensure_ascii=False,indent=2),encoding='utf-8')
