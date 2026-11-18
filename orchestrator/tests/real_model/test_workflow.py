import hashlib,io,json,time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from orchestrator.bailian_app import create_app
from orchestrator.services.bailian.errors import IntegrationError
from orchestrator.services.integration_reference.authority import Denied
from orchestrator.services.bailian.authority import CloudAuthority
from orchestrator.services.bailian.local import parse_upload
from conftest import image_bytes,start_book,finish

@pytest.mark.parametrize('count',[1,2,3])
def test_single_multi_page_end_to_end_native_media(rig,count):
    engine,cloud=rig;book,quote,job=start_book(engine,count);result=finish(engine,job)
    assert result['status']=='COMPLETED',result
    assert result['source_mode']=='MOCK_HTTP_TEST' and result['billing_status']=='UNKNOWN' and result['actual_cost_fen'] is None
    assert [r['page_id'] for r in result['recognition']]==[p['id'] for p in book['pages']]
    assert len(result['c3'])==count and result['duration']>count*1.9
    assert engine.authority.m1.totals()==dict(spent=0,held=quote['estimate_fen'],available=15000-quote['estimate_fen'])
    for key in ['video','audio','subtitles']:
        raw,meta=engine.authority.read(result['outputs'][key].removeprefix('/studio/assets/'),job=job['id'])
        assert len(raw)>30 and hashlib.sha256(raw).hexdigest()==meta['sha256']
    posts=[r for r in cloud.requests if r[0]=='POST']
    assert sum(r[2].get('model')=='qwen3-vl-plus' for r in posts)==count
    assert sum(r[2].get('model')=='wan2.6-i2v-flash' for r in posts)==count
    assert sum(r[2].get('model')=='cosyvoice-v3-flash' for r in posts)==count
    for method,url,body,headers in cloud.requests:
        if url.endswith('/video-synthesis'):
            assert headers['x-dashscope-async']=='enable' and body['parameters']['audio'] is False
            assert body['input']['img_url'].startswith('data:image/jpeg;base64,')

def test_http_upload_generate_assets_and_cancel_revokes_body(rig):
    engine,cloud=rig
    with TestClient(create_app(engine=engine)) as client:
        token=client.get('/studio/session').json()['csrf'];client.headers['X-CSRF-Token']=token
        book=client.post('/studio/books',files=[('files',('p.png',image_bytes(),'image/png'))]).json()
        preview=client.get('/studio/assets/'+book['pages'][0]['asset']);assert preview.status_code==200 and preview.headers['content-type']=='image/jpeg'
        q=client.post('/studio/books/'+book['id']+'/quote',json={'age':'3-6','title':'HTTP绘本'}).json()
        request=dict(quote_id=q['id'],cap_fen=q['estimate_fen'],cloud_consent=True,account_permissions_confirmed=True,request_id='http-one')
        response=client.post('/studio/generate',json=request);assert response.status_code==200,response.text
        job=response.json();result=finish(engine,job)
        assert result['status']=='COMPLETED',result
        assert client.post('/studio/generate',json=request).json()['id']==job['id']
        url=result['outputs']['video'];raw=client.get(url).content
        assert client.get(url,headers={'Range':'bytes=5-20'}).content==raw[5:21]
        assert client.get(url,headers={'Range':'bytes=999999999-'}).status_code==416
        assert client.post('/studio/jobs/'+job['id']+'/cancel',json={}).status_code==200
        denied=client.get(url);assert denied.status_code==403 and raw not in denied.content
        assert 'video/mp4' not in denied.headers['content-type']
        assert engine.authority.m1.totals()['held']==q['estimate_fen']

@pytest.mark.parametrize('mode',['unsafe_vision','duplicate_vision','unsafe_story','wrong_page'])
def test_unsafe_or_wrong_identity_never_publishes(rig,mode):
    engine,cloud=rig;cloud.mode=mode;book,q,job=start_book(engine);result=finish(engine,job)
    assert result['status']=='FAILED' and not result['outputs']
    assert not any(r[1].endswith('/video-synthesis') for r in cloud.requests)
    assert engine.authority.m1.totals()['held']==q['estimate_fen']

def test_uncertain_paid_post_never_retries_on_resume(rig):
    engine,cloud=rig;cloud.mode='timeout';book,q,job=start_book(engine);result=finish(engine,job)
    assert result['status']=='RECOVERY_REQUIRED'
    assert len([r for r in cloud.requests if r[0]=='POST'])==1
    cloud.mode=None;engine.resume(job['id']);result=finish(engine,job)
    assert result['error']=='CHARGED_REQUEST_UNKNOWN_NO_REPLAY'
    assert len([r for r in cloud.requests if r[0]=='POST'])==1
    assert engine.authority.m1.totals()['held']==q['estimate_fen']

