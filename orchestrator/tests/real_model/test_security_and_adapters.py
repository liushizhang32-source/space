import hashlib,io,json,os,secrets,time
from pathlib import Path
import httpx,pytest
from fastapi.testclient import TestClient
from orchestrator.bailian_app import create_app
from orchestrator.services.bailian.cloud import Bailian
from orchestrator.services.bailian.config import ModelConfig,price_estimate
from orchestrator.services.bailian.contracts import c1,c2,validate_story
from orchestrator.services.bailian.errors import IntegrationError
from orchestrator.services.bailian.jsonutil import loads
from orchestrator.services.bailian.local import LocalTools,parse_upload,normalize_image,run
from orchestrator.services.integration_reference.authority import Authority,OfflineKMS,Denied
from conftest import image_bytes,start_book,finish,CloudFixture

@pytest.mark.parametrize('payload',['{"safety":false,"safety":true}','{"x":NaN}','{"x":Infinity}','{bad','[1,2,]'])
def test_strict_cloud_json_rejects_ambiguity(payload):
    with pytest.raises(IntegrationError):loads(payload)

@pytest.mark.parametrize('kwargs',[{'global_budget_fen':30000},{'search_enabled':True},{'region':'evil.local'},{'workspace':'foo/bar'},{'resolution':'4K'},{'shots_per_page':5}])
def test_configuration_cannot_raise_budget_or_inject_endpoint(kwargs):
    with pytest.raises(ValueError):ModelConfig(**kwargs)

@pytest.mark.parametrize('changes',[{'region':'ap-southeast-1'},{'tts_model':'cosyvoice-v3-plus'},{'vlm_model':'other'},{'wan_model':'wan-new'},{'tts_voice':'voice-clone-arbitrary'}])
def test_unpriced_or_unverified_configuration_cannot_quote(changes):
    with pytest.raises(ValueError):price_estimate(ModelConfig(**changes),[{}])

def test_cloud_profile_is_explicit_and_does_not_activate_original_runtime(tmp_path):
    a=Authority.provision(tmp_path/'a.db',tmp_path/'anchor',OfflineKMS(),lambda:1000,offline_test=True)
    with pytest.raises(Denied,match='PROVIDER_BLOCKED'):
        a.begin('invalid','p','page','request',1,['image'],provider='dashscope',model='cloud-workflow-plan/1')
    with pytest.raises(Denied,match='PRODUCTION_BLOCKED'):
        Authority(tmp_path/'a.db',tmp_path/'anchor',OfflineKMS(),lambda:1000)

@pytest.mark.parametrize('path,method',[('/studio/config','GET'),('/studio/jobs','GET'),('/studio/assets/input/private.jpg','GET'),('/studio/generate','POST'),('/studio/questions','POST')])
def test_real_http_requires_session_without_reading_private_bytes(rig,path,method):
    engine,cloud=rig
    with TestClient(create_app(engine=engine)) as client:
        r=client.request(method,path,json={} if method=='POST' else None)
        assert r.status_code==401 and 'SESSION_REQUIRED' in r.text
        assert not cloud.requests

@pytest.mark.parametrize('headers',[{}, {'X-CSRF-Token':'wrong'},{'Origin':'https://evil.example'},{'Host':'evil.example'},{'Sec-Fetch-Site':'cross-site'}])
def test_csrf_origin_and_dns_rebinding_are_denied(rig,headers):
    engine,cloud=rig
    with TestClient(create_app(engine=engine)) as client:
        client.get('/studio/session')
        r=client.post('/studio/connections',headers=headers,json={})
        assert r.status_code==403 and not cloud.requests

def test_key_never_echoed_or_persisted_to_authority_or_frontend(rig):
    engine,cloud=rig;secret='unit-secret-'+secrets.token_hex(15)
    with TestClient(create_app(engine=engine)) as client:
        csrf=client.get('/studio/session').json()['csrf'];client.headers['X-CSRF-Token']=csrf
        data={'config':engine.config.model_dump(),'api_key':secret}
        r=client.post('/studio/config',json=data);assert r.status_code==200 and secret not in r.text
        assert secret not in client.get('/studio/config').text
        assert secret not in client.get('/app.js').text
        bad=client.post('/studio/config',json={'config':{'api_key':secret},'api_key':secret})
        assert bad.status_code==409 and secret not in bad.text
        assert b'localStorage' not in client.get('/app.js').content
    for path in engine.authority.root.rglob('*'):
        if path.is_file():assert secret.encode() not in path.read_bytes()

