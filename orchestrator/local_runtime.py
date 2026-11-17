"""Explicit runnable Windows offline assembly, never production activation.

Run: M1_LOCAL_RUNTIME=offline_fixture; uvicorn orchestrator.local_runtime:create_local_app --factory --host 127.0.0.1
M2 invokes its real frozen CLI with fixture models. M3_HTTP settings are explicit;
real OCR/VLM and trusted supplier billing remain separately reviewed profiles.
"""
import argparse,hashlib,json,os,sys,time,threading
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit
from starlette.routing import Mount
from .core.config import Settings
from .main import create_app
from .services.integration_reference import Authority,OfflineKMS,Denied
from .services.integration_reference.authority import require
from .services.integration_reference.files import WindowsAssetReader
from .services.offline_protocols.assets import PrivateAssets
from .services.offline_protocols.billing import ReconciliationConsumer
from .services.vision_supervisor.shared import SharedFences
from .services.vision_supervisor.supervisor import WorkerSpec
from .services.vision_supervisor.durable import DurableSupervisor
from .services.vision_supervisor.gate import Gate
from .vendor.member3_v116.agents.generation.m1_generation import M1GenerationConsumer,GenerationDenied
from .vendor.member3_v116.agents.generation.m1_pipeline import open_session

ROOT=Path(__file__).resolve().parents[1]
SOURCE='m2-pr9-frozen-offline-cli'

