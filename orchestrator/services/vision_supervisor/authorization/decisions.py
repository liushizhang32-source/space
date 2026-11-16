"""Gate decision provenance and strictly scoped rejection attribution (internal only)."""
from dataclasses import asdict
import hashlib
import json
import uuid
from ..gate import Gate
from ..supervisor import Identity, VisionError, unique_json
from .exceptions import AuthorizationError
from .models import Credential


def _identity(value):
    if type(value) is not Identity:
        return None
    doc = asdict(value)
    if any(type(doc[k]) is not str or not doc[k] for k in
           ('job_id','page_id','generation_id','attempt_id','fencing_token')):
        return None
    if any(type(doc[k]) is not int or doc[k] < 1 for k in ('input_revision','epoch')):
        return None
    return doc


def _binding(store, record, c1, c2, hashes, audience, scope):
    """Capture ledger context without holding a DB lock during Gate.

    OCR/VLM attempts differ in frozen V1.0: compare five lineage fields, then
    all seven OCR fields against the actual PASS evidence Identity.
    """
    result = dict(kind='INTERNAL_ERROR',status='BLOCKED',identity=None,authorization_id=None)
    try:
        record_id,c1_id,c2_id = (_identity(x) for x in (record.identity,c1.identity,c2.identity))
        refs = unique_json(c2.documents['sidecar'])
        sidecar_id = {k:refs[k] for k in asdict(c2.identity)}
        if (record_id is None or c1_id is None or c2_id is None
                or any(type(sidecar_id[k]) is not type(v) for k,v in c2_id.items())):
            return result
        with store.transaction() as db:
            # Still the offline candidate ledger, never production Jobs authority.
            current=db.execute('SELECT * FROM current_asset WHERE page_id=?',(record.page_id,)).fetchone()
            if current is None:
                return result
            current_id=Identity(**json.loads(current['identity']))
            if _identity(current_id) is None:
                return result
            result['identity']=current_id
            try:
                store.check_current(db,c2.identity,hashes[1])
            except AuthorizationError as exc:
                result.update(kind='SUPERSEDED' if exc.status=='BLOCKED' else 'STALE_EVIDENCE',status=exc.status)
                return result
            lineage=('job_id','page_id','generation_id','input_revision','epoch')
            if (record_id!=c2_id or sidecar_id!=c2_id
                    or any(c1_id[k]!=c2_id[k] for k in lineage)
                    or refs.get('c2',{}).get('sha256')!=hashes[1]):
                result.update(kind='STALE_EVIDENCE',status='IDENTITY_MISMATCH')
                return result
            target=db.execute('''SELECT * FROM authorization WHERE identity=? AND c2_sha256=?
                AND audience=? AND scope=? AND status='ACTIVE' ORDER BY rowid DESC LIMIT 1''',
                (current['identity'],hashes[1],audience,scope)).fetchone()
            # First issuance has no authorization to revoke. A Gate failure then
            # is unowned/UNKNOWN, never a DENY attributed to current Identity.
            result.update(status=None)
            if target is None:
                return result
            result['status']='BLOCKED'
            payload=Credential.model_validate_json(target['credential']).payload
            store.check_decision(db,payload)
            proof=db.execute('''SELECT d.c1_sha256,d.sidecar_sha256,e.c1_identity
                FROM gate_decision d JOIN gate_evidence e USING(gate_decision_id)
                WHERE d.gate_decision_id=?''',(payload.gate_decision_id,)).fetchone()
            if proof is None:
                # Older V0.1.1 PASS rows have no OCR Identity metadata. A fresh
                # real Gate PASS may retain normal/idempotent issuance, but a
                # failure stays UNKNOWN and must never revoke that old target.
                # Do not invent or backfill the old OCR Identity from Handoff.
                result.update(status=None)
                return result
            if (json.loads(proof['c1_identity'])!=c1_id or proof['c1_sha256']!=hashes[0]
                    or proof['sidecar_sha256']!=hashes[2]):
                result.update(kind='STALE_EVIDENCE',status='IDENTITY_MISMATCH')
                return result
            result.update(kind='CURRENT_INPUT',status=None,authorization_id=target['authorization_id'])
            return result
    except (ValueError,KeyError,TypeError,AttributeError):
        return result


