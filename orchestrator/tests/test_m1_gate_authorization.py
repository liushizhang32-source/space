"""All keys are ephemeral; all workers and consumers are offline Fakes."""
from dataclasses import asdict, replace
import hashlib
import json
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
import pytest
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from orchestrator.services.vision_supervisor.gate import Gate, Handoff
from orchestrator.services.vision_supervisor.supervisor import Fences, Snapshot, VisionError
from orchestrator.services.vision_supervisor.authorization.issuer import Issuer
from orchestrator.services.vision_supervisor.authorization.verifier import Verifier, downstream_allows
from orchestrator.services.vision_supervisor.authorization.store import Store
from orchestrator.services.vision_supervisor.authorization.revocation import revoke
from orchestrator.services.vision_supervisor.authorization.exceptions import AuthorizationError
from orchestrator.services.vision_supervisor.authorization.api import offline_router, router, PATH
from orchestrator.services.vision_supervisor.authorization.assets import AuthorizedAssetReader


@pytest.fixture
def rig(tmp_path):
    fences = Fences()
    record, _ = fences.begin('job-offline', 'book01_p03')
    identity = fences.attempt(record)
    base = dict(schema_version='1.0', book_id='book01', page_id=identity.page_id, page_no=3,
                image_width=96, image_height=128, elapsed_ms=1)
    c1raw = json.dumps(dict(base, status='empty', text_blocks=[], page_confidence=0.0)).encode()
    c2raw = json.dumps(dict(base, status='empty', description='offline fake', objects=[],
                           safety={'pass':True, 'flags':[]})).encode()
    digest = hashlib.sha256(c2raw).hexdigest()
    refs = dict(schema_version='vision_refs/0.1', **asdict(identity),
                c2=dict(asset_id='fake-c2', schema_version='1.0',
                        relative_path='json/book01_p03_vlm.json', sha256=digest),
                source=dict(component_mode='fixture', model_ref='fake', prompt_sha256='a'*64,
                            evidence_ref='offline'), observations=[])
    c1 = Snapshot(replace(identity, attempt_id='ocr', fencing_token='ocr-token'), 'fake', {'c1':c1raw})
    c2 = Snapshot(identity, 'fake', {'c2':c2raw, 'sidecar':json.dumps(refs).encode()})
    store = Store(tmp_path/'auth.sqlite')
    store.set_current_for_offline_adapter(identity, digest)
    key = Ed25519PrivateKey.generate()
    now = [1000]
    gate = Gate({'fake'})
    issuer = Issuer(gate, store, key_id='test-1', test_private_key=key, offline_test=True, clock=lambda:now[0])
    verifier = Verifier(store, {'test-1':key.public_key()}, clock=lambda:now[0])
    return SimpleNamespace(**locals())


def issue(r, **kw):
    return r.issuer.issue(r.record,r.fences,r.c1,r.c2,(96,128),
        **dict(dict(audience='M2',scope='task.consume',request_id='request-1'),**kw))


def expected(r, **kw):
    return dict(dict(expected_identity=r.identity,expected_c2_sha256=r.digest,
                     expected_audience='M2',expected_scope='task.consume'),**kw)


def verify(r, c, **kw):
    return r.verifier.verify(c.model_dump_json().encode(), **expected(r,**kw))


def signed(r, c, **updates):
    p = dict(c.payload.model_dump(mode='json'),**updates)
    return json.dumps(dict(payload=p,signature=r.key.sign(rfc8785.dumps(p)).hex())).encode()


def test_T01_gate_success(rig):
    c = issue(rig)
    assert verify(rig,c)=='VALID'
    assert c.payload.identity==rig.identity and c.payload.c2_sha256==rig.digest
    with rig.store.transaction() as db:
        assert db.execute('SELECT count(*) FROM audit').fetchone()[0]==1


def test_T02_gate_denial_no_credential(rig):
    raw=json.loads(rig.c2.documents['c2']); raw['safety']['pass']=False
    rig.c2=replace(rig.c2, documents=dict(rig.c2.documents,c2=json.dumps(raw).encode()))
    with pytest.raises(VisionError): issue(rig)
    with rig.store.transaction() as db:
        assert db.execute('SELECT count(*) FROM authorization').fetchone()[0]==0


def test_T03_forgery(rig):
    c=issue(rig)
    assert verify(rig,c.model_copy(update={'signature':'00'*64}))=='INVALID_SIGNATURE'


@pytest.mark.parametrize('field,value', [
    ('identity',{'job_id':'foreign'}),('c2_sha256','b'*64),('audience','M4'),('scope','page.assets.read')],
    ids=['T04','T05','T06','T07'])
def test_payload_tamper(rig,field,value):
    c=issue(rig); d=json.loads(c.model_dump_json())
    if field=='identity': value=dict(d['payload']['identity'],**value)
    d['payload'][field]=value
    assert rig.verifier.verify(json.dumps(d).encode(),**expected(rig))!='VALID'


