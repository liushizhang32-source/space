"""Single SQLite authority for offline integration; separate retained anchor detects rollback.

Only trusted M1 code provisions projects/grants/assets or records billing receipts.
Tokens are opaque signed references to durable server records, not a proposed wire contract.
Generation DRAFT is never activated. Blob storage avoids claiming OS ACL/handle safety.
"""
from contextlib import contextmanager, nullcontext
from pathlib import Path, PurePosixPath
from typing import Protocol
import hashlib, json, os, sqlite3, uuid, time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from ..poc_security.crypto import canonical, parse
from .lifecycle import VisionLifecycle


class Denied(ValueError): pass

def require(ok, reason='DENIED'):
    if not ok: raise Denied(reason)

def integer(v, low=0, high=15000):
    require(type(v) is int and low <= v <= high, 'INVALID_AMOUNT')
    return v

def digest(raw): return hashlib.sha256(raw).hexdigest()

def safe_name(name):
    require(type(name) is str and name and '\\' not in name and ':' not in name and '%' not in name
            and not name.startswith('/') and all(p not in ('','.','..') and not p.endswith((' ','.'))
            for p in name.split('/')), 'INVALID_PATH')
    require(str(PurePosixPath(name)) == name, 'INVALID_PATH')
    return name


class KeyProvider(Protocol):
    active: str
    offline_only: bool
    def sign(self, key_id: str, payload: bytes) -> bytes: ...
    def verify(self, key_id: str, signature: bytes, payload: bytes) -> None: ...
    def public_keys(self) -> dict: ...


class OfflineKMS:
    """Ephemeral test keys only; production use rejected at Authority boundary."""
    offline_only = True
    def __init__(self, *, seed=None):
        require(seed is None or type(seed) is bytes and len(seed)>=32,'INVALID_TEST_SEED')
        self._seed=seed;self.keys={};self.used_key_ids=set();self.audit=[];self._observers={}
        self.rotate('offline-1')
    def _audit(self, action, key_id, outcome='PASS'):
        self.audit.append(dict(seq=len(self.audit)+1,component='offline-kms',action=action,key_id=key_id,outcome=outcome))
    def observe(self,name,callback):self._observers[name]=callback
    def _notify(self,action,key_id,public):
        for callback in list(self._observers.values()):callback(action,key_id,public)
    def rotate(self, key_id):
        require(type(key_id) is str and key_id and key_id not in self.used_key_ids,'KEY_ID_REUSE')
        self.used_key_ids.add(key_id)
        candidate=(Ed25519PrivateKey.generate() if self._seed is None else
            Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b'M1-OFFLINE-TEST-KEY\0'+self._seed+canonical(key_id)).digest()))
        try:self._notify('register',key_id,candidate.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw))
        except BaseException:
            self._audit('rotate',key_id,'DENY');raise
        self.keys[key_id]=candidate
        self.active=key_id;self._audit('rotate',key_id)
    def revoke(self, key_id):
        if key_id in self.keys:
            public=self.keys[key_id].public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
            self._notify('revoke',key_id,public)
            self.keys.pop(key_id);self._audit('revoke',key_id)
    def sign(self, key_id, payload):
        if key_id not in self.keys:
            self._audit('sign',key_id,'DENY');raise Denied('UNKNOWN_KEY')
        result=self.keys[key_id].sign(payload);self._audit('sign',key_id);return result
    def verify(self, key_id, signature, payload):
        if key_id not in self.keys:
            self._audit('verify',key_id,'DENY');raise Denied('UNKNOWN_KEY')
        try:self.keys[key_id].public_key().verify(signature,payload)
        except (InvalidSignature,ValueError):
            self._audit('verify',key_id,'DENY');raise Denied('INVALID_SIGNATURE') from None
        self._audit('verify',key_id)
    def public_keys(self):
        self._audit('public_keys',self.active)
        return {k:v.public_key() for k,v in self.keys.items()}



