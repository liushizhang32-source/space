"""Trusted shared lifecycle operations used only by the explicit offline assembly."""
import json,uuid
from dataclasses import asdict
from ..poc_security.crypto import canonical

LINEAGE=('job_id','page_id','generation_id','input_revision','epoch')

class VisionLifecycle:
    @staticmethod
    def _lineage(value):
        values=value if type(value) is dict else asdict(value)
        return {k:values[k] for k in LINEAGE}

    def _vision_pending(self,db,lineage):
        return any(all(json.loads(r['logical'])[k]==lineage[k] for k in LINEAGE)
                   for r in db.execute("SELECT logical FROM stage_attempts WHERE state IN ('RESERVED','DISPATCHED','UNKNOWN')"))

    def _vision_revoke(self,db,lineage):
        for r in db.execute('SELECT a.id,a.token,a.state,u.identity FROM attempts a JOIN generation_upstream u ON u.attempt_id=a.id').fetchall():
            if self._lineage(json.loads(r['identity']))!=lineage:continue
            db.execute("UPDATE tokens SET status='REVOKED' WHERE id=? AND status='ACTIVE'",(r['token'],))
            if r['state']=='RESERVED':
                db.execute("UPDATE attempts SET state='CANCELLED' WHERE id=?",(r['id'],))
                db.execute("UPDATE reservations SET state='RELEASED' WHERE id=?",(r['id'],))
            self.event(db,'upstream_revoked',attempt_id=r['id'])

    def vision_begin(self,job,page,revision,*,force=False):
        self._require(type(job) is str and job and type(page) is str and page
                      and type(revision) is int and revision>=1 and type(force) is bool,'VISION_IDENTITY')
        blocked=False;created=False
        with self.tx() as db:
            row=db.execute('SELECT * FROM vision_current WHERE page_id=?',(page,)).fetchone()
            old=json.loads(row['lineage']) if row else None
            if row and row['status'] in ('QUEUED','RUNNING') and not force:
                self._require(old['job_id']==job and old['input_revision']==revision,'VISION_BUSY')
                result=dict(row)
            else:
                if row:
                    blocked=self._vision_pending(db,old)
                    if force or blocked:
                        db.execute("UPDATE vision_current SET status='CANCELLED' WHERE page_id=?",(page,))
                        self._vision_revoke(db,old)
                        self.event(db,'vision_cancelled',page_id=page,generation_id=old['generation_id'])
                if not blocked:
                    epoch=row['serial']+1 if row else 1
                    lineage=dict(job_id=job,page_id=page,generation_id=uuid.uuid4().hex,input_revision=revision,epoch=epoch)
                    db.execute('INSERT OR REPLACE INTO vision_current VALUES(?,?,NULL,?,?,NULL)',
                               (page,canonical(lineage).decode(),'QUEUED',epoch))
                    if old:self._vision_revoke(db,old)
                    self.event(db,'vision_begun',page_id=page,generation_id=lineage['generation_id'],epoch=epoch)
                    result=dict(db.execute('SELECT * FROM vision_current WHERE page_id=?',(page,)).fetchone());created=True
        # Cancellation must commit even if a force replacement is denied for drain.
        self._require(not blocked,'VISION_DRAIN_REQUIRED')
        return result,created

    def vision_snapshot(self,page):
        with self.tx() as db:
            row=db.execute('SELECT * FROM vision_current WHERE page_id=?',(page,)).fetchone()
            return dict(row) if row else None

    def _vision_check(self,db,identity,*,allow_done=False,require_attempt=True):
        values=identity if type(identity) is dict else asdict(identity)
        row=db.execute('SELECT * FROM vision_current WHERE page_id=?',(values['page_id'],)).fetchone()
        self._require(row and json.loads(row['lineage'])==self._lineage(values),'VISION_STALE')
        self._require(row['status'] in (('QUEUED','RUNNING','DONE') if allow_done else ('QUEUED','RUNNING')),'VISION_REVOKED')
        if require_attempt:
            self._require(row['identity'] and canonical(json.loads(row['identity']))==canonical(values),'VISION_FENCING')
        return row

    def vision_cancel(self,lineage):
        values=self._lineage(lineage)
        with self.tx() as db:
            row=db.execute('SELECT * FROM vision_current WHERE page_id=?',(values['page_id'],)).fetchone()
            if not row or json.loads(row['lineage'])!=values:return False
            if row['status']=='CANCELLED':return True
            db.execute("UPDATE vision_current SET status='CANCELLED' WHERE page_id=?",(values['page_id'],))
            self._vision_revoke(db,values)
            self.event(db,'vision_cancelled',page_id=values['page_id'],generation_id=values['generation_id'])
            return True

    def vision_finish(self,identity,status):
        self._require(status in ('FAILED','BLOCKED','CANCELLED'),'VISION_STATUS')
        with self.tx() as db:
            row=db.execute('SELECT * FROM vision_current WHERE page_id=?',(identity.page_id,)).fetchone()
            if not row or not row['identity'] or canonical(json.loads(row['identity']))!=canonical(asdict(identity)):return False
            if row['status'] not in ('QUEUED','RUNNING'):return False
            db.execute('UPDATE vision_current SET status=? WHERE page_id=?',(status,identity.page_id))
            self._vision_revoke(db,self._lineage(identity))
            self.event(db,'vision_terminal',page_id=identity.page_id,status=status)
            return True
