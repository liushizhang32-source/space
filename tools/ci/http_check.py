from pathlib import Path
import hashlib,json,os,re,socket,subprocess,sys,time
import httpx

ROOT=Path(os.environ['CI_RUN_DIR'])
CONTROL=Path(__file__).resolve().parent
repo=Path(os.environ['CI_TARGET'])
sys.dont_write_bytecode=True
sys.path.insert(0,str(repo))
from orchestrator.schemas.story import StoryData
from orchestrator.schemas.ocr import OCRData
from orchestrator.schemas.vlm import VLMData

cfg={'python':sys.executable};env=os.environ.copy()
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
base=f'http://127.0.0.1:{port}'
env.update({'GENERATION_BACKEND':'member3','ISOLATED_MODULE':str(repo),'DATA_DIR':str(ROOT/'http-data'),
            'ASSET_BASE_URL':base,'INTEGRATION_PORT':str(port),'RUN_LABEL':'http_integration'})
(ROOT/'stop-http').unlink(missing_ok=True)
log=(ROOT/'logs/http_integration_server.log').open('w',encoding='utf-8')
process=subprocess.Popen([cfg['python'],str(CONTROL/'guard.py'),'server'],
    cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
results=[];history=[];started=time.perf_counter()
client=httpx.Client(base_url=base,timeout=15,trust_env=False)

def check(name,fn):
    data=fn();results.append({'name':name,'pass':True,'detail':data});print('PASS',name,flush=True);return data

def envelope(response,code=0):
    assert response.status_code==200
    doc=response.json();assert set(doc)=={'code','msg','data','trace_id'}
    assert doc['code']==code,doc
    assert re.fullmatch(r'tr_[0-9A-HJKMNP-TV-Z]{26}',doc['trace_id'])
    assert response.headers['X-Trace-ID']==doc['trace_id']
    return doc

try:
    deadline=time.monotonic()+20
    while True:
        try:
            response=client.get('/openapi.json')
            if response.status_code==200:break
        except httpx.TransportError:pass
        if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Uvicorn startup failed')
        time.sleep(.1)
    check('unchanged API paths',lambda: all(p in response.json()['paths'] for p in (
        '/api/v1/capture','/api/v1/generate','/api/v1/jobs/{job_id}')) or (_ for _ in ()).throw(AssertionError()))
    image=(repo/'orchestrator/vendor/member3_v116/examples/book01_p03/book01_p03_orig.png').read_bytes()
    capture=check('capture',lambda:envelope(client.post('/api/v1/capture',data={'page_no':3,'book_id':'book01'},
        files={'image':('page.png',image,'image/png')})))['data']
    assert capture['image_width']>0 and capture['image_height']>0
    def preview():
        response=client.get(capture['preview_url']);assert response.status_code==200 and response.headers['content-type']=='image/jpeg'
        return {'url':capture['preview_url'],'bytes':len(response.content)}
    check('preview URL',preview)
    payload={'page_ids':[capture['page_id']],'age_level':'3-6','force':False}
    generated=check('generate',lambda:envelope(client.post('/api/v1/generate',json=payload)))['data']
    assert generated['status']=='queued' and generated['poll_after_ms']==2000
    jid=generated['job_id'];assert re.fullmatch(r'job_[0-9A-HJKMNP-TV-Z]{26}',jid)
    def duplicate():
        data=envelope(client.post('/api/v1/generate',json=payload));assert data['data']['job_id']==jid;return data
    check('active request idempotency',duplicate)
    while True:
        state=envelope(client.get('/api/v1/jobs/'+jid));history.append(state);job=state['data']
        if job['status'] in ('done','failed','partial_failed','cancelled'):break
        if time.perf_counter()-started>90:raise TimeoutError('integration job timeout')
        time.sleep(2)
    def completed():
        assert job['status']=='done' and job['progress']==100 and job['error'] is None
        page=job['pages'][0];assert page['status']=='done' and page['degraded']==[]
        assert [s['name'] for s in page['stages']]==['ocr','vlm','story','tts','render']
        assert [s['status'] for s in page['stages']]==['ok']*5
        assert all(s['elapsed_ms']>=0 for s in page['stages'])
        assert any(h['data']['status']=='queued' for h in history) and any(h['data']['status']=='running' for h in history)
        assert [h['data']['progress'] for h in history]==sorted(h['data']['progress'] for h in history)
        return job
    check('queued-running-done and all stages',completed)
    def visual():
        for kind,model in [('ocr',OCRData),('vlm',VLMData)]:
            q=client.get('/json/book01_p03_'+kind+'.json');assert q.status_code==200
            data=model.model_validate(q.json());assert data.page_id==capture['page_id']
        return {'ocr':'public Schema passed','vlm':'public Schema passed','source':'fixed MOCK'}
    check('visual fixtures public Schemas',visual)
    page=job['pages'][0]
    def story():
        q=client.get(page['story_url']);assert q.status_code==200
        model=StoryData.model_validate(q.json());assert model.model.name=='mock-template'
        assert all(s.scene and s.duration_source=='tts' and s.audio_url for s in model.segments)
        (ROOT/'logs/http-story.json').write_text(json.dumps(q.json(),ensure_ascii=False,indent=2),encoding='utf-8')
        return {'url':page['story_url'],'segments':len(model.segments),'total_duration_sec':model.total_duration_sec}
    check('Story public Schema',story)
    doc=json.loads((ROOT/'logs/http-story.json').read_text(encoding='utf-8'))
    def decode(url,target):
        response=client.get(url);assert response.status_code==200
        target.write_bytes(response.content)
        ff=subprocess.run([env['FFMPEG_PATH'],'-v','error','-xerror','-i',str(target),'-f','null','-'],capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));assert ff.returncode==0,ff.stderr
        probe=subprocess.run([env['FFPROBE_PATH'],'-v','error','-show_entries','format=duration,format_name:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate','-of','json',str(target)],capture_output=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));assert probe.returncode==0
        return {'url':url,'bytes':len(response.content),'sha256':hashlib.sha256(response.content).hexdigest(),'decoder_exit':ff.returncode,'probe':json.loads(probe.stdout)}
    check('all audio HTTP downloads and real decoding',lambda:[decode(s['audio_url'],ROOT/'downloads'/f'http-audio-{i}.mp3') for i,s in enumerate(doc['segments'])])
    video=check('video HTTP download and real decoding',lambda:decode(page['video_url'],ROOT/'downloads/http-video.mp4'))
    assert 'mp4' in video['probe']['format']['format_name']
    assert {s['codec_type'] for s in video['probe']['streams']}=={'video','audio'}
    local=ROOT/'http-data/videos/book01_p03_video.mp4';assert video['sha256']==hashlib.sha256(local.read_bytes()).hexdigest()
    check('unknown job unified error',lambda:envelope(client.get('/api/v1/jobs/missing'),1003))
    def clean():
        assert list((ROOT/'http-data/.member3').iterdir())==[];return True
    check('temporary workspace cleanup',clean)
except Exception as exc:
    results.append({'name':'uncompleted HTTP integration check','pass':False,'detail':repr(exc)})
    print('FAIL',repr(exc),flush=True)
finally:
    client.close();(ROOT/'stop-http').write_text('stop',encoding='utf-8')
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
    log.close()
    with socket.socket() as s:s.settimeout(.5);closed=s.connect_ex(('127.0.0.1',port))!=0
    result={'checks':results,'history':history,'passed':sum(c['pass'] for c in results),'failed':sum(not c['pass'] for c in results),
            'seconds':time.perf_counter()-started,'server_pid':process.pid,'server_exit':process.returncode,'port':port,'port_closed':closed}
    (ROOT/'http-integration-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('checks','history')}),flush=True)

if result["failed"] or result["passed"] != 12 or result["server_exit"] != 0 or not result["port_closed"]:
    raise SystemExit(1)
