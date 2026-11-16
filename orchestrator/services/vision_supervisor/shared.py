"""Durable current adapter for the explicit offline, frozen-V1 assembly."""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib,json,threading,uuid
from .supervisor import Fences,Generation,Identity,Cancelled
from ..integration_reference.authority import Denied
from ..poc_security.crypto import canonical

class SharedFences(Fences):
    def __init__(self,authority):
        super().__init__();self.authority=authority

    @staticmethod
    def _lineage(record):
        return {k:getattr(record,k) for k in ('job_id','page_id','generation_id','input_revision','epoch')}

    def begin(self,job_id,page_id,*,input_revision=1,force=False):
        with self.lock:
            row,created=self.authority.vision_begin(job_id,page_id,input_revision,force=force)
            lineage=json.loads(row['lineage']);record=self.pages.get(page_id)
            if record is None or self._lineage(record)!=lineage:
                record=Generation(**lineage);self.pages[page_id]=record
            record.status=row['status'].lower()
            record.identity=Identity(**json.loads(row['identity'])) if row['identity'] else None
            self.serial.setdefault(page_id,threading.Lock())
            return record,created

    def restore(self,page_id):
        """Rehydrate the current view without allocating a new generation."""
        with self.lock:
            row=self.authority.vision_snapshot(page_id)
            if row is None:return None
            record=Generation(**json.loads(row['lineage']))
            record.status=row['status'].lower()
            record.identity=Identity(**json.loads(row['identity'])) if row['identity'] else None
            if row['status']=='CANCELLED':record.cancel.set()
            self.pages[page_id]=record;self.serial.setdefault(page_id,threading.Lock())
            return record

    def current(self,record):
        row=self.authority.vision_snapshot(record.page_id)
        return bool(row and json.loads(row['lineage'])==self._lineage(record)
                    and row['status'] in ('QUEUED','RUNNING','DONE'))

    def check(self,record,identity=None,*,_db=None):
        if record.cancel.is_set():raise Cancelled()
        values=asdict(identity) if identity is not None else self._lineage(record)
        try:
            if _db is not None:self.authority._vision_check(_db,values,require_attempt=identity is not None)
            else:
                with self.authority.tx() as db:self.authority._vision_check(db,values,require_attempt=identity is not None)
        except Denied as exc:raise Cancelled() from exc

    def attempt(self,record):
        with self.lock:
            self.check(record)
            # Only reserve_stage may make this Identity current. A duplicate
            # admission loser must not revoke an already running worker.
            record.identity=Identity(**self._lineage(record),attempt_id=uuid.uuid4().hex,fencing_token=uuid.uuid4().hex)
            record.status='running';record.c2_sha256=None
            return record.identity

    def cancel(self,record):
        with self.lock:
            if self.authority.vision_cancel(self._lineage(record)):
                record.cancel.set();record.status='cancelled'

    def finish(self,record,status):
        if record.identity is not None:
            return self.authority.vision_finish(record.identity,status.upper())
        return False

    @contextmanager
    def publication_guard(self,record,identity,manifest):
        with self.authority.tx() as db:
            self.check(record,identity,_db=db)
            yield
            db.execute("UPDATE vision_current SET status='DONE',manifest_sha256=? WHERE page_id=?",
                       (hashlib.sha256(canonical(manifest)).hexdigest(),record.page_id))
            self.authority.event(db,'vision_published',page_id=record.page_id,generation_id=record.generation_id)

    def accept_manifest(self,record,manifest):
        with self.authority.tx() as db:
            row=db.execute('SELECT * FROM vision_current WHERE page_id=?',(record.page_id,)).fetchone()
            return bool(row and row['status']=='DONE' and row['identity']
                and canonical(json.loads(row['identity']))==canonical(manifest['identity'])
                and row['manifest_sha256']==hashlib.sha256(canonical(manifest)).hexdigest())