def test_cancel_during_dispatch_prevents_later_paid_calls(rig):
    engine,cloud=rig
    def before(req,body):
        if body and body.get('model')=='qwen3-vl-plus':
            jobs=engine.authority.all('job/');engine.cancel(jobs[0]['id'])
    cloud.before=before;book,q,job=start_book(engine);result=finish(engine,job)
    assert result['status']=='CANCELLED'
    assert len([r for r in cloud.requests if r[0]=='POST'])==1
    assert engine.authority.m1.totals()['spent']==0 and engine.authority.m1.totals()['held']==q['estimate_fen']

def test_budget_persists_across_restarts_and_is_global(rig):
    engine,cloud=rig;book,q,job=start_book(engine);finish(engine,job)
    fresh=CloudAuthority(engine.authority.root)
    assert fresh.m1.totals()['held']==q['estimate_fen']
    with pytest.raises(Denied,match='PROJECT_ACCOUNT_FIXED'):fresh.m1.provision_project('new-model-account')
    assert fresh.m1.totals()['available']==15000-q['estimate_fen']

def test_second_job_cap_cannot_multiply_project_budget(rig):
    engine,cloud=rig
    book=engine.upload([('a.png',image_bytes())]);q=engine.quote(book['id'],'3-6','one')
    job=engine.generate(q['id'],15000,True,True,'all-budget');finish(engine,job)
    other=engine.upload([('b.png',image_bytes())]);q2=engine.quote(other['id'],'3-6','two')
    before=len(cloud.requests)
    with pytest.raises(Denied,match='BUDGET_EXHAUSTED'):engine.generate(q2['id'],q2['estimate_fen'],True,True,'second')
    assert len(cloud.requests)==before and engine.authority.m1.totals()['held']==15000

@pytest.mark.parametrize('field',['key','consent','permissions','cap','revision','config'])
def test_dispatch_requires_key_consent_exact_quote_and_cap(rig,field):
    engine,cloud=rig;book=engine.upload([('a.png',image_bytes())]);q=engine.quote(book['id'],'3-6','title')
    cap=q['estimate_fen'];consent=permissions=True
    if field=='key':engine._key=''
    if field=='consent':consent=False
    if field=='permissions':permissions=False
    if field=='cap':cap-=1
    if field=='revision':engine.reorder(book['id'],[book['pages'][0]['id']])
    if field=='config':engine.configure(engine.config.model_copy(update={'speech_rate':1.1}))
    with pytest.raises(IntegrationError):engine.generate(q['id'],cap,consent,permissions,'denied-'+field)
    assert not cloud.requests and engine.authority.m1.totals()['held']==0

def test_sort_pages_changes_revision_and_retains_exact_bytes(rig):
    engine,cloud=rig;book=engine.upload([('a.png',image_bytes('white')),('b.png',image_bytes('red'))]);a,b=book['pages']
    raw=engine.authority.read(b['asset'])[0];updated=engine.reorder(book['id'],[b['id'],a['id']])
    assert updated['revision']==2 and updated['pages'][0]['id']==a['id']
    assert engine.authority.read(updated['pages'][0]['asset'])[0]==raw
    with pytest.raises(IntegrationError):engine.reorder(book['id'],[a['id'],a['id']])

def test_pdf_real_rasterization_and_multi_page_workflow(rig):
    import pymupdf
    engine,cloud=rig
    with pymupdf.open() as doc:
        for _ in range(2):doc.new_page(width=400,height=300).insert_text((40,50),'Picture book')
        raw=doc.tobytes()
    book=engine.upload([('book.pdf',raw)]);assert len(book['pages'])==2
    q=engine.quote(book['id'],'6-9','PDF');job=engine.generate(q['id'],q['estimate_fen'],True,True,'pdf-job')
    assert finish(engine,job)['status']=='COMPLETED'

def test_agent_context_multi_turn_and_real_audio_composition(rig):
    engine,cloud=rig;book,q,job=start_book(engine);assert finish(engine,job)['status']=='COMPLETED'
    first=engine.ask(job['id'],1,'兔子为什么帮助朋友？',100,True,'qa-1')
    second=engine.ask(job['id'],1,'后来呢？',100,True,'qa-2')
    assert first['answer'] and first['audio_url'] and second['billing_status']=='UNKNOWN'
    qa=[x[2] for x in cloud.requests if x[2] and x[2].get('model')=='qwen-plus' and '问答助手' in x[2]['messages'][0]['content']]
    assert json.loads(qa[1]['messages'][1]['content'])['history'][0]['question']=='兔子为什么帮助朋友？'
    assert engine.ask(job['id'],1,'后来呢？',100,True,'qa-2')==second
    engine.cancel(job['id'])
    with pytest.raises(Denied):engine.ask(job['id'],1,'再问一次',100,True,'qa-3')
