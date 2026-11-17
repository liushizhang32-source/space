"""P1: durable inbox around the single original M1 financial authority."""
import hashlib,json,os,re,sqlite3
from pathlib import Path
from ..integration_reference.authority import Denied,require
from ..poc_security.crypto import canonical,parse

KEYS={'version','mode','event_id','project_id','attempt_id','result_sha256','actual_fen','receipt_id','outcome'}
DOMAIN=b'M1-OFFLINE-SETTLEMENT-v1\0'

def offline_only(authority,explicit):
    require(explicit is True and getattr(authority.kms,'offline_only',False)
            and os.getenv('M1_DEPLOYMENT_ENV','local')=='local','PRODUCTION_BLOCKED')

def validate_event(p):
    require(type(p) is dict and set(p)==KEYS,'BILLING_SCHEMA')
    require(p['version']=='1.0' and p['mode']=='offline_fixture' and p['outcome']=='SETTLED','BILLING_PROFILE')
    for k in ['event_id','project_id','attempt_id','receipt_id']:
        require(type(p[k]) is str and 0<len(p[k])<=128 and p[k].strip()==p[k],'BILLING_ID')
    require(type(p['result_sha256']) is str and re.fullmatch('[0-9a-f]{64}',p['result_sha256']),'BILLING_HASH')
    require(type(p['actual_fen']) is int and 0<=p['actual_fen']<=15000,'BILLING_AMOUNT')
    canonical(p)
    return p

class OfflineSettlementAdapter:
    def __init__(self,authority,*,offline_test=False):
        offline_only(authority,offline_test);self.authority=authority
    def sign(self,payload):
        offline_only(self.authority,True);validate_event(payload)
        key=self.authority.kms.active
        return dict(payload=dict(payload),key_id=key,
                    signature=self.authority.kms.sign(key,DOMAIN+canonical(payload)).hex())
    def evidence(self,attempt,actual_fen,*,event_id,receipt_id):
        with self.authority.tx() as db:
            a=db.execute('SELECT * FROM attempts WHERE id=?',(attempt,)).fetchone()
            require(a and a['result'],'UNKNOWN_ATTEMPT')
            return self.sign(dict(version='1.0',mode='offline_fixture',event_id=event_id,
                project_id=a['project'],attempt_id=attempt,result_sha256=a['result'],
                actual_fen=actual_fen,receipt_id=receipt_id,outcome='SETTLED'))