class Authority(VisionLifecycle):
    """Each instance opens independent connections. SQLite serializes cross-process writes.

    Deployment must protect anchor separately. Restoring both DB and anchor is NOT
    detectable without a trusted external high-water service. Offline tests retain anchor.
    Crash between anchor publication and commit fails closed for operator reconciliation.
    """
    _require=staticmethod(require)

    def __init__(self, path, anchor, kms, clock, *, offline_test=False):
        require(offline_test is True and getattr(kms, 'offline_only', False), 'PRODUCTION_BLOCKED')
        self.path, self.anchor = Path(path).resolve(), Path(anchor).resolve()
        require(self.path != self.anchor and self.path.is_file() and self.anchor.is_file(), 'UNPROVISIONED')
        self.kms, self.clock = kms, clock
        with self.tx() as db:
            for key_id,key in self.kms.public_keys().items():
                self._register_key(db,key_id,key.public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw))
        self.kms.observe(str(self.path),self._key_event)

    @classmethod
    def provision(cls, path, anchor, kms, clock, *, offline_test=False):
        require(offline_test is True, 'PRODUCTION_BLOCKED')
        path, anchor = Path(path).resolve(), Path(anchor).resolve()
        require(not path.exists() and not anchor.exists() and path != anchor
                and not Path(str(path)+'.maintenance').exists() and not Path(str(anchor)+'.recovery.jsonl').exists(),'ALREADY_PROVISIONED')
        path.parent.mkdir(parents=True, exist_ok=True); anchor.parent.mkdir(parents=True, exist_ok=True)
        db=sqlite3.connect(path)
        db.executescript('''
        PRAGMA synchronous=FULL;
        CREATE TABLE meta(id INTEGER PRIMARY KEY, db_id TEXT, time INTEGER, bound_path TEXT NOT NULL);
        CREATE TABLE projects(id TEXT PRIMARY KEY, spent INTEGER NOT NULL DEFAULT 0 CHECK(spent BETWEEN 0 AND 15000));
        CREATE TABLE grants(subject TEXT, project TEXT REFERENCES projects(id), scope TEXT, enabled INTEGER, PRIMARY KEY(subject,project,scope));
        CREATE TABLE tokens(id TEXT PRIMARY KEY, kind TEXT, subject TEXT, project TEXT, attempt TEXT, assets TEXT, amount INTEGER, expires INTEGER, status TEXT, key_id TEXT NOT NULL);
        CREATE TABLE current(project TEXT, page TEXT, serial INTEGER, attempt TEXT, PRIMARY KEY(project,page));
        CREATE TABLE vision_current(page_id TEXT PRIMARY KEY,lineage TEXT NOT NULL,identity TEXT,status TEXT,serial INTEGER,manifest_sha256 TEXT);
        CREATE TABLE generation_upstream(attempt_id TEXT PRIMARY KEY REFERENCES attempts(id),identity TEXT NOT NULL);
        CREATE TABLE key_registry(key_id TEXT PRIMARY KEY, public BLOB NOT NULL, status TEXT NOT NULL CHECK(status IN ('ACTIVE','REVOKED')));
        CREATE TABLE stage_attempts(attempt_id TEXT PRIMARY KEY, fencing_token TEXT UNIQUE, logical TEXT,
            ordinal INTEGER CHECK(ordinal IN (1,2)), identity TEXT, owner TEXT, state TEXT,
            retry_allowed INTEGER NOT NULL DEFAULT 0, UNIQUE(logical,ordinal));
        CREATE TABLE attempt_context(id TEXT PRIMARY KEY, prompt_sha256 TEXT, provider TEXT, model TEXT);
        CREATE TABLE attempts(id TEXT PRIMARY KEY, project TEXT, page TEXT, serial INTEGER, identity TEXT, state TEXT, token TEXT, result TEXT);
        CREATE TABLE reservations(id TEXT PRIMARY KEY REFERENCES attempts(id), project TEXT, amount INTEGER, actual INTEGER, state TEXT, receipt TEXT);
        CREATE TABLE assets(project TEXT, name TEXT, version TEXT, content BLOB, PRIMARY KEY(project,name));
        CREATE TABLE requests(id TEXT PRIMARY KEY, fingerprint TEXT, response TEXT);
        CREATE TABLE events(seq INTEGER PRIMARY KEY, payload TEXT, previous TEXT, hash TEXT);
        ''')
        db.execute('INSERT INTO meta VALUES(1,?,?,?)',(uuid.uuid4().hex,integer(clock(),0,9007199254740991),str(path)))
        db.commit(); db.close()
        obj=object.__new__(cls);obj.path=path;obj.anchor=anchor
        db=sqlite3.connect(path);obj._write_anchor(obj._state(db));db.close()
        return cls(path,anchor,kms,clock,offline_test=True)

    @staticmethod
    def _state(db):
        tables=('meta','projects','grants','tokens','current','attempts','attempt_context','key_registry','vision_current','generation_upstream','stage_attempts','reservations','assets','requests','events')
        data={t:[[{'hex':v.hex()} if isinstance(v,bytes) else v for v in r] for r in db.execute('SELECT * FROM '+t+' ORDER BY 1,2')] for t in tables}
        data['schema']=[list(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]
        return digest(canonical(data))

    def _write_anchor(self, value):
        tmp=self.anchor.with_name(self.anchor.name+'.'+uuid.uuid4().hex+'.tmp')
        with tmp.open('xb') as f: f.write(value.encode());f.flush();os.fsync(f.fileno())
        # Windows scanners/readers can briefly deny replacement even though the
        # SQLite writer lock serializes authority instances. Retry only this
        # transient sharing class, bounded, while retaining the same writer lock.
        deadline=time.monotonic()+1.0
        while True:
            try:
                os.replace(tmp,self.anchor)
                break
            except PermissionError:
                if time.monotonic()>=deadline: raise
                time.sleep(0.01)

    @property
    def maintenance_path(self):return Path(str(self.path)+'.maintenance')

    def _check_owner_path(self,db):
        value=db.execute('SELECT bound_path FROM meta WHERE id=1').fetchone()[0]
        require(value==str(self.path),'AUTHORITY_PATH_MISMATCH')

    @contextmanager
    def tx(self):
        require(self.path.is_file() and self.anchor.is_file(), 'UNPROVISIONED')
        require(not self.maintenance_path.exists(),'MAINTENANCE')
        db=sqlite3.connect(self.path,timeout=10,isolation_level=None);db.row_factory=sqlite3.Row
        ready=False
        try:
            db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
            require(not self.maintenance_path.exists(),'MAINTENANCE')
            self._check_owner_path(db)
            require(db.execute('PRAGMA quick_check').fetchone()[0]=='ok','CORRUPT')
            require(self.anchor.read_text()==self._state(db),'ROLLBACK_DETECTED')
            now=integer(self.clock(),0,9007199254740991)
            require(now>=db.execute('SELECT time FROM meta').fetchone()[0],'CLOCK_ROLLBACK')
            db.execute('UPDATE meta SET time=?',(now,))
            # Expiration is persisted even when a public operation is denied.
            expired=db.execute("SELECT id FROM tokens WHERE status='ACTIVE' AND expires<=?",(now,)).fetchall()
            for row in expired:
                db.execute("UPDATE tokens SET status='EXPIRED' WHERE id=?",(row[0],)); self.event(db,'expired',token_id=row[0])
            db.execute('SAVEPOINT business');ready=True
            yield db
            self._write_anchor(self._state(db));db.commit()
        except Denied as exc:
            # Validation callers never mutate business state before all checks.
            # Commit expiry/time only; other failures use rollback below.
            if db.in_transaction:
                if ready:
                    db.execute('ROLLBACK TO business')
                    self.event(db,'denied',reason=str(exc))
                    self._write_anchor(self._state(db));db.commit()
                else: db.rollback()
            raise
        except BaseException:
            if db.in_transaction: db.rollback()
            raise
        finally: db.close()

    def event(self, db, kind, **values):
        last=db.execute('SELECT hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
        prev=last[0] if last else ''
        raw=canonical(dict(kind=kind,at=self.clock(),**values)).decode()
        db.execute('INSERT INTO events(payload,previous,hash) VALUES(?,?,?)',(raw,prev,digest((prev+raw).encode())))

    def provision_project(self, project):
        require(type(project) is str and project, 'INVALID_PROJECT')
        with self.tx() as db:
            # One fixed project account across modules. A second account cannot multiply budget.
            rows=db.execute('SELECT id FROM projects').fetchall()
            require(not rows or rows[0][0]==project,'PROJECT_ACCOUNT_FIXED')
            db.execute('INSERT OR IGNORE INTO projects(id) VALUES(?)',(project,));self.event(db,'project',project=project)

    def grant(self, subject, project, scope, enabled=True):
        require(scope in ('generate','assets.read') and type(enabled) is bool,'INVALID_GRANT')
        with self.tx() as db:
            require(db.execute('SELECT 1 FROM projects WHERE id=?',(project,)).fetchone(),'UNKNOWN_PROJECT')
            db.execute('INSERT OR REPLACE INTO grants VALUES(?,?,?,?)',(subject,project,scope,int(enabled)))
            self.event(db,'grant',subject=subject,project=project,scope=scope,enabled=enabled)

    @staticmethod
    def _grant(db, subject, project, scope):
        row=db.execute('SELECT enabled FROM grants WHERE subject=? AND project=? AND scope=?',(subject,project,scope)).fetchone()
        require(row and row[0]==1,'FORBIDDEN')

    def _mint(self, db, kind, subject, project='', attempt='', assets=None, amount=0, ttl=120):
        integer(ttl,1,300);token_id=uuid.uuid4().hex
        db.execute('INSERT INTO tokens VALUES(?,?,?,?,?,?,?,?,?,?)',(token_id,kind,subject,project,attempt,json.dumps(assets or {}),amount,self.clock()+ttl,'ACTIVE',self.kms.active))
        self._key_active(db,self.kms.active)
        body=canonical({'profile':'offline-reference/0.1','id':token_id,'key_id':self.kms.active})
        wire=json.dumps({'body':body.hex(),'signature':self.kms.sign(self.kms.active,body).hex()},separators=(',',':'))
        self.event(db,'issued',token_id=token_id,kind_name=kind,subject=subject)
        return wire

    def service_token(self, subject, *, ttl=120):
        require(type(subject) is str and subject,'INVALID_SUBJECT')
        with self.tx() as db: return self._mint(db,'service',subject,ttl=ttl)

    def _token(self, db, wire, kind):
        try:
            doc=parse(wire.encode());require(set(doc)=={'body','signature'},'MALFORMED')
            body=bytes.fromhex(doc['body']);claims=parse(body)
            require(set(claims)=={'profile','id','key_id'} and claims['profile']=='offline-reference/0.1','MALFORMED')
            self._key_active(db,claims['key_id'])
            self.kms.verify(claims['key_id'],bytes.fromhex(doc['signature']),body)
        except Denied: raise
        except (ValueError,KeyError,TypeError,AttributeError): raise Denied('MALFORMED') from None
        row=db.execute('SELECT * FROM tokens WHERE id=?',(claims['id'],)).fetchone()
        require(row and row['kind']==kind,'TOKEN_KIND')
        require(row['key_id']==claims['key_id'],'TOKEN_KEY_MISMATCH')
        require(row['status']=='ACTIVE','TOKEN_'+row['status'])
        require(row['expires']>self.clock(),'TOKEN_EXPIRED')
        return row

    def revoke(self, wire, *, kind='attempt'):
        # Trusted administration; no network route. Revocation requires authentic wire.
        with self.tx() as db:
            try: row=self._token(db,wire,kind)
            except Denied as e:
                if str(e)=='TOKEN_REVOKED': return
                raise
            db.execute("UPDATE tokens SET status='REVOKED' WHERE id=?",(row['id'],));self.event(db,'revoked',token_id=row['id'])

    def put_asset(self, project, name, content, *, _db=None):
        safe_name(name);require(type(content) is bytes,'INVALID_ASSET')
        with (self.tx() if _db is None else nullcontext(_db)) as db:
            require(db.execute('SELECT 1 FROM projects WHERE id=?',(project,)).fetchone(),'UNKNOWN_PROJECT')
            db.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?,?)',(project,name,digest(content),content))
            self.event(db,'asset_registered',project=project,name=name,sha256=digest(content))

    def begin(self, service, project, page, request_id, amount, asset_names, *, ttl=120, lineage=None, final_messages=None, provider='fixture', model='offline', _db=None, upstream_identity=None):
        integer(amount,1);integer(ttl,1,300);safe_name(page)
        require(provider=='fixture' and model=='offline','PROVIDER_BLOCKED')
        messages=final_messages if final_messages is not None else [{'role':'user','content':'offline fixture'}]
        require(type(messages) is list and messages,'INVALID_PROMPT')
        ordered=[]
        for msg in messages:
            require(type(msg) is dict and set(msg)=={'role','content'} and all(type(v) is str for v in msg.values()) and msg['role'],'INVALID_PROMPT')
            ordered.append({'role':msg['role'],'content':msg['content']})
        # Frozen prompt algorithm: ordered role/content keys, exact UTF8, no trim.
        prompt_hash=digest(json.dumps(ordered,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8','strict'))
        require(type(request_id) is str and request_id and type(asset_names) is list and asset_names,'INVALID_REQUEST')
        for name in asset_names: safe_name(name)
        if lineage is not None:
            require(type(lineage) is dict and set(lineage)=={'job_id','page_id','generation_id','input_revision','epoch'},'INVALID_LINEAGE')
            require(lineage['page_id']==page and all(type(lineage[k]) is str and lineage[k] for k in ('job_id','page_id','generation_id')),'INVALID_LINEAGE')
            for k in ('input_revision','epoch'): integer(lineage[k],1,9007199254740991)
        with (self.tx() if _db is None else nullcontext(_db)) as db:
            if upstream_identity is not None:
                from dataclasses import asdict
                self._vision_check(db,upstream_identity)
                require(lineage==self._lineage(upstream_identity),'UPSTREAM_LINEAGE')
            subject=self._token(db,service,'service')['subject']
            self._grant(db,subject,project,'generate');self._grant(db,subject,project,'assets.read')
            fp=digest(canonical(dict(subject=subject,project=project,page=page,amount=amount,assets=sorted(asset_names),ttl=ttl,lineage=lineage,prompt_sha256=prompt_hash,provider=provider,model=model,upstream_identity=asdict(upstream_identity) if upstream_identity is not None else None)))
            old=db.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone()
            if old:
                require(old['fingerprint']==fp,'IDEMPOTENCY_CONFLICT');response=json.loads(old['response'])
                self._bound(db,service,response['token'],response['identity'],live=False)
                return response
            current=db.execute('SELECT * FROM current WHERE project=? AND page=?',(project,page)).fetchone()
            if current:
                prior=db.execute('SELECT state FROM attempts WHERE id=?',(current['attempt'],)).fetchone()[0]
                require(prior not in ('RESERVED','SUBMITTED','UNKNOWN'),'ATTEMPT_UNRESOLVED')
            assets={}
            for name in asset_names:
                row=db.execute('SELECT version FROM assets WHERE project=? AND name=?',(project,name)).fetchone()
                require(row,'UNKNOWN_ASSET');assets[name]=row[0]
            spent=db.execute('SELECT spent FROM projects WHERE id=?',(project,)).fetchone()[0]
            held=db.execute("SELECT COALESCE(SUM(amount),0) FROM reservations WHERE state IN ('RESERVED','UNKNOWN')").fetchone()[0]
            require(spent+held+amount<=15000,'BUDGET_EXHAUSTED')
            serial=current['serial']+1 if current else 1;attempt=uuid.uuid4().hex
            identity=dict(job_id=request_id,page_id=page,generation_id=uuid.uuid4().hex,input_revision=1,epoch=serial,attempt_id=attempt,fencing_token=uuid.uuid4().hex)
            if lineage is not None: identity.update(lineage)
            token=self._mint(db,'attempt',subject,project,attempt,assets,amount,ttl)
            token_id=parse(bytes.fromhex(json.loads(token)['body']))['id']
            db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?,NULL)',(attempt,project,page,serial,json.dumps(identity),'RESERVED',token_id))
            if upstream_identity is not None:
                db.execute('INSERT INTO generation_upstream VALUES(?,?)',(attempt,canonical(asdict(upstream_identity)).decode()))
            db.execute('INSERT INTO attempt_context VALUES(?,?,?,?)',(attempt,prompt_hash,provider,model))
            db.execute('INSERT INTO reservations VALUES(?,?,?,0,?,NULL)',(attempt,project,amount,'RESERVED'))
            db.execute('INSERT OR REPLACE INTO current VALUES(?,?,?,?)',(project,page,serial,attempt))
            response=dict(identity=identity,token=token)
            db.execute('INSERT INTO requests VALUES(?,?,?)',(request_id,fp,json.dumps(response)))
            self.event(db,'reserved',attempt_id=attempt,project=project,amount=amount)
            return response

    def _bound(self, db, service, token, identity, *, live=True):
        s=self._token(db,service,'service');t=self._token(db,token,'attempt')
        require(s['subject']==t['subject'],'SERVICE_MISMATCH')
        self._grant(db,s['subject'],t['project'],'generate')
        a=db.execute('SELECT * FROM attempts WHERE id=?',(t['attempt'],)).fetchone()
        require(type(identity) is dict and canonical(identity)==canonical(json.loads(a['identity'])),'FENCING_MISMATCH')
        upstream=db.execute('SELECT identity FROM generation_upstream WHERE attempt_id=?',(a['id'],)).fetchone()
        if upstream:self._vision_check(db,json.loads(upstream['identity']),allow_done=True)
        c=db.execute('SELECT attempt FROM current WHERE project=? AND page=?',(a['project'],a['page'])).fetchone()
        require(c and c[0]==a['id'],'STALE_ATTEMPT')
        if live: require(a['state']=='RESERVED','ATTEMPT_'+a['state'])
        return s,t,a

    def read(self, service, token, identity, name):
        safe_name(name)
        with self.tx() as db:
            s,t,a=self._bound(db,service,token,identity)
            self._grant(db,s['subject'],t['project'],'assets.read')
            allowed=json.loads(t['assets']);require(name in allowed,'ASSET_FORBIDDEN')
            row=db.execute('SELECT * FROM assets WHERE project=? AND name=?',(t['project'],name)).fetchone()
            require(row and row['version']==allowed[name] and digest(row['content'])==allowed[name],'ASSET_VERSION')
            self.event(db,'asset_read',attempt_id=a['id'],name=name,subject=s['subject'])
            return bytes(row['content'])

    def read_file(self, service, token, identity, name, reader):
        """Authorized filesystem read; release only after a second committed check."""
        safe_name(name)
        with self.tx() as db:
            s,t,a=self._bound(db,service,token,identity)
            self._grant(db,s['subject'],t['project'],'assets.read')
            expected=json.loads(t['assets']).get(name)
            require(expected is not None,'ASSET_FORBIDDEN')
        raw=reader.read_bytes(name)
        require(type(raw) is bytes and digest(raw)==expected,'ASSET_VERSION')
        with self.tx() as db:
            s,t,a=self._bound(db,service,token,identity)
            self._grant(db,s['subject'],t['project'],'assets.read')
            row=db.execute('SELECT version FROM assets WHERE project=? AND name=?',(t['project'],name)).fetchone()
            require(row and row['version']==expected and json.loads(t['assets']).get(name)==expected,'ASSET_VERSION')
            self.event(db,'asset_file_read',attempt_id=a['id'],name=name,subject=s['subject'])
        return raw

    def submit(self, service, token, identity, result):
        require(type(result) is bytes and len(result)<=1048576,'INVALID_RESULT')
        with self.tx() as db:
            s,t,a=self._bound(db,service,token,identity,live=False)
            result_hash=digest(result)
            if a['state'] in ('SUBMITTED','UNKNOWN','DONE'):
                require(a['result']==result_hash,'IDEMPOTENCY_CONFLICT');return result_hash
            require(a['state']=='RESERVED','ATTEMPT_'+a['state'])
            db.execute("UPDATE attempts SET state='SUBMITTED',result=? WHERE id=?",(result_hash,a['id']))
            # Receipt must arrive via trusted adapter; an untrusted result never charges.
            db.execute("UPDATE reservations SET state='UNKNOWN' WHERE id=?",(a['id'],))
            self.event(db,'submitted',attempt_id=a['id'],sha256=result_hash)
            return result_hash

    def settle(self, attempt, actual, receipt):
        """Trusted offline billing adapter only, never an M3 self-reported charge."""
        integer(actual);require(type(receipt) is str and receipt,'INVALID_RECEIPT')
        with self.tx() as db:
            r=db.execute('SELECT * FROM reservations WHERE id=?',(attempt,)).fetchone();require(r,'UNKNOWN_ATTEMPT')
            if r['state']=='SETTLED':
                require(r['actual']==actual and r['receipt']==receipt,'IDEMPOTENCY_CONFLICT');return
            require(r['state']=='UNKNOWN' and actual<=r['amount'],'INVALID_SETTLEMENT')
            require(not db.execute('SELECT 1 FROM reservations WHERE receipt=?',(receipt,)).fetchone(),'RECEIPT_REPLAY')
            db.execute('UPDATE projects SET spent=spent+? WHERE id=?',(actual,r['project']))
            db.execute("UPDATE reservations SET state='SETTLED',actual=?,receipt=? WHERE id=?",(actual,receipt,attempt))
            db.execute("UPDATE attempts SET state='DONE' WHERE id=?",(attempt,));self.event(db,'settled',attempt_id=attempt,actual=actual)

    def cancel(self, attempt):
        with self.tx() as db:
            a=db.execute('SELECT * FROM attempts WHERE id=?',(attempt,)).fetchone();require(a,'UNKNOWN_ATTEMPT')
            if a['state']=='CANCELLED':return
            require(a['state']=='RESERVED','UNKNOWN_RETAINS_BUDGET')
            db.execute("UPDATE tokens SET status='REVOKED' WHERE id=?",(a['token'],))
            db.execute("UPDATE attempts SET state='CANCELLED' WHERE id=?",(attempt,))
            db.execute("UPDATE reservations SET state='RELEASED' WHERE id=?",(attempt,));self.event(db,'cancelled',attempt_id=attempt)

    def recover(self):
        with self.tx() as db:
            for a in db.execute("SELECT id FROM attempts WHERE state='SUBMITTED'").fetchall():
                db.execute("UPDATE attempts SET state='UNKNOWN' WHERE id=?",(a[0],))
            self.event(db,'recovered')

    def totals(self):
        with self.tx() as db:
            spent=db.execute('SELECT COALESCE(SUM(spent),0) FROM projects').fetchone()[0]
            held=db.execute("SELECT COALESCE(SUM(amount),0) FROM reservations WHERE state IN ('RESERVED','UNKNOWN')").fetchone()[0]
            return dict(spent=spent,held=held,available=15000-spent-held)

    @contextmanager
    def snapshot_guard(self):
        """Read the exact committed checkpoint while excluding all authority writers."""
        require(self.path.is_file() and self.anchor.is_file(),'UNPROVISIONED')
        require(not self.maintenance_path.exists(),'MAINTENANCE')
        db=sqlite3.connect(self.path,timeout=10,isolation_level=None);db.row_factory=sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            require(not self.maintenance_path.exists(),'MAINTENANCE')
            self._check_owner_path(db)
            require(db.execute('PRAGMA quick_check').fetchone()[0]=='ok','CORRUPT')
            expected=self._state(db)
            require(self.anchor.read_text()==expected,'ROLLBACK_DETECTED')
            require(integer(self.clock(),0,9007199254740991)>=db.execute('SELECT time FROM meta').fetchone()[0],'CLOCK_ROLLBACK')
            yield db,expected
        finally:
            if db.in_transaction:db.rollback()
            db.close()

    def _backup_locked(self,target,expected):
        target=Path(target)
        with target.open('xb'):pass
        src=sqlite3.connect(self.path);dst=sqlite3.connect(target)
        try:
            src.backup(dst)
            require(self._state(dst)==expected,'BACKUP_SNAPSHOT_MISMATCH')
        finally:src.close();dst.close()
        return digest(target.read_bytes())

    def backup(self,target):
        require(not Path(target).exists(),'BACKUP_EXISTS')
        with self.snapshot_guard() as (db,expected):
            return self._backup_locked(target,expected)


    def provenance(self, service, token, identity):
        """Offline signed assertion only; never asserts real provider execution."""
        with self.tx() as db:
            s,t,a=self._bound(db,service,token,identity,live=False)
            require(a['state'] in ('SUBMITTED','DONE'),'RESULT_REQUIRED')
            context=dict(db.execute('SELECT * FROM attempt_context WHERE id=?',(a['id'],)).fetchone())
            body=canonical(dict(profile='offline-provenance/0.1',key_id=self.kms.active,
                identity=identity,inputs=json.loads(t['assets']),result_sha256=a['result'],
                prompt_sha256=context['prompt_sha256'],provider=context['provider'],model=context['model'],source_mode='fixture'))
            self._key_active(db,self.kms.active)
            signature=self.kms.sign(self.kms.active,body)
            self.event(db,'provenance_signed',attempt_id=a['id'],key_id=self.kms.active)
            return dict(body=body.hex(),signature=signature.hex())

    def verify_provenance(self, proof, *, expected_identity, expected_result):
        try:
            body=bytes.fromhex(proof['body']);doc=parse(body)
            with self.tx() as db:self._key_active(db,doc['key_id'])
            self.kms.verify(doc['key_id'],bytes.fromhex(proof['signature']),body)
            require(doc['profile']=='offline-provenance/0.1' and doc['source_mode']=='fixture','PROFILE_BLOCKED')
            require(canonical(doc['identity'])==canonical(expected_identity) and doc['result_sha256']==digest(expected_result),'PROVENANCE_MISMATCH')
            return doc
        except Denied: raise
        except (KeyError,ValueError,TypeError): raise Denied('MALFORMED_PROVENANCE') from None


    def reserve_stage(self, identity, stage, owner):
        """Frozen F08 counter; trusted M1 supervisor only, no new wire fields."""
        from dataclasses import asdict
        i=asdict(identity)
        require(stage in ('ocr','vlm') and type(owner) is str and owner,'STAGE_OWNER')
        for k in ('job_id','page_id','generation_id','attempt_id','fencing_token'):
            require(type(i[k]) is str and i[k],'STAGE_IDENTITY')
        for k in ('input_revision','epoch'):integer(i[k],1,9007199254740991)
        logical=canonical({k:i[k] for k in ('job_id','page_id','generation_id','input_revision','epoch')} | {'stage':stage}).decode()
        raw=canonical(i).decode()
        with self.tx() as db:
            old=db.execute('SELECT * FROM stage_attempts WHERE attempt_id=?',(i['attempt_id'],)).fetchone()
            if old:
                require(old['identity']==raw and old['owner']==owner and old['logical']==logical,'STAGE_IDEMPOTENCY_CONFLICT')
                return dict(old)
            previous=db.execute('SELECT * FROM stage_attempts WHERE logical=? ORDER BY ordinal DESC LIMIT 1',(logical,)).fetchone()
            if previous:
                require(previous['state'] not in ('RESERVED','DISPATCHED','UNKNOWN'),'STAGE_UNRESOLVED')
                require(previous['ordinal']<2,'STAGE_LIMIT')
                require(previous['state']=='FAILED' and previous['retry_allowed']==1,'STAGE_FINAL')
            require(not db.execute('SELECT 1 FROM stage_attempts WHERE fencing_token=?',(i['fencing_token'],)).fetchone(),'STAGE_TOKEN_REPLAY')
            vision=db.execute('SELECT 1 FROM vision_current WHERE page_id=?',(i['page_id'],)).fetchone()
            if vision:self._vision_check(db,i,require_attempt=False)
            ordinal=previous['ordinal']+1 if previous else 1
            db.execute('INSERT INTO stage_attempts VALUES(?,?,?,?,?,?,?,0)',(i['attempt_id'],i['fencing_token'],logical,ordinal,raw,owner,'RESERVED'))
            if vision:
                db.execute("UPDATE vision_current SET identity=?,status='RUNNING' WHERE page_id=?",(raw,i['page_id']))
            self.event(db,'stage_reserved',attempt_id=i['attempt_id'],stage=stage,ordinal=ordinal,owner=owner)
            return dict(db.execute('SELECT * FROM stage_attempts WHERE attempt_id=?',(i['attempt_id'],)).fetchone())

    @staticmethod
    def _stage_owned(db,identity,owner):
        from dataclasses import asdict
        row=db.execute('SELECT * FROM stage_attempts WHERE attempt_id=?',(identity.attempt_id,)).fetchone()
        require(row and row['identity']==canonical(asdict(identity)).decode() and row['owner']==owner,'STAGE_OWNER_MISMATCH')
        return row

    def dispatch_stage(self,identity,owner):
        with self.tx() as db:
            row=self._stage_owned(db,identity,owner)
            require(row['state']=='RESERVED','STAGE_DISPATCH_REPLAY')
            if db.execute('SELECT 1 FROM vision_current WHERE page_id=?',(identity.page_id,)).fetchone():
                self._vision_check(db,identity)
            db.execute("UPDATE stage_attempts SET state='DISPATCHED' WHERE attempt_id=?",(identity.attempt_id,))
            self.event(db,'stage_dispatch_barrier',attempt_id=identity.attempt_id,owner=owner)

    def finish_stage(self,identity,owner,*,outcome,terminal_confirmed,retry_allowed=False):
        require(outcome in ('SUCCEEDED','FAILED','CANCELLED') and type(terminal_confirmed) is bool
                and type(retry_allowed) is bool,'STAGE_TERMINAL_PROOF')
        state=outcome if terminal_confirmed else 'UNKNOWN'
        retry=bool(state=='FAILED' and retry_allowed)
        with self.tx() as db:
            row=self._stage_owned(db,identity,owner)
            if row['state'] in ('SUCCEEDED','FAILED','CANCELLED','UNKNOWN'):
                require(row['state']==state and row['retry_allowed']==int(retry),'STAGE_TERMINAL_CONFLICT')
                return
            require(row['state'] in ('RESERVED','DISPATCHED'),'STAGE_STATE')
            db.execute('UPDATE stage_attempts SET state=?,retry_allowed=? WHERE attempt_id=?',(state,int(retry),identity.attempt_id))
            self.event(db,'stage_terminal',attempt_id=identity.attempt_id,owner=owner,outcome=state,retry_allowed=retry)


    def reconcile_stage(self,identity,owner,*,outcome,terminal_confirmed,retry_allowed=False):
        """Trusted offline terminal adapter; only the original durable owner/key.

        This never refunds an ordinal or redispatches. Real backend proof must be
        supplied by a separately approved adapter, never a worker body assertion.
        """
        require(outcome in ('SUCCEEDED','FAILED','CANCELLED') and terminal_confirmed is True
                and type(retry_allowed) is bool,'STAGE_TERMINAL_PROOF')
        retry=bool(outcome=='FAILED' and retry_allowed)
        with self.tx() as db:
            row=self._stage_owned(db,identity,owner)
            if row['state'] in ('SUCCEEDED','FAILED','CANCELLED'):
                require(row['state']==outcome and row['retry_allowed']==int(retry),'STAGE_TERMINAL_CONFLICT')
                return
            require(row['state'] in ('RESERVED','DISPATCHED','UNKNOWN'),'STAGE_STATE')
            db.execute('UPDATE stage_attempts SET state=?,retry_allowed=? WHERE attempt_id=?',(outcome,int(retry),identity.attempt_id))
            self.event(db,'stage_reconciled',attempt_id=identity.attempt_id,owner=owner,outcome=outcome,retry_allowed=retry)


    def _register_key(self,db,key_id,public):
        row=db.execute('SELECT * FROM key_registry WHERE key_id=?',(key_id,)).fetchone()
        if row:
            require(bytes(row['public'])==public,'KEY_ID_REUSE')
            # Reopening a provider never upgrades durable REVOKED back to ACTIVE.
            return
        db.execute('INSERT INTO key_registry VALUES(?,?,?)',(key_id,public,'ACTIVE'))
        self.event(db,'key_registered',key_id=key_id)

    def _key_event(self,action,key_id,public):
        with self.tx() as db:
            if action=='register':
                self._register_key(db,key_id,public)
                require(db.execute('SELECT status FROM key_registry WHERE key_id=?',(key_id,)).fetchone()[0]=='ACTIVE','KEY_ID_REUSE')
            else:
                row=db.execute('SELECT * FROM key_registry WHERE key_id=?',(key_id,)).fetchone()
                require(row and bytes(row['public'])==public,'UNKNOWN_KEY')
                if row['status']=='ACTIVE':
                    db.execute("UPDATE key_registry SET status='REVOKED' WHERE key_id=?",(key_id,))
                    self.event(db,'key_revoked',key_id=key_id)

    def _key_active(self,db,key_id):
        row=db.execute('SELECT * FROM key_registry WHERE key_id=?',(key_id,)).fetchone()
        require(row and row['status']=='ACTIVE','UNKNOWN_KEY')
        key=self.kms.public_keys().get(key_id)
        require(key is not None,'UNKNOWN_KEY')
        public=key.public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        require(bytes(row['public'])==public,'KEY_ID_REUSE')

    def public_keys(self):
        """Durably filtered public-only distribution; no private material."""
        with self.tx() as db:
            result={row['key_id']:bytes(row['public']).hex() for row in db.execute("SELECT * FROM key_registry WHERE status='ACTIVE'")}
            self.event(db,'public_keys_distributed')
            return result
