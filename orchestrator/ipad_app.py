"""Authorized household gateway; original M1 remains the sole asset/budget authority."""
import hashlib,hmac,ipaddress,json,secrets,time
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import Response,JSONResponse,HTMLResponse
from starlette.concurrency import run_in_threadpool
from .bailian_app import create_app as core_app,default_root
from .services.bailian.engine import BookEngine

STATIC=Path(__file__).with_name('ipad')
class Devices:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.path=self.root/'ipad-devices.json'
        self.data=json.loads(self.path.read_bytes()) if self.path.exists() else {'devices':{},'pin':None}
        self.sessions=dict(self.data.get('parent_sessions',{}));self.code=None;self.expires=0;self.failures={};self.allowances={}
    def save(self,*,auth_change=False):
        if not auth_change and self.path.exists():
            current=json.loads(self.path.read_bytes())
            self.data['pin']=current['pin'];self.data['parent_sessions']=current.get('parent_sessions',{})
        tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.data),encoding='utf-8');tmp.replace(self.path)
    def set_pin(self,pin):
        if not isinstance(pin,str) or len(pin)<8:raise ValueError('PIN至少8位')
        if self.path.exists():self.data=json.loads(self.path.read_bytes())
        salt=secrets.token_bytes(16);self.data['pin']={'salt':salt.hex(),'hash':hashlib.scrypt(pin.encode(),salt=salt,n=16384,r=8,p=1).hex()}
        self.data['parent_sessions']={};self.sessions={k:v for k,v in self.sessions.items() if v['role']!='parent'};self.save(auth_change=True)
    def verify(self,pin):
        if self.path.exists():self.data=json.loads(self.path.read_bytes())
        p=self.data['pin'];return p and hmac.compare_digest(p['hash'],hashlib.scrypt(pin.encode(),salt=bytes.fromhex(p['salt']),n=16384,r=8,p=1).hex())
    def pairing(self):self.code=secrets.token_urlsafe(9);self.expires=time.time()+300;return self.code
    def session(self,role,device=None):
        token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
        digest=hashlib.sha256(token.encode()).hexdigest()
        self.sessions[digest]={'role':role,'csrf':csrf,'expires':None if role=='parent' else time.time()+86400,'device':device}
        if role=='parent':
            if self.path.exists():self.data=json.loads(self.path.read_bytes())
            self.data.setdefault('parent_sessions',{})[digest]=self.sessions[digest];self.save(auth_change=True)
        return token,csrf
    def lookup(self,token):
        digest=hashlib.sha256((token or '').encode()).hexdigest();s=self.sessions.get(digest)
        if not s or s['expires'] is not None and s['expires']<time.time():return None
        if s['role']=='parent':
            # A separate local password-reset process invalidates durable sessions
            # too. Read only the hashed references, never persist the raw cookie.
            current=json.loads(self.path.read_bytes())
            if digest not in current.get('parent_sessions',{}):return None
        if s['device'] and not self.data['devices'].get(s['device'],{}).get('enabled'):return None
        return s

