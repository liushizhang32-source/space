"""Mock CLOUD only. Native media paths must be explicitly declared by runner."""
import io,json,os,subprocess,threading
from pathlib import Path
import httpx,pytest
from PIL import Image
from orchestrator.services.bailian.local import LocalTools
from orchestrator.services.bailian.engine import BookEngine

@pytest.fixture(scope='session')
def native_media(tmp_path_factory):
    root=tmp_path_factory.mktemp('real-model-media');tools=LocalTools()
    assert tools.ffmpeg and tools.ffprobe and Path(tools.font).is_file(),'Native tools must be configured, never skipped'
    audio=root/'tone.mp3';video=root/'moving.mp4'
    subprocess.run([tools.ffmpeg,'-y','-v','error','-f','lavfi','-i','sine=frequency=440:sample_rate=24000:duration=2',
        '-c:a','libmp3lame',str(audio)],check=True)
    subprocess.run([tools.ffmpeg,'-y','-v','error','-f','lavfi','-i','testsrc2=size=480x270:rate=24:duration=3',
        '-an','-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True)
    return dict(audio=audio.read_bytes(),video=video.read_bytes(),root=root,tools=tools)

def image_bytes(color='white'):
    b=io.BytesIO();Image.new('RGB',(640,480),color).save(b,format='PNG');return b.getvalue()

class CloudFixture:
    def __init__(self,media):
        self.media=media;self.requests=[];self.mode=None;self.before=None;self.task_status='SUCCEEDED'
    def __call__(self,request):
        body=json.loads(request.content) if request.content else None
        self.requests.append((request.method,str(request.url),body,dict(request.headers)))
        if self.before:self.before(request,body)
        path=request.url.path
        if request.url.host=='dashscope-result-bj.oss-cn-beijing.aliyuncs.com':
            assert 'authorization' not in request.headers
            return httpx.Response(200,content=self.media['audio' if path.endswith('.mp3') else 'video'])
        if self.mode=='timeout' and request.method=='POST':raise httpx.ReadTimeout('private response not logged',request=request)
        if path.endswith('/models'):return httpx.Response(200,json={'data':[{'id':'qwen-plus'}]})
        if path.endswith('/chat/completions'):
            model=body['model']
            if model=='qwen3-asr-flash':content='小兔子为什么帮助朋友？'
            elif model=='qwen3-vl-plus':content=json.dumps(dict(description='小兔子在森林里',objects=[dict(label='兔子',bbox=[100,100,600,800])],scene_tags=['森林'],safety={'pass':True,'flags':[]}),ensure_ascii=False)
            elif '儿童绘本导演' in body['messages'][0]['content']:
                material=json.loads(body['messages'][1]['content'])
                data=dict(title='森林里的朋友',characters=['小兔子'],safety_pass=True,safety_flags=[],pages=[
                    dict(page_id=p['page_id'],shots=[dict(narration='小兔子和朋友一起快乐地散步。',scene='森林散步',video_prompt='兔子轻轻向朋友挥手，保留绘本插画风格。')]) for p in material['pages']])
                if self.mode=='unsafe_story':data['safety_flags']=['violence']
                if self.mode=='wrong_page':data['pages'][0]['page_id']='other_p01'
                content=json.dumps(data,ensure_ascii=False)
            else:content=json.dumps(dict(answer='因为朋友需要帮助，小兔子很关心它。',safety_pass=True,safety_flags=[]),ensure_ascii=False)
            if self.mode=='unsafe_vision' and model=='qwen3-vl-plus':content=content.replace('"pass": true','"pass": false')
            if self.mode=='duplicate_vision' and model=='qwen3-vl-plus':content='{"safety":{"pass":false},"safety":{"pass":true,"flags":[]}}'
            return httpx.Response(200,json={'id':'req-test','choices':[{'finish_reason':'stop','message':{'content':content}}],
                'usage':{'prompt_tokens':100,'completion_tokens':200}})
        if path.endswith('/SpeechSynthesizer'):return httpx.Response(200,json={'request_id':'tts-test','output':{'audio':{'url':'https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/voice.mp3'}},'usage':{'characters':18}})
        if path.endswith('/video-synthesis'):return httpx.Response(200,json={'output':{'task_id':'wan-test-'+str(sum(x[1].endswith('/video-synthesis') for x in self.requests)),'task_status':'PENDING'}})
        if path.endswith('/cancel'):return httpx.Response(200,json={'request_id':'cancel-test'})
        if '/tasks/' in path:return httpx.Response(200,json={'output':{'task_id':path.rsplit('/',1)[-1],'task_status':self.task_status,
            'video_url':'https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/moving.mp4'},'usage':{'duration':3}})
        raise AssertionError('Unexpected cloud request '+path)

class FixtureOcrTools(LocalTools):
    def ocr(self,raw,cancel=lambda:False):
        from orchestrator.services.bailian.errors import Cancelled
        if cancel():raise Cancelled()
        im=Image.open(io.BytesIO(raw))
        return dict(width=im.width,height=im.height,lines=[dict(text='小兔子和朋友',bbox=[5,5,200,50],confidence=.9)],elapsed_ms=1)
    def status(self):
        result=super().status();result['paddle_python']='READY';return result

@pytest.fixture
def rig(tmp_path,native_media):
    fake=CloudFixture(native_media);base=native_media['tools']
    tools=FixtureOcrTools(ffmpeg=base.ffmpeg,ffprobe=base.ffprobe,font=base.font,ocr_python=__import__('sys').executable)
    engine=BookEngine(tmp_path/'state',local=tools,transport=httpx.MockTransport(fake));engine._key='test-not-a-real-secret'
    yield engine,fake
    engine.close()

def start_book(engine,count=1):
    book=engine.upload([(f'p{i}.png',image_bytes('white' if i%2 else 'ivory')) for i in range(count)])
    q=engine.quote(book['id'],'3-6','测试绘本')
    job=engine.generate(q['id'],q['estimate_fen'],True,True,'req-'+book['id'])
    return book,q,job
def finish(engine,job):
    engine.futures[job['id']].result(timeout=90)
    return engine.job(job['id'])
