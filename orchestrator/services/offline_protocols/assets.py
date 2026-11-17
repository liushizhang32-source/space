"""P2 output-assets adapter owned by the one existing M1 Authority.

No second signer/grant database, no untrusted path or identity in HTTP.
"""
import hashlib,json,re
from fastapi import FastAPI,Request
from starlette.responses import JSONResponse,Response
from orchestrator.core.ids import new_id
from orchestrator.schemas.common import APIResponse
from ..integration_reference.authority import Denied,require,safe_name
from ..integration_reference.files import WindowsAssetReader
from .billing import offline_only

def asset_id(value):
    require(type(value) is str and re.fullmatch('[a-z][a-z0-9_-]{0,63}',value),'ASSET_ID')
    return value

class PrivateAssets:
    def __init__(self,authority,private_root,*,offline_test=False,reader=None):
        offline_only(authority,offline_test);self.authority=authority
        self.reader=reader or WindowsAssetReader(private_root,max_bytes=64*1024*1024)
        with authority.tx() as db:
            db.execute('CREATE TABLE IF NOT EXISTS output_assets(asset_id TEXT PRIMARY KEY,project TEXT,job TEXT,attempt TEXT,page TEXT,path TEXT,hash TEXT,mime TEXT,revoked INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS revoked_output_jobs(project TEXT,job TEXT,PRIMARY KEY(project,job))')
    def _current(self,db,row):
        a=db.execute('SELECT * FROM attempts WHERE id=?',(row['attempt'],)).fetchone()
        require(a and a['project']==row['project'] and a['state'] in {'SUBMITTED','UNKNOWN','DONE'},'OUTPUT_ATTEMPT_STATE')
        current=db.execute('SELECT attempt FROM current WHERE project=? AND page=?',(a['project'],a['page'])).fetchone()
        require(current and current[0]==a['id'],'STALE_ATTEMPT')
        upstream=db.execute('SELECT identity FROM generation_upstream WHERE attempt_id=?',(a['id'],)).fetchone()
        if upstream:self.authority._vision_check(db,json.loads(upstream[0]),allow_done=True)
        require(not row['revoked'] and not db.execute('SELECT 1 FROM revoked_output_jobs WHERE project=? AND job=?',(row['project'],row['job'])).fetchone(),'ASSET_REVOKED')
    def register_output(self,service,attempt_token,identity,reference):
        offline_only(self.authority,True)
        keys={'asset_id','project_id','job_id','attempt_id','sha256','relative_path','content_type'}
        require(type(reference) is dict and set(reference)==keys,'OUTPUT_SCHEMA');asset_id(reference['asset_id'])
        name=safe_name(reference['relative_path'])
        mime=reference['content_type'];allowed={'audios':('.mp3','audio/mpeg'),'videos':('_video.mp4','video/mp4'),'json':('_story.json','application/json')}
        prefix=name.split('/')[0];require(name.count('/')==1 and prefix in allowed,'OUTPUT_PATH')
        suffix,expected_mime=allowed[prefix]
        require(name.endswith(suffix) and mime==expected_mime and not any(x in name.lower() for x in ['manifest','sidecar','_ocr','_vlm','_refs','_c1','_c2']),'OUTPUT_INTERNAL')
        require(type(reference['sha256']) is str and re.fullmatch('[0-9a-f]{64}',reference['sha256']),'OUTPUT_HASH')
        with self.authority.tx() as db:
            s,t,a=self.authority._bound(db,service,attempt_token,identity,live=False)
            require(a['state'] in {'SUBMITTED','UNKNOWN','DONE'} and a['result'],'OUTPUT_NOT_SUBMITTED')
            require(reference['project_id']==a['project'] and reference['attempt_id']==a['id']
                    and reference['job_id']==json.loads(a['identity'])['job_id'],'OUTPUT_BINDING')
            row=dict(asset_id=reference['asset_id'],project=a['project'],job=reference['job_id'],attempt=a['id'],page=a['page'],path=name,hash=reference['sha256'],mime=mime,revoked=0)
            self._current(db,row)
            old=db.execute('SELECT * FROM output_assets WHERE asset_id=?',(row['asset_id'],)).fetchone()
            require(old is None or dict(old)==row,'OUTPUT_ID_CONFLICT')
            if old is None:db.execute('INSERT INTO output_assets VALUES(?,?,?,?,?,?,?,?,?)',tuple(row.values()))
            self.authority.event(db,'output_registered',subject=s['subject'],project=row['project'],job=row['job'],asset_id=row['asset_id'],attempt_id=a['id'],sha256=row['hash'])
        return row['asset_id']
    def issue(self,service,aid,*,project,job,ttl=60):
        offline_only(self.authority,True);asset_id(aid)
        with self.authority.tx() as db:
            s=self.authority._token(db,service,'service');self.authority._grant(db,s['subject'],project,'assets.read')
            row=db.execute('SELECT * FROM output_assets WHERE asset_id=?',(aid,)).fetchone()
            require(row and row['project']==project and row['job']==job,'ASSET_SCOPE');self._current(db,row)
            return self.authority._mint(db,'asset_access',s['subject'],project,row['attempt'],{aid:row['hash']},ttl=ttl)
    def _authorize(self,db,service,credential,aid,project,job):
        s=self.authority._token(db,service,'service');t=self.authority._token(db,credential,'asset_access')
        require(s['subject']==t['subject'],'SERVICE_MISMATCH')
        self.authority._grant(db,s['subject'],project,'assets.read')
        row=db.execute('SELECT * FROM output_assets WHERE asset_id=?',(aid,)).fetchone()
        require(row and row['project']==project==t['project'] and row['job']==job and row['attempt']==t['attempt'],'ASSET_SCOPE')
        require(json.loads(t['assets'])=={aid:row['hash']},'ASSET_VERSION');self._current(db,row)
        return {**dict(row),'authorized_subject':s['subject']}
    def read(self,service,credential,aid,*,project,job):
        offline_only(self.authority,True);asset_id(aid)
        try:
            with self.authority.tx() as db:row=self._authorize(db,service,credential,aid,project,job)
            raw=self.reader.read_bytes(row['path'])  # First target IO after authorization.
            require(type(raw) is bytes and hashlib.sha256(raw).hexdigest()==row['hash'],'ASSET_VERSION')
            with self.authority.tx() as db:
                again=self._authorize(db,service,credential,aid,project,job)
                require(again==row,'ASSET_CHANGED')
                self.authority.event(db,'output_read',subject=row['authorized_subject'],asset_id=aid,project=project,job=job,sha256=row['hash'])
            return raw,row['mime']
        except (ValueError,TypeError,KeyError) as exc:
            with self.authority.tx() as db:self.authority.event(db,'output_denied',asset_id=aid,reason=str(exc))
            raise Denied('ASSET_ACCESS_DENIED') from None
    def revoke_task(self,project,job):
        with self.authority.tx() as db:
            db.execute('INSERT OR IGNORE INTO revoked_output_jobs VALUES(?,?)',(project,job))
            self.authority.event(db,'output_task_revoked',project=project,job=job)
    def http_app(self):
        app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
        @app.get('/{aid}')
        async def fetch(aid:str,request:Request):
            trace=getattr(request.state,'trace_id',None) or new_id('tr')
            try:
                header=request.headers.get('Authorization','');credential=request.headers.get('X-M1-Asset-Token','')
                require(header.startswith('Bearer ') and len(header)<=8192 and len(credential)<=8192,'MISSING_CREDENTIAL')
                raw,mime=self.read(header[7:],credential,aid,project=request.headers.get('X-M1-Project',''),job=request.headers.get('X-M1-Job',''))
                return Response(raw,media_type=mime,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Trace-ID':trace})
            except (ValueError,TypeError,KeyError) as exc:
                try:
                    with self.authority.tx() as db:self.authority.event(db,'output_http_denied',asset_id=aid[:64],reason=type(exc).__name__)
                except (ValueError,TypeError):pass  # Authority unavailable: still deny, never read.
                payload=APIResponse[dict](code=1005,msg='Asset access denied',trace_id=trace).model_dump(mode='json')
                return JSONResponse(payload,status_code=403,headers={'Cache-Control':'no-store','X-Trace-ID':trace})
        return app