def create_app(*,engine=None,root=None,hosts=None,devices=None):
    engine=engine or BookEngine(root or default_root());devices=devices or Devices(root or default_root())
    hosts=set(hosts or ['localhost','127.0.0.1']);core=core_app(engine=engine)
    app=FastAPI(lifespan=core.router.lifespan_context,docs_url=None,openapi_url=None);app.state.engine=engine;app.state.devices=devices
    core.state.request_shutdown=lambda:getattr(app.state,'request_shutdown',lambda:None)()
    def reply(data,role,device=None):
        token,csrf=devices.session(role,device);r=JSONResponse(dict(**data,csrf=csrf,role=role));r.set_cookie('ipad_session',token,secure=True,httponly=True,samesite='strict',max_age=10*365*86400 if role=='parent' else 86400);return r
    @app.middleware('http')
    async def security(request,call_next):
        host=request.url.hostname;peer=request.client.host if request.client else ''
        if host not in hosts or peer not in {'testclient','127.0.0.1','::1'} and not ipaddress.ip_address(peer).is_private:return JSONResponse({'error':'LAN_ONLY'},403)
        if request.url.scheme!='https':return JSONResponse({'error':'HTTPS_REQUIRED'},403)
        if request.headers.get('origin') and request.headers['origin']!=str(request.base_url).rstrip('/'):return JSONResponse({'error':'ORIGIN_DENIED'},403)
        if request.headers.get('sec-fetch-site')=='cross-site':return JSONResponse({'error':'ORIGIN_DENIED'},403)
        public=request.url.path in {'/','/app.js','/style.css','/manifest.webmanifest','/sw.js','/icon.svg','/icon-180.png','/icon-192.png','/icon-512.png','/health','/ipad/login','/ipad/pair'}
        s=devices.lookup(request.cookies.get('ipad_session'));request.state.owner=s
        if not public:
            if not s:return JSONResponse({'error':'DEVICE_AUTH_REQUIRED'},401)
            if request.method not in {'GET','HEAD'} and not hmac.compare_digest(s['csrf'],request.headers.get('x-ipad-csrf','')):return JSONResponse({'error':'CSRF_REQUIRED'},403)
            parent=request.url.path.startswith('/ipad/parent') or request.url.path in {'/studio/config','/studio/connections','/studio/generate','/studio/shutdown'} or request.url.path.endswith('/quote') or request.url.path.startswith('/studio/questions')
            if parent and s['role']!='parent':return JSONResponse({'error':'PARENT_REQUIRED'},403)
        if request.method not in {'GET','HEAD'}:
            limit=4096 if public else 64*1024*1024
            content=bytearray()
            async for chunk in request.stream():
                content.extend(chunk)
                if len(content)>limit:return JSONResponse({'error':'BODY_LIMIT'},413)
            request._body=bytes(content)
        if request.url.path in {'/ipad/login','/ipad/pair'}:
            f=devices.failures.setdefault(peer,[]);f[:]=[t for t in f if t>time.time()-60]
            if len(f)>=6:return JSONResponse({'error':'RATE_LIMIT'},429)
            f.append(time.time())
        result=await call_next(request);result.headers['Cache-Control']='no-store';result.headers['X-Content-Type-Options']='nosniff'
        result.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; worker-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        return result
    @app.get('/')
    def home():return HTMLResponse((STATIC/'index.html').read_text(encoding='utf-8'))
    @app.get('/{asset:path}')
    async def dispatch(asset:str,request:Request):
        if asset in {'app.js','style.css','sw.js','manifest.webmanifest','icon.svg','icon-180.png','icon-192.png','icon-512.png'}:
            types={'js':'application/javascript','css':'text/css','webmanifest':'application/manifest+json','svg':'image/svg+xml','png':'image/png'}
            return Response((STATIC/asset).read_bytes(),media_type=types[asset.rsplit('.',1)[1]])
        if asset=='health':return {'status':'ok','service':'paperbook-ipad','cloud':'WAITING_FOR_KEY' if not engine._key else 'KEY_PRESENT_UNVERIFIED'}
        if asset=='ipad/session':return {'role':request.state.owner['role'],'csrf':request.state.owner['csrf'],'key_present':bool(engine._key)}
        if asset=='ipad/books':return engine.authority.all('book/')
        if asset=='ipad/parent/devices':return devices.data['devices']
        if asset.startswith('demo/') and asset.rsplit('/',1)[-1] in {'demo.mp4','page1.jpg','page2.jpg'}:
            raw=(STATIC/'demo'/asset.rsplit('/',1)[-1]).read_bytes();mime='video/mp4' if asset.endswith('mp4') else 'image/jpeg'
            headers={'Accept-Ranges':'bytes'}
            if request.headers.get('range'):
                import re
                m=re.fullmatch(r'bytes=(\d*)-(\d*)',request.headers['range'])
                if not m or not any(m.groups()):return Response(status_code=416,headers={'Content-Range':f'bytes */{len(raw)}'})
                start=int(m[1]) if m[1] else max(0,len(raw)-int(m[2]));end=min(int(m[2]),len(raw)-1) if m[1] and m[2] else len(raw)-1
                if start>end or start>=len(raw):return Response(status_code=416,headers={'Content-Range':f'bytes */{len(raw)}'})
                headers['Content-Range']=f'bytes {start}-{end}/{len(raw)}';return Response(raw[start:end+1],206,media_type=mime,headers=headers)
            return Response(raw,media_type=mime,headers=headers)
        # Retain original session/CSRF/asset checks after authenticating the
        # household device. Rewrite only trusted ASGI metadata, never headers
        # from an untrusted proxy. No second M1 asset authorization is created.
        return await forward(request)
    async def forward(request):
        scope=dict(request.scope);scope['scheme']='https';scope['server']=('localhost',443)
        scope['headers']=[(k,v) for k,v in scope['headers'] if k.lower() not in {b'host',b'origin'}]+[(b'host',b'localhost')]
        messages=[]
        async def send(message):messages.append(message)
        await core(scope,request.receive,send)
        start=next(x for x in messages if x['type']=='http.response.start')
        raw=b''.join(x.get('body',b'') for x in messages if x['type']=='http.response.body')
        r=Response(raw,status_code=start['status']);r.raw_headers=[(k,v+b'; Secure' if k.lower()==b'set-cookie' and b'; secure' not in v.lower() else v) for k,v in start['headers']];return r
    @app.post('/ipad/login')
    async def login(request:Request):
        data=await request.json()
        if not devices.verify(str(data.get('pin',''))):return JSONResponse({'error':'PIN_INVALID'},403)
        return reply({},'parent')
    @app.post('/ipad/pair')
    async def pair(request:Request):
        data=await request.json()
        if not devices.code or time.time()>devices.expires or not hmac.compare_digest(devices.code,str(data.get('code',''))):return JSONResponse({'error':'PAIRING_INVALID'},403)
        devices.code=None;did=secrets.token_hex(12);devices.data['devices'][did]={'name':str(data.get('name','iPad'))[:40],'enabled':True};devices.save();return reply({},'child',did)
    @app.post('/ipad/parent/pairing')
    def pairing():return {'code':devices.pairing(),'expires_seconds':300}
    @app.get('/ipad/parent/devices')
    def device_list():return devices.data['devices']
    @app.post('/ipad/parent/revoke')
    async def revoke(request:Request):
        did=(await request.json()).get('device');devices.data['devices'].get(did,{})['enabled']=False;devices.save();return {'revoked':True}
    @app.post('/ipad/ocr/{bid}')
    async def ocr(bid:str):
        book=engine.book(bid);rows=[]
        for page in book['pages']:
            raw,_=engine.authority.read(page['asset']);result=await run_in_threadpool(engine.local.ocr,raw);rows.append(dict(page_id=page['id'],**result))
        return {'source_mode':'REAL_LOCAL','pages':rows}
    @app.post('/ipad/parent/qa-permit')
    async def permit(request:Request):
        d=await request.json();cap=d.get('cap_fen')
        if type(cap) is not int or not 100<=cap<=15000 or d.get('consent') is not True:return JSONResponse({'error':'COST_CONSENT_REQUIRED'},409)
        devices.allowances[d['device']]={'job':d['job'],'cap':cap,'expires':time.time()+300};return {'approved':True}
    @app.post('/ipad/ask')
    async def ask(request:Request):
        d=await request.json();s=request.state.owner;permit=devices.allowances.pop(s['device'],None)
        if not permit or permit['expires']<time.time():return JSONResponse({'error':'PARENT_APPROVAL_REQUIRED'},403)
        return await run_in_threadpool(engine.ask,permit['job'],d['page_no'],d['question'],permit['cap'],True,secrets.token_hex(16))
    @app.post('/ipad/lock')
    def lock(request:Request):
        token=request.cookies.get('ipad_session','');digest=hashlib.sha256(token.encode()).hexdigest();devices.sessions.pop(digest,None);devices.data=json.loads(devices.path.read_bytes());devices.data.setdefault('parent_sessions',{}).pop(digest,None);devices.save(auth_change=True)
        r=JSONResponse({'locked':True});r.delete_cookie('ipad_session',secure=True,httponly=True,samesite='strict');return r
    @app.post('/ipad/ask-audio')
    async def ask_audio(request:Request):
        form=await request.form();permit=devices.allowances.pop(request.state.owner['device'],None)
        if not permit or permit['expires']<time.time():return JSONResponse({'error':'PARENT_APPROVAL_REQUIRED'},403)
        raw=await form['audio'].read(10*1024*1024+1)
        return await run_in_threadpool(engine.ask,permit['job'],int(form['page_no']),'',permit['cap'],True,secrets.token_hex(16),raw)
    @app.post('/{path:path}')
    async def writes(path:str,request:Request):return await forward(request)
    return app