def test_no_key_connection_performs_zero_network_calls(rig):
    engine,cloud=rig;engine._key=''
    assert engine.connection()['authentication']=='WAITING_FOR_KEY' and not cloud.requests

def test_model_list_never_claims_model_permissions(rig):
    engine,cloud=rig;result=engine.connection()
    assert result['authentication']=='PASS' and result['model_permissions']=='UNVERIFIED'
    assert all(x[0]=='GET' for x in cloud.requests)

@pytest.mark.parametrize('url',['http://127.0.0.1/a','https://127.0.0.1/a','https://example.com/a','file:///etc/passwd',
    'https://user:pass@dashscope-result-bj.oss-cn-beijing.aliyuncs.com/a','https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com:8888/a',
    'https://aliyuncs.com.attacker.example/a'])
def test_remote_result_download_rejects_ssrf_without_request(rig,url):
    engine,cloud=rig;client=Bailian(engine.config,engine._key,transport=httpx.MockTransport(cloud))
    try:
        with pytest.raises(IntegrationError,match='DOWNLOAD_URL_DENIED'):client.download(url,limit=1024)
        assert not cloud.requests
    finally:client.close()

def test_download_rejects_redirect_overflow_and_empty():
    for response,expected in [(httpx.Response(302,headers={'location':'http://127.0.0.1'}),'DOWNLOAD_FAILED'),
        (httpx.Response(200,content=b'x'*100),'DOWNLOAD_TOO_LARGE'),(httpx.Response(200,content=b''),'DOWNLOAD_EMPTY')]:
        client=Bailian(ModelConfig(),'not-real',transport=httpx.MockTransport(lambda _:response))
        try:
            with pytest.raises(IntegrationError,match=expected):client.download('https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/file',limit=10)
        finally:client.close()

def test_tts_request_matches_installed_official_sdk_body(rig):
    from dashscope.resources.audio.http_tts import _build_body
    engine,cloud=rig;client=Bailian(engine.config,engine._key,transport=httpx.MockTransport(cloud))
    try:client.tts('小兔子你好。')
    finally:client.close()
    actual=cloud.requests[-1][2]
    expected=_build_body('小兔子你好。',model='cosyvoice-v3-flash',voice=engine.config.tts_voice,format='mp3',sample_rate=24000,
        language_type=None,parameters=None,extra_input={'rate':.9,'enable_aigc_tag':True,'language_hints':['zh']})
    assert actual==expected