class OfflineAssembly:
    def __init__(self,settings):
        require(os.name=='nt' and os.getenv('M1_LOCAL_RUNTIME')=='offline_fixture','EXPLICIT_WINDOWS_OFFLINE_PROFILE_REQUIRED')
        require(settings.deployment_env=='local' and settings.asset_mode=='blocked','PRODUCTION_BLOCKED')
        for endpoint in (settings.member3_tts_http_url,settings.member3_llm_base_url):
            require(not endpoint or urlsplit(endpoint).hostname in {'localhost','127.0.0.1','::1'},'OFFLINE_PROVIDER_MUST_BE_LOOPBACK')
        self.settings=settings;self.app=None
        root=settings.data_dir.resolve();root.mkdir(parents=True,exist_ok=True)
        self.state=root/'.m1-state';self.state.mkdir(exist_ok=True)
        seed=self.state/'test-key.seed';database=self.state/'authority.sqlite'
        fresh=not database.exists()
        if not seed.exists():
            require(fresh,'TEST_KEY_MISSING')
            with seed.open('xb') as stream:stream.write(os.urandom(32));stream.flush();os.fsync(stream.fileno())
        material=seed.read_bytes();require(len(material)==32,'INVALID_TEST_SEED')
        constructor=Authority.provision if fresh else Authority
        self.authority=constructor(database,self.state/'retained.anchor',OfflineKMS(seed=material),lambda:int(time.time()),offline_test=True)
        if fresh:
            self.authority.provision_project('M1')
            for scope in ('generate','assets.read'):self.authority.grant('M3','M1',scope)
        self.fences=SharedFences(self.authority)
        self.assets=PrivateAssets(self.authority,root,offline_test=True)
        self.consumer=ReconciliationConsumer(self.authority,self.state/'inbox.sqlite',offline_test=True)

    @contextmanager
    def service_guard(self):
        import msvcrt
        handle=(self.state/'service.lock').open('a+b')
        try:
            handle.seek(0)
            if not handle.read(1):handle.write(b'0');handle.flush()
            handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        except BaseException:
            handle.close();raise RuntimeError('Only one local HTTP service may own this data directory') from None
        try:
            self.authority.recover() # UNKNOWN retained; no automatic refunds/replays.
            self.consumer.recover()
            yield
        finally:
            handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1);handle.close()

    def service_token(self):return self.authority.service_token('M3',ttl=300)

    def session(self,*,page_id,job_id,request_id,cancelled=lambda:False):
        with self.authority.tx() as db:
            unresolved=db.execute('SELECT a.state FROM current c JOIN attempts a ON a.id=c.attempt WHERE c.project=? AND c.page=?',('M1',page_id)).fetchone()
            if unresolved and unresolved['state'] in {'SUBMITTED','UNKNOWN'}:raise GenerationDenied('ATTEMPT_UNRESOLVED')
        storage=self.app.state.storage
        with storage.lock:page=storage.pages[page_id].copy()
        image=storage.root/page['original']
        raw=WindowsAssetReader(storage.root,max_bytes=16*1024*1024).read_bytes(page['original'])
        require(hashlib.sha256(raw).hexdigest()==page['original_sha256'],'CAPTURE_CHANGED')
        record,_=self.fences.begin(job_id,page_id,input_revision=page.get('input_revision',1))
        supervisor=DurableSupervisor(self.state/'workers',authority=self.authority,deadline=30)
        def spec(_):return WorkerSpec((sys.executable,'-I',str(ROOT/'tools/runtime/m2_entry.py')),SOURCE,environment=(('VISION_BACKEND','fixture'),))
        stopped=threading.Event()
        def monitor():
            while not stopped.wait(.01):
                if cancelled():self.fences.cancel(record);return
        watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
        try:
            if cancelled():self.fences.cancel(record)
            c1=supervisor.run(record,self.fences,'ocr',spec,image)
            c2=supervisor.run(record,self.fences,'vlm',spec,image,c1=c1)
            consumer=M1GenerationConsumer(self.authority,Gate({SOURCE}),self.fences,record,service_token=self.service_token())
            return open_session(consumer,page_id=page_id,request_id=request_id,amount=1000,c1=c1,c2=c2,
                size=(page['image_width'],page['image_height']),image=raw,
                final_messages=[{'role':'user','content':'依据已授权页面的OCR与画面，为儿童生成安全且连贯的故事'}])
        finally:stopped.set();watcher.join();supervisor.close()

    def publish(self,session):
        attempt=session.m1.attempt;service=session.m1.consumer.service_token
        entries=[(f'json/{session.page_id}_story.json','application/json')]
        entries.extend((p.relative_to(session.root).as_posix(),'audio/mpeg') for p in sorted(session.audio_paths))
        if session.video:entries.append((f'videos/{session.page_id}_video.mp4','video/mp4'))
        ids={}
        for relative,mime in entries:
            data=(self.settings.data_dir/relative).read_bytes()
            aid='a_'+hashlib.sha256((attempt.attempt_id+'\0'+relative).encode()).hexdigest()[:40]
            self.assets.register_output(service,attempt.token,dict(attempt.identity),dict(asset_id=aid,project_id='M1',job_id=session.job_id,
                attempt_id=attempt.attempt_id,sha256=hashlib.sha256(data).hexdigest(),relative_path=relative,content_type=mime))
            ids[mime]=aid
        return (self.settings.url('_m1/assets/'+ids['application/json']),
                self.settings.url('_m1/assets/'+ids['video/mp4']) if 'video/mp4' in ids else None)

    def asset_credentials(self,job_id):
        service=self.service_token()
        with self.authority.tx() as db:rows=[dict(x) for x in db.execute('SELECT * FROM output_assets WHERE job=? ORDER BY asset_id',(job_id,))]
        return [dict(asset_id=row['asset_id'],path=row['path'],sha256=row['hash'],url=self.settings.url('_m1/assets/'+row['asset_id']),
            headers={'Authorization':'Bearer '+service,'X-M1-Asset-Token':self.assets.issue(service,row['asset_id'],project='M1',job=job_id),
                     'X-M1-Project':'M1','X-M1-Job':job_id}) for row in rows]

def create_local_app(settings=None):
    settings=replace(settings or Settings(),generation_backend='member3',asset_mode='blocked',persist_state=True)
    runtime=OfflineAssembly(settings)
    app=create_app(settings,m1_session_factory=runtime.session,m1_assets=runtime.assets,m1_publisher=runtime.publish,m1_runtime_guard=runtime.service_guard)
    runtime.app=app;app.state.m1_runtime=runtime
    # Existing Story audio URLs remain valid, but every alias still resolves
    # registered metadata and calls the same Authority; missing auth stays 503.
    for prefix in ('audios','json','videos'):
        app.router.routes.insert(0,Mount('/'+prefix,app=runtime.assets.http_app(path_prefix=prefix)))
    return app

def main():
    parser=argparse.ArgumentParser(description='Trusted local M1 operator only; prints short-lived offline credentials')
    parser.add_argument('command',choices=['asset-credentials','totals']);parser.add_argument('--job')
    args=parser.parse_args();runtime=OfflineAssembly(Settings())
    if args.command=='asset-credentials':
        if not args.job:parser.error('--job required')
        result=runtime.asset_credentials(args.job)
    else:result=runtime.authority.totals()
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