@pytest.mark.parametrize('kwargs,status', [
    ({'expected_identity':'foreign'},'IDENTITY_MISMATCH'),
    ({'expected_c2_sha256':'c'*64},'C2_HASH_MISMATCH'),
    ({'expected_audience':'M4'},'AUDIENCE_MISMATCH'),
    ({'expected_scope':'page.assets.read'},'SCOPE_MISMATCH')])
def test_expected_binding(rig,kwargs,status):
    c=issue(rig)
    if 'expected_identity' in kwargs: kwargs['expected_identity']=replace(rig.identity,page_id='book01_p04')
    assert verify(rig,c,**kwargs)==status


def test_T08_expiry(rig):
    c=issue(rig); rig.now[0]=c.payload.expires_at
    assert verify(rig,c)=='EXPIRED'
    rig.now[0]=1000
    assert verify(rig,c)=='EXPIRED'  # expiry state cannot revive on clock rollback


@pytest.mark.parametrize('iat,nbf', [(1000,1001),(1001,1001)])
def test_T09_future(rig,iat,nbf):
    c=issue(rig)
    assert rig.verifier.verify(signed(rig,c,issued_at=iat,not_before=nbf),**expected(rig))=='NOT_YET_VALID'


def test_T10_revocation(rig):
    c=issue(rig); revoke(rig.store,c.payload.authorization_id,at=1001,reason='offline test')
    assert verify(rig,c)=='REVOKED'
    with rig.store.transaction() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE action='REVOKED'").fetchone()[0]==1


def test_T11_unknown_key(rig):
    c=issue(rig); rig.verifier.public_keys.clear()
    assert verify(rig,c)=='UNKNOWN_KEY'


@pytest.mark.parametrize('field,value',[('alg','none'),('alg','HS256'),('schema_version','future'),('issuer','M2')])
def test_T12_downgrade_and_version(rig,field,value):
    c=issue(rig)
    assert rig.verifier.verify(signed(rig,c,**{field:value}),**expected(rig))=='MALFORMED'


def test_T13_idempotency(rig):
    c=issue(rig); assert issue(rig)==c
    with pytest.raises(AuthorizationError,match='IDEMPOTENCY_CONFLICT'):
        issue(rig,audience='M4',scope='page.assets.read')
    with rig.store.transaction() as db:
        assert db.execute('SELECT count(*) FROM authorization').fetchone()[0]==1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT INTO authorization SELECT * FROM authorization')


@pytest.mark.parametrize('change,status', [
    ({'generation_id':'new'},'STALE_GENERATION'),({'epoch':2},'STALE_GENERATION'),
    ({'fencing_token':'new'},'FENCING_MISMATCH'),({'attempt_id':'new'},'FENCING_MISMATCH'),
    ({'input_revision':2},'STALE_GENERATION'),({'job_id':'new'},'STALE_GENERATION')],
    ids=['T14','T15','T16','attempt','revision','job'])
def test_current_transition(rig,change,status):
    c=issue(rig)
    rig.store.set_current_for_offline_adapter(replace(rig.identity,**change),rig.digest)
    assert verify(rig,c)==status
    with pytest.raises(AuthorizationError,match=status): issue(rig,request_id='new-request')


def test_T17_restart_revocation(rig):
    c=issue(rig); revoke(rig.store,c.payload.authorization_id,at=1000,reason='restart')
    # A fresh OS process reads the committed ledger; no in-memory revocation state.
    code="import sqlite3,sys; d=sqlite3.connect(sys.argv[1]); print(d.execute('SELECT status FROM authorization').fetchone()[0])"
    result=subprocess.run([sys.executable,'-I','-c',code,rig.store.path],capture_output=True,text=True,check=True)
    assert result.stdout.strip()=='REVOKED'
    rig.verifier.store=Store(rig.store.path)
    assert verify(rig,c)=='REVOKED'


def test_T18_storage_failure(rig):
    c=issue(rig); rig.store.path=str(rig.tmp_path/'missing'/'auth.sqlite')
    assert verify(rig,c)=='BLOCKED'
    with pytest.raises(AuthorizationError,match='BLOCKED'): issue(rig,request_id='new')


def test_T19_authentication(rig):
    c=issue(rig); app=FastAPI()
    app.include_router(offline_router(rig.verifier,lambda req:'M2' if req.headers.get('X-Fake-Service')=='M2' else None))
    body=dict(credential=json.loads(c.model_dump_json()),**{k:asdict(v) if k=='expected_identity' else v for k,v in expected(rig).items()})
    with TestClient(app) as client:
        assert client.post(PATH,json=body).status_code==401
        assert client.post(PATH,json=body,headers={'X-Fake-Service':'M2'}).json()['status']=='VALID'
        body['expected_audience']='M4'
        assert client.post(PATH,json=body,headers={'X-Fake-Service':'M2'}).status_code==403