def _event(db,kind,context,record,c1,c2,hashes,operation_id,now,reason,*,passed_decision_id=None):
    """Idempotent internal event, distinct from the frozen public protocol."""
    evidence=dict(record=_identity(getattr(record,'identity',None)),
                  c1=_identity(getattr(c1,'identity',None)),c2=_identity(getattr(c2,'identity',None)))
    event_id=hashlib.sha256(json.dumps(dict(kind=kind,operation=operation_id,evidence=evidence,
        hashes=hashes,target=context['authorization_id']),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if db.execute('SELECT 1 FROM gate_event WHERE event_id=?',(event_id,)).fetchone():
        return
    decision_id=passed_decision_id or uuid.uuid4().hex
    if passed_decision_id is None:
        # Non-current DENY rows are explicitly unowned (JSON null Identity).
        # Actual supplied Identities and classification are preserved in event.
        subject=asdict(context['identity']) if kind=='CURRENT_DENY' else None
        db.execute('INSERT INTO gate_decision VALUES (?,?,?,?,?,?,?,?,?)',
            (decision_id,json.dumps(subject),*hashes,'DENY',now,'gate.accept/0.1.1',kind+': '+reason))
    db.execute('INSERT INTO gate_event VALUES (?,?,?,?,?,?,?)',
        (event_id,kind,decision_id,context['authorization_id'],json.dumps(evidence),now,reason))


def _evidence_size(c1,c2,size):
    """Caller size is a consistency hint, never authoritative DENY evidence.

    Use the dimensions in the raw snapshots (C2 hash is independently bound by
    _binding). No original-image registry is connected to this offline Issuer;
    this does not claim production original-image dimension verification.
    """
    try:
        docs=(unique_json(c1.documents['c1']),unique_json(c2.documents['c2']))
        dimensions=tuple((doc['image_width'],doc['image_height']) for doc in docs)
        if (type(size) is not tuple or len(size)!=2
                or any(type(x) is not int or x<=0 for x in size)
                or any(type(x) is not int or x<=0 for pair in dimensions for x in pair)
                or dimensions[0]!=dimensions[1] or size!=dimensions[1]):
            raise ValueError('Caller/evidence dimensions differ')
        return dimensions[1]
    except (ValueError,KeyError,TypeError,AttributeError) as exc:
        raise VisionError(1002,'Unverified size or inconsistent evidence dimensions') from exc


def evaluate(gate,store,record,fences,c1,c2,size,*,now,audience,scope,operation_id):
    if type(gate) is not Gate:
        raise AuthorizationError('BLOCKED')
    def digest(snapshot,name):
        try:
            raw=snapshot.documents.get(name)
            return hashlib.sha256(raw).hexdigest() if type(raw) is bytes else ''
        except (TypeError,AttributeError):
            return ''
    hashes=(digest(c1,'c1'),digest(c2,'c2'),digest(c2,'sidecar'))
    context=_binding(store,record,c1,c2,hashes,audience,scope)
    try:
        # Check parameters before safety policy, including the combination of a
        # bad size and 3004 evidence. No caller parameter may trigger revocation.
        evidence_size=_evidence_size(c1,c2,size)
        handoff=gate.accept(record,fences,c1,c2,evidence_size)
    except Exception as exc:
        if context['kind'] in {'STALE_EVIDENCE','SUPERSEDED'}:
            kind=context['kind']
        elif isinstance(exc,VisionError) and exc.code==2004:
            kind='SUPERSEDED'
        # 1002 includes caller size, schemas, provenance and other generic errors.
        # It is never sufficient evidence for CURRENT_DENY, even on current bytes.
        elif (context['kind']=='CURRENT_INPUT' and isinstance(exc,VisionError) and exc.code==3004):
            kind='CURRENT_DENY'
        else:
            kind='INTERNAL_ERROR'
        with store.transaction() as db:
            if kind=='CURRENT_DENY' and not store.deny_current(context['authorization_id'],
                    context['identity'],hashes[1],now,_db=db):
                kind='SUPERSEDED'
            _event(db,kind,context,record,c1,c2,hashes,operation_id,now,
                   str(exc.code) if isinstance(exc,VisionError) else 'Gate internal error')
        if isinstance(exc,VisionError):
            raise
        raise AuthorizationError('BLOCKED') from exc
    decision_id=uuid.uuid4().hex
    with store.transaction() as db:
        db.execute('INSERT INTO gate_decision VALUES (?,?,?,?,?,?,?,?,?)',
            (decision_id,json.dumps(asdict(handoff.identity)),*hashes,
             'PASS',now,'gate.accept/0.1.1','Gate.accept completed'))
        db.execute('INSERT INTO gate_evidence VALUES (?,?)',(decision_id,json.dumps(asdict(c1.identity))))
        if context['status'] is not None:
            _event(db,context['kind'],context,record,c1,c2,hashes,operation_id,now,
                   context['status'],passed_decision_id=decision_id)
    if context['status'] is not None:
        raise AuthorizationError(context['status'])
    return handoff,decision_id
