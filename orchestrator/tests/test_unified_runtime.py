"""Runnable assembly and configured-service HTTP contract, never real models."""
import hashlib,io,json,os,socket,subprocess,threading,time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import httpx,pytest,uvicorn
from fastapi.testclient import TestClient
from PIL import Image
from orchestrator.core.config import Settings
from orchestrator.local_runtime import create_local_app
from orchestrator.main import create_app
from orchestrator.services import member3_adapter as adapter
from orchestrator.tests.test_member3_m1_callchain import chain,start,terminal

@contextmanager
def real_http(app):
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='on',access_log=False))
    thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
    deadline=time.monotonic()+10
    while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.01)
    assert server.started,'HTTP startup failed'
    try:
        with httpx.Client(base_url='http://127.0.0.1:'+str(listener.getsockname()[1]),timeout=10) as client:yield client
    finally:
        server.should_exit=True;thread.join(30);listener.close();assert not thread.is_alive()

@contextmanager
def tone_provider(tmp_path):
    """Local HTTP contract fixture returns decoded sine audio, not synthesized speech."""
    path=tmp_path/'provider.mp3'
    subprocess.run([os.environ['FFMPEG_PATH'],'-v','error','-f','lavfi','-i','sine=frequency=440:sample_rate=24000','-t','1.6','-c:a','libmp3lame','-y',str(path)],check=True)
    data=path.read_bytes();calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert set(body)=={'text','voice_id','speed','format'} and body['format']=='mp3'
            calls.append(body['text']);self.send_response(200);self.send_header('Content-Type','audio/mpeg');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:yield 'http://127.0.0.1:'+str(server.server_address[1]),calls,data
    finally:server.shutdown();server.server_close();worker.join()

def test_real_socket_chain_configured_TTS_assets_restart_and_UNKNOWN(tmp_path,monkeypatch):
    monkeypatch.setenv('M1_LOCAL_RUNTIME','offline_fixture');monkeypatch.setenv('M1_ASSET_MODE','blocked')
    settings=Settings(data_dir=tmp_path/'data',queue_delay=.001,stage_delay=.001,
        ffmpeg_path=os.environ['FFMPEG_PATH'],ffprobe_path=os.environ['FFPROBE_PATH'],video_font=os.environ['VIDEO_FONT'])
    with tone_provider(tmp_path) as (url,calls,audio):
        from dataclasses import replace
        settings=replace(settings,member3_tts_engine='http',member3_tts_http_url=url)
        app=create_local_app(settings)
        image=io.BytesIO();Image.new('RGB',(96,128),'white').save(image,format='PNG')
        with real_http(app) as client:
            assert client.post('/api/v1/capture',data={'book_id':'book01','page_no':3},files={'image':('page.png',image.getvalue(),'image/png')}).json()['code']==0
            jid=start(client);job=terminal(client,jid);assert job['status']=='done',job
            credentials=app.state.m1_runtime.asset_credentials(jid);assert len(credentials)>=3
            for entry in credentials:
                r=client.get('/_m1/assets/'+entry['asset_id'],headers=entry['headers'])
                assert r.status_code==200 and hashlib.sha256(r.content).hexdigest()==entry['sha256']
                assert client.get('/_m1/assets/'+entry['asset_id']).status_code==403
                alias=client.get('/'+entry['path'],headers=entry['headers'])
                assert alias.status_code==200 and alias.content==r.content
            entry=next(c for c in credentials if c['path'].startswith('audios/'))
            assert client.get('/'+entry['path'],headers=entry['headers']).content==audio
            assert calls and len(calls)==len(json.loads((settings.data_dir/'json/book01_p03_story.json').read_bytes())['segments'])
            assert app.state.m1_runtime.authority.totals()['held']==1000
            assert client.get('/'+entry['path']).status_code==503
        # A fresh application reuses persisted capture/job/Authority, never replays
        # unresolved work or invents a refund from a completed business Job.
        restarted=create_local_app(settings)
        with real_http(restarted) as client:
            assert client.get('/api/v1/jobs/'+jid).json()['data']['status']=='done'
            assert 'book01_p03' in restarted.state.storage.pages
            assert restarted.state.m1_runtime.authority.totals()['held']==1000
            assert client.get('/_m1/assets/'+entry['asset_id'],headers=entry['headers']).content==audio
            replacement=start(client);failed=terminal(client,replacement)
            assert failed['status']=='failed' and restarted.state.m1_runtime.authority.totals()['held']==1000