def test_T20_downstream_unavailable():
    def unavailable(): raise ConnectionError('offline')
    assert not downstream_allows(unavailable)
    for s in ['BLOCKED','UNKNOWN','INVALID_SIGNATURE',None]: assert not downstream_allows(lambda:s)


def test_T21_historical_c2(rig):
    c=issue(rig); rig.store.set_current_for_offline_adapter(rig.identity,'d'*64)
    assert verify(rig,c)=='C2_HASH_MISMATCH'
    with pytest.raises(AuthorizationError,match='C2_HASH_MISMATCH'): issue(rig,request_id='new')


def test_T22_handoff_is_not_credential(rig):
    handoff=rig.gate.accept(rig.record,rig.fences,rig.c1,rig.c2,(96,128))
    assert isinstance(handoff,Handoff)
    assert rig.verifier.verify(repr(handoff).encode(),**expected(rig))=='MALFORMED'
    with pytest.raises(TypeError): rig.issuer.issue(handoff)


def test_T23_history_cannot_restore(rig):
    c=issue(rig)
    # Keep current bytes/Hash intact: current trust-policy DENY must revoke.
    # A changed C2 against the old hash is STALE, covered by P1 regressions.
    rig.gate.trusted=frozenset()
    with pytest.raises(VisionError): issue(rig,request_id='rejected')
    class History:
        def read(self,page): pytest.fail('Historical reader reached after denial')
    reader=AuthorizedAssetReader(rig.verifier,History())
    with pytest.raises(AuthorizationError,match='REVOKED'):
        reader.read(rig.identity.page_id,c.model_dump_json().encode(),**expected(rig))
    rig.verifier.store=Store(rig.store.path)
    assert verify(rig,c)=='REVOKED'


def test_concurrent_idempotent_issuance(rig):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        credentials=list(pool.map(lambda _:issue(rig), range(8)))
    assert all(c==credentials[0] for c in credentials)
    with rig.store.transaction() as db:
        assert db.execute('SELECT count(*) FROM authorization').fetchone()[0]==1


def test_unknown_current_fails_closed(rig):
    with rig.store.transaction() as db: db.execute('DELETE FROM current_asset')
    with pytest.raises(AuthorizationError,match='BLOCKED'): issue(rig)


def test_cancelled_generation_no_issuance(rig):
    rig.fences.cancel(rig.record)
    with pytest.raises(VisionError): issue(rig)


def test_protected_asset_different_page(rig):
    c=issue(rig)
    reader=AuthorizedAssetReader(rig.verifier,None)
    with pytest.raises(AuthorizationError,match='IDENTITY_MISMATCH'):
        reader.read('book01_p04',c.model_dump_json().encode(),**expected(rig))


def test_T24_repeated_m4_reads(rig):
    c=issue(rig,audience='M4',scope='page.assets.read')
    kw=expected(rig,expected_audience='M4',expected_scope='page.assets.read')
    class Assets:
        def read(self,page):
            return dict(identity=asdict(rig.identity)), {f'json/{page}_vlm.json':rig.c2raw}
    reader=AuthorizedAssetReader(rig.verifier,Assets())
    for _ in range(3):
        assert reader.read(rig.identity.page_id,c.model_dump_json().encode(),**kw)


@pytest.mark.parametrize('aud,scope,target',[('M2','task.consume','M4'),('M4','page.assets.read','M2')],ids=['T25','T26'])
def test_audience_isolation(rig,aud,scope,target):
    c=issue(rig,audience=aud,scope=scope)
    assert verify(rig,c,expected_audience=target)=='AUDIENCE_MISMATCH'


@pytest.mark.parametrize('field,status',[('jti','UNKNOWN_JTI'),('nonce','UNKNOWN_NONCE')])
def test_unknown_replay_fields(rig,field,status):
    c=issue(rig)
    assert rig.verifier.verify(signed(rig,c,**{field:'unknown'}),**expected(rig))==status


def test_production_fail_closed(rig):
    rig.issuer.offline_test=False
    with pytest.raises(AuthorizationError,match='BLOCKED'): issue(rig)
    app=FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        r=client.post(PATH,json={})
        assert r.status_code==503 and r.json()['status']=='BLOCKED'


def test_key_rotation(rig):
    c=issue(rig); key2=Ed25519PrivateKey.generate()
    rig.issuer._key=key2; rig.issuer.key_id='test-2'
    c2=issue(rig,request_id='request-2')
    rig.verifier.public_keys['test-2']=key2.public_key()
    assert verify(rig,c)==verify(rig,c2)=='VALID'
    del rig.verifier.public_keys['test-1']
    assert verify(rig,c)=='UNKNOWN_KEY' and verify(rig,c2)=='VALID'


def test_duplicate_json_and_boolean_identity(rig):
    c=issue(rig)
    raw=c.model_dump_json().replace('"epoch":1','"epoch":true').encode()
    assert rig.verifier.verify(raw,**expected(rig))=='MALFORMED'
    assert rig.verifier.verify(b'{"payload":{},"payload":{}}',**expected(rig))=='MALFORMED'
