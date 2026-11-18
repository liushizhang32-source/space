"""Bailian HTTPS adapters. Charged POSTs are NEVER automatically retried.

Each SDK HTTP payload is explicit and covered against DashScope 2.1.0. API keys
belong to this in-memory client only, never results, journals or exception text.
"""
import base64,ipaddress,re,socket,time
from urllib.parse import urlsplit
import httpx
from .errors import IntegrationError
from .jsonutil import loads

def image_uri(raw):return 'data:image/jpeg;base64,'+base64.b64encode(raw).decode('ascii')
def identifier(value):
    if not isinstance(value,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,128}',value):raise IntegrationError('INVALID_PROVIDER_ID')
    return value

class Bailian:
    def __init__(self,config,key,*,transport=None):
        if not key or any(c in key for c in '\r\n'):raise IntegrationError('WAITING_FOR_KEY')
        self.config=config;self._key=key;self._test_transport=transport is not None
        self.client=httpx.Client(transport=transport,timeout=config.request_timeout,follow_redirects=False,trust_env=False)
    def close(self):self.client.close();self._key=''
    def request(self,method,path,body=None,*,async_task=False):
        headers={'Authorization':'Bearer '+self._key,'Content-Type':'application/json'}
        if async_task:headers['X-DashScope-Async']='enable'
        attempts=self.config.get_retries+1 if method=='GET' else 1
        for n in range(attempts):
            try:
                r=self.client.request(method,self.config.api_base+path,json=body,headers=headers)
            except httpx.TransportError:
                if n+1<attempts:time.sleep(min(2**n,4));continue
                raise IntegrationError('CLOUD_TRANSPORT_UNKNOWN',uncertain=method!='GET') from None
            if method=='GET' and r.status_code in {429,500,502,503,504} and n+1<attempts:
                time.sleep(min(2**n,4));continue
            if not 200<=r.status_code<300:
                raise IntegrationError('CLOUD_HTTP_'+str(r.status_code),uncertain=method!='GET',
                    request_id=r.headers.get('x-request-id','')[:100])
            data=loads(r.content)
            if not isinstance(data,dict) or data.get('code'):raise IntegrationError('CLOUD_BUSINESS_ERROR',uncertain=method!='GET')
            return data
    def chat(self,messages,*,model,max_tokens,json_mode=True):
        body=dict(model=model,messages=messages,max_tokens=max_tokens,enable_thinking=False,stream=False)
        if json_mode:body['response_format']={'type':'json_object'}
        data=self.request('POST','/compatible-mode/v1/chat/completions',body)
        try:
            choice=data['choices'][0]
            if choice['finish_reason']!='stop':raise IntegrationError('MODEL_OUTPUT_INCOMPLETE',uncertain=True)
            text=choice['message']['content']
            if not isinstance(text,str):raise TypeError()
        except (KeyError,TypeError,IndexError):raise IntegrationError('MODEL_RESPONSE_INVALID',uncertain=True) from None
        return dict(content=loads(text) if json_mode else text,usage=data.get('usage'),request_id=data.get('id','')[:128])
    def vlm(self,image,ocr_text):
        from .contracts import vision_backend
        backend=vision_backend()
        messages=[{'role':'system','content':backend.SYSTEM_PROMPT},{'role':'user','content':[
            {'type':'image_url','image_url':{'url':image_uri(image)}},
            {'type':'text','text':backend.USER_PROMPT % ocr_text[:12000]}]}]
        return self.chat(messages,model=self.config.vlm_model,max_tokens=self.config.vlm_max_tokens)
    def tts(self,text):
        if not text or len(text)>self.config.narration_chars_per_page:raise IntegrationError('TTS_TEXT_LIMIT')
        body={'model':self.config.tts_model,'input':dict(text=text,voice=self.config.tts_voice,
            format='mp3',sample_rate=24000,rate=self.config.speech_rate,enable_aigc_tag=True,
            language_hints=['zh'])}
        data=self.request('POST','/api/v1/services/audio/tts/SpeechSynthesizer',body)
        try:url=data['output']['audio']['url']
        except (KeyError,TypeError):raise IntegrationError('TTS_RESPONSE_INVALID',uncertain=True) from None
        return dict(url=url,usage=data.get('usage'),request_id=data.get('request_id',''))
    def asr(self,wav):
        body=dict(model=self.config.asr_model,stream=False,messages=[{'role':'user','content':[
            {'type':'input_audio','input_audio':{'data':'data:audio/wav;base64,'+base64.b64encode(wav).decode()}}]}],
            asr_options={'language':'zh','enable_itn':False})
        data=self.request('POST','/compatible-mode/v1/chat/completions',body)
        try:
            text=data['choices'][0]['message']['content']
            if not isinstance(text,str) or not 1<=len(text)<=1000:raise ValueError()
        except (KeyError,IndexError,TypeError,ValueError):raise IntegrationError('ASR_RESPONSE_INVALID',uncertain=True) from None
        return {'text':text,'usage':data.get('usage'),'request_id':data.get('id','')}
    def wan_submit(self,image,prompt,duration):
        if type(duration) is not int or not 2<=duration<=15:raise IntegrationError('WAN_DURATION_LIMIT')
        body={'model':self.config.wan_model,'input':dict(img_url=image_uri(image),prompt=prompt[:1500]),
            'parameters':dict(resolution=self.config.resolution,duration=duration,audio=False,prompt_extend=False,watermark=True)}
        data=self.request('POST','/api/v1/services/aigc/video-generation/video-synthesis',body,async_task=True)
        try:task=identifier(data['output']['task_id'])
        except (KeyError,TypeError):raise IntegrationError('WAN_TASK_ID_MISSING',uncertain=True) from None
        return dict(task_id=task,request_id=data.get('request_id',''))
    def wan_poll(self,task):
        data=self.request('GET','/api/v1/tasks/'+identifier(task))
        try:
            output=data['output'];status=output['task_status']
            if status not in {'PENDING','RUNNING','SUCCEEDED','FAILED','CANCELED','CANCELLED','UNKNOWN'}:raise KeyError()
            if output.get('task_id',task)!=task:raise KeyError()
        except (KeyError,TypeError):raise IntegrationError('WAN_POLL_INVALID',uncertain=True) from None
        return data
    def wan_cancel(self,task):return self.request('POST','/api/v1/tasks/'+identifier(task)+'/cancel',{})
    def models(self):
        # No inference charge; a model listing is NOT a model permission test.
        data=self.request('GET','/compatible-mode/v1/models')
        return dict(authentication='PASS',model_permissions='UNVERIFIED',listed_models=len(data.get('data',[])))
    def download(self,url,*,limit,authorize=lambda:None):
        try:p=urlsplit(url)
        except ValueError:raise IntegrationError('DOWNLOAD_URL_DENIED') from None
        host=(p.hostname or '').lower()
        # Official temporary result storage only. No arbitrary URL, credentials,
        # private hosts, redirects, proxy inheritance or Authorization forwarding.
        if p.scheme!='https' or p.username or p.password or p.port not in {None,443} or not (
            host.endswith('.aliyuncs.com') and ('dashscope' in host or re.search(r'\.oss-[a-z0-9-]+\.aliyuncs\.com$',host))):
            raise IntegrationError('DOWNLOAD_URL_DENIED')
        if not self._test_transport:
            try:addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
            except OSError:raise IntegrationError('DOWNLOAD_DNS_FAILED') from None
            if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):raise IntegrationError('DOWNLOAD_ADDRESS_DENIED')
        authorize();chunks=[];count=0
        try:
            with self.client.stream('GET',url,headers={},timeout=180) as r:
                if r.status_code!=200:raise IntegrationError('DOWNLOAD_FAILED',uncertain=True)
                for part in r.iter_bytes():
                    authorize()
                    count+=len(part)
                    if count>limit:raise IntegrationError('DOWNLOAD_TOO_LARGE',uncertain=True)
                    chunks.append(part)
        except httpx.TransportError:raise IntegrationError('DOWNLOAD_TRANSPORT_FAILED',uncertain=True) from None
        if not count:raise IntegrationError('DOWNLOAD_EMPTY',uncertain=True)
        authorize()
        return b''.join(chunks)