class ReconciliationConsumer:
    def __init__(self,authority,inbox_path,*,offline_test=False):
        offline_only(authority,offline_test);self.authority=authority;self.path=Path(inbox_path)
        require(self.path.resolve()!=authority.path,'INBOX_MUST_BE_SEPARATE')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:db.executescript('''
            CREATE TABLE IF NOT EXISTS inbox(event_id TEXT PRIMARY KEY,hash TEXT NOT NULL,envelope TEXT NOT NULL,state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cursor(source TEXT PRIMARY KEY,offset INTEGER NOT NULL,hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY,kind TEXT NOT NULL,reference TEXT NOT NULL,detail TEXT NOT NULL);
        ''')
    def db(self):
        db=sqlite3.connect(self.path,timeout=30);db.row_factory=sqlite3.Row
        db.execute('PRAGMA synchronous=FULL');return db
    def audit(self,kind,reference,detail):
        with self.db() as db:db.execute('INSERT INTO audit(kind,reference,detail) VALUES(?,?,?)',(kind,reference,detail))
    def verify(self,envelope):
        require(type(envelope) is dict and set(envelope)=={'payload','key_id','signature'},'BILLING_ENVELOPE')
        p=validate_event(envelope['payload'])
        try:
            require(type(envelope['signature']) is str and len(envelope['signature'])==128,'BILLING_SIGNATURE')
            with self.authority.tx() as db:self.authority._key_active(db,envelope['key_id'])
            self.authority.kms.verify(envelope['key_id'],bytes.fromhex(envelope['signature']),DOMAIN+canonical(p))
        except (ValueError,TypeError,KeyError):raise Denied('BILLING_SIGNATURE') from None
        with self.authority.tx() as db:
            a=db.execute('SELECT a.*,r.state AS reservation_state,r.amount FROM attempts a JOIN reservations r ON r.id=a.id WHERE a.id=?',(p['attempt_id'],)).fetchone()
            require(a and a['project']==p['project_id'],'BILLING_PROJECT_ATTEMPT')
            require(a['result']==p['result_sha256'],'BILLING_RESULT_MISMATCH')
            require(a['state'] in {'SUBMITTED','UNKNOWN','DONE'} and a['reservation_state'] in {'UNKNOWN','SETTLED'},'BILLING_STATE')
            require(p['actual_fen']<=a['amount'],'INVALID_SETTLEMENT')
        return p
    def consume(self,envelope,*,fault=None):
        offline_only(self.authority,True)
        try:p=self.verify(envelope)
        except (ValueError,TypeError,KeyError) as exc:
            self.audit('QUARANTINE','invalid',type(exc).__name__+':'+str(exc));raise
        fingerprint=hashlib.sha256(canonical(p)).hexdigest()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM inbox WHERE event_id=?',(p['event_id'],)).fetchone()
            if old:
                if old['hash']!=fingerprint:
                    db.execute('INSERT INTO audit(kind,reference,detail) VALUES(?,?,?)',('CONFLICT',p['event_id'],fingerprint))
                    db.commit();raise Denied('EVENT_CONFLICT')
                if old['state']=='ACK':return 'ACK'
            else:db.execute('INSERT INTO inbox VALUES(?,?,?,?)',(p['event_id'],fingerprint,canonical(envelope).decode(),'PENDING'))
        # Original settle is transactional and receipt-idempotent. A crash here
        # leaves PENDING, so replay cannot create a second financial charge.
        try:self.authority.settle(p['attempt_id'],p['actual_fen'],p['receipt_id'])
        except Denied as exc:
            with self.db() as db:
                db.execute("UPDATE inbox SET state='QUARANTINE' WHERE event_id=?",(p['event_id'],))
                db.execute('INSERT INTO audit(kind,reference,detail) VALUES(?,?,?)',('QUARANTINE',p['event_id'],str(exc)))
            raise
        if fault:fault('after_settle')
        with self.db() as db:
            db.execute("UPDATE inbox SET state='ACK' WHERE event_id=?",(p['event_id'],))
            db.execute('INSERT INTO audit(kind,reference,detail) VALUES(?,?,?)',('ACK',p['event_id'],fingerprint))
        return 'ACK'
    def recover(self):
        with self.db() as db:pending=[parse(x[0].encode()) for x in db.execute("SELECT envelope FROM inbox WHERE state='PENDING'")]
        for envelope in pending:
            try:self.consume(envelope)
            except Denied:continue
        return len(pending)
    def observe(self,receipt):
        """M3 JSONL is a hint, never settlement evidence."""
        require(type(receipt) is dict,'OBSERVATION_SCHEMA')
        with self.authority.tx() as db:
            a=db.execute('SELECT * FROM attempts WHERE id=?',(receipt.get('m1_attempt_id'),)).fetchone()
            require(a,'UNKNOWN_ATTEMPT');identity=json.loads(a['identity'])
            require(receipt.get('page_id')==a['page'] and receipt.get('job_id')==identity['job_id'],'OBSERVATION_TASK')
            require(receipt.get('m1_result_sha256')==a['result'],'BILLING_RESULT_MISMATCH')
        state='PENDING_RELEASE' if receipt.get('budget_release_error') else 'WAITING_TRUSTED_EVIDENCE'
        self.audit('OBSERVED',a['id'],state);return state
    def retry_release(self,attempt,*,trusted_terminal=False):
        offline_only(self.authority,True);require(trusted_terminal is True,'TRUSTED_TERMINAL_REQUIRED')
        self.authority.cancel(attempt)  # Original API rejects UNKNOWN.
        self.audit('RELEASED',attempt,'original RESERVED-only cancel')
    def ingest_jsonl(self,path,source_id):
        """Signed evidence journal only; observations use observe(), not this API."""
        return self._ingest(path,'settlements:'+source_id,self.consume)
    def ingest_observations(self,path,source_id):
        """Durable receipt intake without financial authority."""
        return self._ingest(path,'observations:'+source_id,self.observe)
    def _ingest(self,path,source_id,handler):
        offline_only(self.authority,True);require(type(source_id) is str and source_id,'SOURCE_ID')
        raw=Path(path).read_bytes()
        require(len(raw)<=64*1024*1024,'JOURNAL_SIZE_LIMIT')
        with self.db() as db:row=db.execute('SELECT * FROM cursor WHERE source=?',(source_id,)).fetchone()
        offset=row['offset'] if row else 0
        require(len(raw)>=offset and (not row or hashlib.sha256(raw[:offset]).hexdigest()==row['hash']),'JOURNAL_CHANGED')
        processed=0
        while b'\n' in raw[offset:]:
            end=raw.index(b'\n',offset)+1;line=raw[offset:end-1]
            try:
                require(len(line)<=65536,'JOURNAL_LINE_LIMIT');handler(parse(line))
            except (ValueError,TypeError,KeyError) as exc:
                self.audit('QUARANTINE_LINE',hashlib.sha256(line).hexdigest(),str(exc))
            offset=end;processed+=1
            with self.db() as db:db.execute('INSERT INTO cursor VALUES(?,?,?) ON CONFLICT(source) DO UPDATE SET offset=excluded.offset,hash=excluded.hash WHERE excluded.offset>cursor.offset',(source_id,offset,hashlib.sha256(raw[:offset]).hexdigest()))
        require(len(raw)-offset<=65536,'JOURNAL_LINE_LIMIT')
        return processed