def test_charged_post_is_not_retried_but_poll_is_bounded():
    counts={'POST':0,'GET':0}
    def handler(request):
        counts[request.method]+=1
        return httpx.Response(503,json={'message':'private upstream body'})
    client=Bailian(ModelConfig(get_retries=1),'test-secret',transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(IntegrationError,match='CLOUD_HTTP_503'):client.request('POST','/paid',{})
        with pytest.raises(IntegrationError,match='CLOUD_HTTP_503'):client.request('GET','/poll')
        assert counts=={'POST':1,'GET':2}
    finally:client.close()

@pytest.mark.parametrize('status',['PENDING','RUNNING','SUCCEEDED','FAILED','CANCELED','UNKNOWN'])
def test_wan_async_status_parser(rig,status):
    engine,cloud=rig;cloud.task_status=status;client=Bailian(engine.config,engine._key,transport=httpx.MockTransport(cloud))
    try:assert client.wan_poll('known-task')['output']['task_status']==status
    finally:client.close()

@pytest.mark.parametrize('duration',[0,1,16,2.1,True])
def test_wan_duration_guard_precedes_network(rig,duration):
    engine,cloud=rig;client=Bailian(engine.config,engine._key,transport=httpx.MockTransport(cloud))
    try:
        with pytest.raises(IntegrationError):client.wan_submit(b'jpeg','prompt',duration)
        assert not cloud.requests
    finally:client.close()

def test_pdf_image_signature_and_limits():
    for name,raw in [('malware.svg',b'<svg/>'),('bad.pdf',b'not pdf'),('bad.png',b'not image'),('huge.jpg',b'x'*(20*1024*1024+1))]:
        with pytest.raises(IntegrationError):parse_upload(raw,name)

def test_local_media_rejects_silence_and_nonvideo(native_media,tmp_path):
    import subprocess
    tools=native_media['tools'];silent=tmp_path/'silent.mp3'
    subprocess.run([tools.ffmpeg,'-y','-v','error','-f','lavfi','-i','anullsrc=r=24000:cl=mono','-t','1','-c:a','libmp3lame',str(silent)],check=True)
    with pytest.raises(IntegrationError,match='AUDIO_SILENCE_REJECTED'):tools.audio_duration(silent.read_bytes(),tmp_path)
    with pytest.raises(IntegrationError):tools.validate_video(b'not video',tmp_path,1)

def test_c1_pixel_coordinates_and_c2_missing_safety_fail_closed():
    page=dict(id='book001_p01',number=1,width=640,height=480)
    value=c1('book001',page,dict(width=640,height=480,lines=[dict(text='你好',bbox=[1,2,30,40],confidence=.98)],elapsed_ms=2))
    assert value['text_blocks'][0]['bbox']==(1,2,30,40)
    with pytest.raises(IntegrationError):c2('book001',page,dict(description='nothing',objects=[],safety={'pass':True}))

def test_original_grant_and_token_revocation_block_input_before_bytes(rig):
    engine,cloud=rig;book,q,job=start_book(engine);finish(engine,job)
    lease=engine.authority.get('lease/'+job['id']);engine.authority.m1.revoke(lease['token'])
    with pytest.raises(Denied):engine.authority.input(job['id'],book['pages'][0]['asset'])
    assert engine.authority.m1.totals()['held']==q['estimate_fen']

def test_private_assets_have_no_static_or_file_path_bypass(rig):
    engine,cloud=rig;book=engine.upload([('a.png',image_bytes())]);raw=engine.authority.read(book['pages'][0]['asset'])[0]
    with TestClient(create_app(engine=engine)) as client:
        client.get('/studio/session')
        for path in ['/static/input/'+book['pages'][0]['id']+'.jpg','/data/m1.sqlite','/videos/private.mp4','/studio/assets/unknown','/studio/assets/C%3A/Windows/win.ini']:
            response=client.get(path);assert response.status_code in {403,404} and raw not in response.content

def test_http_duplicate_json_and_oversize_body_are_denied(rig):
    engine,cloud=rig
    with TestClient(create_app(engine=engine)) as client:
        token=client.get('/studio/session').json()['csrf'];client.headers['X-CSRF-Token']=token
        assert client.post('/studio/generate',content='{"cloud_consent":false,"cloud_consent":true}',headers={'Content-Type':'application/json'}).status_code==400
        assert client.post('/studio/config',content='{}',headers={'Content-Length':str(65*1024*1024)}).status_code==413
        assert not cloud.requests

def test_anchor_detects_journal_tampering(rig):
    import sqlite3
    engine,cloud=rig
    db=sqlite3.connect(engine.authority.m1.path);db.execute("INSERT INTO cloud_documents VALUES('tamper','{}')");db.commit();db.close()
    with pytest.raises(Denied,match='ROLLBACK_DETECTED'):engine.authority.m1.totals()

def test_cloud_extension_is_proposed_and_traceable():
    root=Path(__file__).resolve().parents[3]
    record=next(r for r in json.loads((root/'docs/protocols/registry.json').read_bytes()) if r['id']=='P5')
    assert record['status']=='PROPOSED' and record['version']=='1.0' and record['clauses']==16
    spec=(root/'docs/protocols'/record['file']).read_text(encoding='utf-8')
    trace=(root/'docs/protocols/PROTOCOL_TRACEABILITY_MATRIX.md').read_text(encoding='utf-8')
    for i in range(1,17):assert f'P5-{i:02d}' in spec and f'P5-{i:02d}' in trace