def test_revoked_after_render_cannot_publish_even_when_job_not_cancelled(chain,monkeypatch):
    client,jobs,rig,sessions=chain;original=adapter.Member3Session.publish
    def revoked(session):
        session.m1.consumer.fences.cancel(session.m1.consumer.record)
        return original(session)
    monkeypatch.setattr(adapter.Member3Session,'publish',revoked)
    jid=start(client);job=terminal(client,jid)
    assert job['status']=='failed' and job['pages'][0]['story_url'] is None
    assert not (jobs.storage.root/'json/book01_p03_story.json').exists()
    assert rig.authority.totals()['held']==1000

@pytest.mark.parametrize('environment',['dev','production','local'])
def test_no_implicit_fixture_bypass_without_M1(tmp_path,environment):
    app=create_app(Settings(data_dir=tmp_path/'data',generation_backend='member3',deployment_env=environment,asset_mode='blocked',queue_delay=.001))
    image=io.BytesIO();Image.new('RGB',(30,30)).save(image,format='PNG')
    with TestClient(app) as client:
        client.post('/api/v1/capture',data={'book_id':'book01','page_no':3},files={'image':('page.png',image.getvalue(),'image/png')})
        job=terminal(client,start(client))
        assert job['status']=='failed' and job['error']['code']==1005
        assert not (tmp_path/'data/.member3').exists()

def test_single_http_owner_and_explicit_profile(tmp_path,monkeypatch):
    monkeypatch.setenv('M1_LOCAL_RUNTIME','offline_fixture')
    config=Settings(data_dir=tmp_path/'data')
    first=create_local_app(config)
    with TestClient(first):
        with pytest.raises(RuntimeError,match='Only one local HTTP service'):
            with TestClient(create_local_app(config)):pass
    monkeypatch.delenv('M1_LOCAL_RUNTIME')
    with pytest.raises(ValueError):create_local_app(config)

def test_native_opencv_segmentation_is_not_fallback():
    import cv2,numpy as np
    assert callable(cv2.grabCut) and cv2.__version__
    image=np.full((120,120,3),240,np.uint8);image[30:90,30:90]=(40,40,200)
    mask=np.zeros((120,120),np.uint8)
    cv2.grabCut(image,mask,(28,28,64,64),np.zeros((1,65),np.float64),np.zeros((1,65),np.float64),3,cv2.GC_INIT_WITH_RECT)
    foreground=(mask==cv2.GC_FGD)|(mask==cv2.GC_PR_FGD)
    assert 1000<int(foreground.sum())<10000

def test_multi_page_audio_alias_is_bound_to_exact_asset_token(tmp_path,monkeypatch):
    monkeypatch.setenv('M1_LOCAL_RUNTIME','offline_fixture')
    app=create_local_app(Settings(data_dir=tmp_path/'data',queue_delay=.001,stage_delay=.001,
        ffmpeg_path=os.environ['FFMPEG_PATH'],ffprobe_path=os.environ['FFPROBE_PATH'],video_font=os.environ['VIDEO_FONT']))
    image=io.BytesIO();Image.new('RGB',(96,128),'white').save(image,format='PNG')
    with TestClient(app) as client:
        for page in (3,4):
            assert client.post('/api/v1/capture',data={'book_id':'book01','page_no':page},files={'image':('page.png',image.getvalue(),'image/png')}).json()['code']==0
        result=client.post('/api/v1/generate',json={'page_ids':['book01_p03','book01_p04'],'age_level':'3-6','force':False}).json()
        jid=result['data']['job_id'];job=terminal(client,jid);assert job['status']=='done',job
        for entry in app.state.m1_runtime.asset_credentials(jid):
            response=client.get('/'+entry['path'],headers=entry['headers'])
            assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==entry['sha256']
        assert app.state.m1_runtime.authority.totals()['held']==2000
