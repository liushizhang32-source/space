"""Local cloud-workflow profile of the existing M1 authority (P5, PROPOSED).

All grants, leases, input/output bytes, budgets and journal share its retained
anchor. This is not a second permission system or a production KMS.
"""
import hashlib,json,secrets,time
from pathlib import Path
from ..integration_reference.authority import Authority,OfflineKMS,require,digest
from .jsonutil import encoded

PROJECT='paperbook'
SUBJECT='local-book-owner'

class CloudAuthority:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        key=self.root/'local-development-signing.seed'
        db=self.root/'m1.sqlite';anchor=self.root/'m1.retained-anchor'
        if not key.exists():
            require(not db.exists() and not anchor.exists(),'SIGNING_KEY_MISSING')
            with key.open('xb') as f:f.write(secrets.token_bytes(32))
        kms=OfflineKMS(seed=key.read_bytes())
        factory=Authority if db.exists() or anchor.exists() else Authority.provision
        self.m1=factory(db,anchor,kms,lambda:int(time.time()),offline_test=True,local_cloud=True)
        with self.m1.tx() as con:
            con.execute('CREATE TABLE IF NOT EXISTS cloud_documents(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            initialized=con.execute("SELECT 1 FROM cloud_documents WHERE key='initialized'").fetchone()
        if not initialized:
            self.m1.provision_project(PROJECT)
            self.m1.grant(SUBJECT,PROJECT,'generate');self.m1.grant(SUBJECT,PROJECT,'assets.read')
            self.put('initialized',{'profile':'local-cloud-development/1','production_ready':False})
        self.m1.recover()
    def service(self):return self.m1.service_token(SUBJECT,ttl=300)
    def _authorize(self,con,scope='assets.read'):
        # The caller is trusted M1 backend; browser sessions are authenticated at
        # the HTTP boundary. No browser-supplied subject/project is accepted.
        self.m1._grant(con,SUBJECT,PROJECT,scope)
    def get(self,key,default=None,*,con=None):
        if con is None:
            with self.m1.tx() as db:return self.get(key,default,con=db)
        self._authorize(con)
        row=con.execute('SELECT value FROM cloud_documents WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default
    def put(self,key,value,*,con=None):
        if con is None:
            with self.m1.tx() as db:return self.put(key,value,con=db)
        self._authorize(con,'generate')
        con.execute('INSERT OR REPLACE INTO cloud_documents VALUES(?,?)',(key,encoded(value).decode()))
    def all(self,prefix):
        with self.m1.tx() as con:
            self._authorize(con)
            return [json.loads(r[0]) for r in con.execute('SELECT value FROM cloud_documents WHERE key LIKE ?',(prefix+'%',))]
    def store(self,name,raw,mime,*,job=None):
        require(type(raw) is bytes and len(raw)<=64*1024*1024,'ASSET_SIZE_LIMIT')
        with self.m1.tx() as con:
            self._authorize(con,'generate')
            if job:self.bound(job,con=con)
            existing=self.get('object/'+name,con=con)
            if existing:
                require(existing['sha256']==digest(raw) and existing['job']==job and existing['mime']==mime,'OUTPUT_IMMUTABLE')
                return
            self.m1.put_asset(PROJECT,name,raw,_db=con)
            self.put('object/'+name,dict(name=name,mime=mime,job=job,sha256=digest(raw),bytes=len(raw)),con=con)
    def read(self,name,*,job=None,con=None):
        if con is None:
            with self.m1.tx() as db:return self.read(name,job=job,con=db)
        self._authorize(con)
        meta=self.get('object/'+name,con=con);require(meta,'UNKNOWN_ASSET')
        if meta['job']:
            require(job==meta['job'],'ASSET_JOB_MISMATCH');self.bound(job,con=con)
        row=con.execute('SELECT content,version FROM assets WHERE project=? AND name=?',(PROJECT,name)).fetchone()
        require(row and digest(row['content'])==meta['sha256']==row['version'],'ASSET_VERSION')
        return bytes(row['content']),meta
    def reserve(self,job,book,amount,plan):
        with self.m1.tx() as con:
            service=self.m1._mint(con,'service',SUBJECT,ttl=300)
            previous=con.execute('SELECT serial FROM current WHERE project=? AND page=?',(PROJECT,book['id'])).fetchone()
            attempt=self.m1.begin(service,PROJECT,book['id'],job,amount,
                [p['asset'] for p in book['pages']],ttl=300,provider='dashscope',model='cloud-workflow-plan/1',_db=con,
                lineage=dict(job_id=job,page_id=book['id'],generation_id=secrets.token_hex(16),input_revision=book['revision'],epoch=previous[0]+1 if previous else 1),
                final_messages=[{'role':'system','content':encoded(plan).decode()}])
            # Freeze the APPROVED PLAN, not a fabricated story result. Every paid
            # dispatch is journaled under it. UNKNOWN holds the complete cap until
            # a trusted billing receipt arrives; usage never goes to settle().
            self.put('lease/'+job,dict(**attempt,plan_sha256=digest(encoded(plan)),approved_plan=plan),con=con)
        return attempt['identity']
    def bound(self,job,*,con=None):
        if con is None:
            with self.m1.tx() as db:return self.bound(job,con=db)
        self._authorize(con,'generate')
        info=self.get('job/'+job,con=con);require(info and not info.get('cancel_requested'),'JOB_REVOKED')
        if info.get('source_job'):self.bound(info['source_job'],con=con)
        lease=self.get('lease/'+job,con=con);require(lease,'UNKNOWN_ATTEMPT')
        a=con.execute('SELECT * FROM attempts WHERE id=?',(lease['identity']['attempt_id'],)).fetchone()
        require(a and (a['state']=='RESERVED' and a['result'] is None or
            a['state'] in {'SUBMITTED','UNKNOWN','DONE'} and a['result']==lease['plan_sha256']),'ATTEMPT_UNRESOLVED')
        old=con.execute('SELECT * FROM tokens WHERE id=?',(a['token'],)).fetchone()
        require(old and old['status'] in {'ACTIVE','EXPIRED'},'TOKEN_REVOKED')
        self.m1._key_active(con,old['key_id'])
        # Trusted M1 renewal keeps the same identity, assets, grant and current
        # fence. Expiration alone can renew; revocation can never renew.
        if old['expires']<=self.m1.clock()+30:
            c=con.execute('SELECT attempt FROM current WHERE project=? AND page=?',(PROJECT,a['page'])).fetchone()
            require(c and c[0]==a['id'],'STALE_ATTEMPT')
            wire=self.m1._mint(con,'attempt',SUBJECT,PROJECT,a['id'],json.loads(old['assets']),old['amount'],300)
            token_id=json.loads(bytes.fromhex(json.loads(wire)['body']))['id']
            con.execute("UPDATE tokens SET status='REVOKED' WHERE id=?",(old['id'],))
            con.execute('UPDATE attempts SET token=? WHERE id=?',(token_id,a['id']))
            lease['token']=wire;self.put('lease/'+job,lease,con=con)
        service=self.m1._mint(con,'service',SUBJECT,ttl=120)
        s,t,a=self.m1._bound(con,service,lease['token'],lease['identity'],live=False)
        self.m1._grant(con,SUBJECT,PROJECT,'assets.read')
        return lease
    def dispatch(self,job,*,con):
        lease=self.bound(job,con=con)
        service=self.m1._mint(con,'service',SUBJECT,ttl=120)
        return self.m1.submit(service,lease['token'],lease['identity'],encoded(lease['approved_plan']),_db=con)
    def release_unsubmitted(self,job):
        """Only original RESERVED attempts; UNKNOWN is never released here."""
        with self.m1.tx() as con:
            self._authorize(con,'generate');lease=self.get('lease/'+job,con=con)
            if not lease:return False
            row=con.execute('SELECT state FROM attempts WHERE id=?',(lease['identity']['attempt_id'],)).fetchone()
            if row and row['state']=='RESERVED':
                self.m1.cancel(lease['identity']['attempt_id'],_db=con);return True
            return False
    def billing_status(self,job):
        with self.m1.tx() as con:
            lease=self.get('lease/'+job,con=con)
            if not lease:return 'NOT_RESERVED'
            row=con.execute('SELECT state FROM reservations WHERE id=?',(lease['identity']['attempt_id'],)).fetchone()
            return {'RELEASED':'NOT_CHARGED_RELEASED','SETTLED':'SETTLED'}.get(row[0] if row else '', 'UNKNOWN')
    def input(self,job,name):
        with self.m1.tx() as con:
            lease=self.bound(job,con=con)
            t=con.execute('SELECT assets FROM tokens WHERE id=(SELECT token FROM attempts WHERE id=?)',(lease['identity']['attempt_id'],)).fetchone()
            allowed=json.loads(t[0]);require(name in allowed,'ASSET_FORBIDDEN')
            raw,meta=self.read(name,con=con)
            require(digest(raw)==allowed[name],'ASSET_VERSION')
            return raw
