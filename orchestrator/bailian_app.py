"""Loopback-only real-model studio, alongside unchanged member 4/legacy APIs."""
import asyncio,os,secrets,time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI,Request,UploadFile,File,Form,HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse,Response,JSONResponse
from starlette.concurrency import run_in_threadpool
from .services.bailian.engine import BookEngine
from .services.bailian.config import ModelConfig
from .services.bailian.errors import IntegrationError
from .services.integration_reference.authority import Denied

FRONT=Path(__file__).with_name('studio')
MAX_BODY=64*1024*1024

def default_root():
    # Fixed across code checkouts and model choices, never a per-job budget.
    return Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'PaperbookZhiban'/'m1-local-cloud'

def create_app(*,state_root=None,engine=None):
    runtime=engine or BookEngine(state_root or default_root());sessions={}
    if not engine:runtime._key=os.environ.get('DASHSCOPE_API_KEY','')
    @asynccontextmanager
    async def lifespan(app):
        yield
        await run_in_threadpool(runtime.close)
    app=FastAPI(title='纸书智伴·本地工作室',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.engine=runtime
    @app.exception_handler(IntegrationError)
    async def integration_error(request,exc):return JSONResponse({'error':exc.code,'uncertain':exc.uncertain},status_code=409)
    @app.exception_handler(Denied)
    async def denied(request,exc):return JSONResponse({'error':'M1_AUTHORITY_DENIED','reason':str(exc)},status_code=403)
    @app.exception_handler(RequestValidationError)
    async def invalid(request,exc):return JSONResponse({'error':'REQUEST_INVALID'},status_code=422)
    @app.exception_handler(Exception)
    async def unexpected(request,exc):return JSONResponse({'error':'REQUEST_OR_WORKFLOW_INVALID'},status_code=400)
    @app.middleware('http')
    async def protect(request,call_next):
        host=request.url.hostname
        if host not in {'127.0.0.1','localhost','::1','testserver'}:return JSONResponse({'error':'LOOPBACK_HOST_REQUIRED'},status_code=403)
        origin=request.headers.get('origin')
        if origin and origin!=str(request.base_url).rstrip('/'):
            return JSONResponse({'error':'CROSS_ORIGIN_DENIED'},status_code=403)
        if request.headers.get('sec-fetch-site')=='cross-site':return JSONResponse({'error':'CROSS_SITE_DENIED'},status_code=403)
        try:length=int(request.headers.get('content-length','0') or '0')
        except ValueError:return JSONResponse({'error':'CONTENT_LENGTH_INVALID'},status_code=400)
        if length<0 or length>MAX_BODY:return JSONResponse({'error':'BODY_LIMIT'},status_code=413)
        if request.method not in {'GET','HEAD'}:
            body=bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>MAX_BODY:return JSONResponse({'error':'BODY_LIMIT'},status_code=413)
            request._body=bytes(body)
            if request.headers.get('content-type','').split(';')[0]=='application/json':
                from .services.bailian.jsonutil import loads
                try:
                    data=loads(request._body)
                    if not isinstance(data,dict):raise IntegrationError('JSON_OBJECT_REQUIRED')
                except IntegrationError:return JSONResponse({'error':'JSON_INVALID'},status_code=400)
        if request.url.path.startswith('/studio/') and request.url.path!='/studio/session':
            sid=request.cookies.get('paperbook_session');session=sessions.get(sid)
            if not session or time.time()-session['last_seen']>24*3600:return JSONResponse({'error':'SESSION_REQUIRED'},status_code=401)
            session['last_seen']=time.time()
            if request.method not in {'GET','HEAD'} and not secrets.compare_digest(request.headers.get('x-csrf-token',''),session['csrf']):
                return JSONResponse({'error':'CSRF_REQUIRED'},status_code=403)
        result=await call_next(request)
        result.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return result
    @app.get('/')
    def index():return HTMLResponse((FRONT/'index.html').read_text(encoding='utf-8'))
    @app.get('/app.js')
    def js():return Response((FRONT/'app.js').read_bytes(),media_type='application/javascript')
    @app.get('/style.css')
    def css():return Response((FRONT/'style.css').read_bytes(),media_type='text/css')
    @app.get('/health')
    def health():return {'status':'ok','service':'paperbook-real-model-studio','production_ready':False}
    @app.get('/studio/session')
    def session(request:Request):
        sid=request.cookies.get('paperbook_session')
        if sid not in sessions:
            sid=secrets.token_urlsafe(32);sessions[sid]=dict(csrf=secrets.token_urlsafe(32),last_seen=time.time())
        response=JSONResponse({'csrf':sessions[sid]['csrf']})
        response.set_cookie('paperbook_session',sid,httponly=True,samesite='strict',max_age=86400,path='/')
        return response
    @app.get('/studio/config')
    def config():return runtime.status()
    @app.post('/studio/config')
    async def set_config(request:Request):
        from pydantic import ValidationError
        data=await request.json()
        try:configuration=ModelConfig.model_validate(data.get('config',{}))
        except (ValueError,TypeError):raise IntegrationError('CONFIG_INVALID') from None
        return await run_in_threadpool(runtime.configure,configuration,data.get('api_key'))
    @app.post('/studio/connections')
    async def connection():return await run_in_threadpool(runtime.connection)
    @app.post('/studio/shutdown')
    def shutdown():
        callback=getattr(app.state,'request_shutdown',None)
        if callback is None:raise IntegrationError('SERVER_LAUNCHER_REQUIRED')
        callback();return {'status':'SHUTTING_DOWN','workers_awaited':True}
    @app.post('/studio/books')
    async def upload(files:list[UploadFile]=File(...)):
        if len(files)>30:raise IntegrationError('UPLOAD_COUNT_LIMIT')
        content=[];total=0
        for f in files:
            raw=await f.read(20*1024*1024+1);total+=len(raw)
            if total>MAX_BODY:raise IntegrationError('BODY_LIMIT')
            content.append((f.filename or '',raw));await f.close()
        return await run_in_threadpool(runtime.upload,content)
    @app.get('/studio/books/{bid}')
    def book(bid:str):return runtime.book(bid)
    @app.post('/studio/books/{bid}/order')
    async def order(bid:str,request:Request):return await run_in_threadpool(runtime.reorder,bid,(await request.json())['page_ids'])
    @app.post('/studio/books/{bid}/quote')
    async def quote(bid:str,request:Request):
        data=await request.json();return runtime.quote(bid,data['age'],data.get('title',''))
    @app.post('/studio/generate')
    async def generate(request:Request):
        data=await request.json()
        return runtime.generate(data['quote_id'],data['cap_fen'],data.get('cloud_consent') is True,
            data.get('account_permissions_confirmed') is True,data.get('request_id'))
    @app.get('/studio/jobs')
    def jobs():return sorted(runtime.authority.all('job/'),key=lambda x:x['created_at'],reverse=True)[:50]
    @app.get('/studio/jobs/{jid}')
    def job(jid:str):return runtime.job(jid)
    @app.post('/studio/jobs/{jid}/cancel')
    def cancel(jid:str):return runtime.cancel(jid)
    @app.post('/studio/jobs/{jid}/resume')
    def resume(jid:str):return runtime.resume(jid)
    @app.get('/studio/assets/{name:path}')
    def asset(name:str,request:Request):
        from .services.integration_reference.authority import safe_name
        safe_name(name)
        meta=runtime.authority.get('object/'+name)
        if not meta:raise HTTPException(404)
        raw,meta=runtime.authority.read(name,job=meta['job'])
        headers={'Content-Disposition':'inline; filename="'+name.rsplit('/',1)[-1]+'"','Accept-Ranges':'bytes'}
        range_=request.headers.get('range')
        if range_:
            import re
            m=re.fullmatch(r'bytes=(\d*)-(\d*)',range_)
            if not m or not any(m.groups()):return Response(status_code=416,headers={'Content-Range':f'bytes */{len(raw)}'})
            start=int(m[1]) if m[1] else max(0,len(raw)-int(m[2]));end=min(len(raw)-1,int(m[2])) if m[1] and m[2] else len(raw)-1
            if start>end or start>=len(raw):return Response(status_code=416,headers={'Content-Range':f'bytes */{len(raw)}'})
            headers['Content-Range']=f'bytes {start}-{end}/{len(raw)}'
            return Response(raw[start:end+1],status_code=206,media_type=meta['mime'],headers=headers)
        return Response(raw,media_type=meta['mime'],headers=headers)
    @app.post('/studio/questions')
    async def question(request:Request):
        data=await request.json()
        return await run_in_threadpool(runtime.ask,data['job_id'],data['page_no'],data['question'],data['cap_fen'],
            data.get('consent') is True,data['request_id'])
    @app.post('/studio/questions/audio')
    async def audio_question(audio:UploadFile=File(...),request:str=Form(...)):
        from .services.bailian.jsonutil import loads
        data=loads(request);raw=await audio.read(10*1024*1024+1);await audio.close()
        return await run_in_threadpool(runtime.ask,data['job_id'],data['page_no'],data.get('question',''),data['cap_fen'],
            data.get('consent') is True,data['request_id'],raw)
    return app
