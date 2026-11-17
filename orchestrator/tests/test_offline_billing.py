import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from orchestrator.tests.test_m1_integration_reference import rig,begin
from orchestrator.services.integration_reference import Denied
from orchestrator.services.offline_protocols.billing import OfflineSettlementAdapter,ReconciliationConsumer,validate_event
from orchestrator.services.poc_security.crypto import canonical

@pytest.fixture
def billing(rig,tmp_path):
    a,k,n,s=rig;b=begin(rig);result=a.submit(s,b['token'],b['identity'],b'committed-story')
    adapter=OfflineSettlementAdapter(a,offline_test=True)
    c=ReconciliationConsumer(a,tmp_path/'inbox.sqlite',offline_test=True)
    e=adapter.evidence(b['identity']['attempt_id'],200,event_id='e1',receipt_id='r1')
    return rig,b,adapter,c,e

def test_settlement_duplicate_and_budget(billing):
    rig,b,ad,c,e=billing;a=rig[0]
    assert c.consume(e)=='ACK' and c.consume(e)=='ACK'
    assert a.totals()==dict(spent=200,held=0,available=14800)
    with a.tx() as db:assert sum(json.loads(x[0])['kind']=='settled' for x in db.execute('SELECT payload FROM events'))==1

def test_unknown_observation_does_not_charge_or_release(billing):
    rig,b,ad,c,e=billing;a=rig[0]
    assert c.observe(dict(m1_attempt_id=b['identity']['attempt_id'],page_id='page',job_id='req',m1_result_sha256=e['payload']['result_sha256'],submission_state='UNKNOWN'))=='WAITING_TRUSTED_EVIDENCE'
    with pytest.raises(Denied,match='ATTEMPT_UNRESOLVED'):begin(rig,request='different-request')
    with pytest.raises(Denied,match='UNKNOWN_RETAINS_BUDGET'):c.retry_release(b['identity']['attempt_id'],trusted_terminal=True)
    assert a.totals()['held']==1000 and a.totals()['spent']==0

@pytest.mark.parametrize('field,value',[('project_id','other'),('attempt_id','missing'),('result_sha256','0'*64),('actual_fen',1001)])
def test_signed_mismatch_never_changes_budget(billing,field,value):
    rig,b,ad,c,e=billing;p=dict(e['payload']);p[field]=value
    with pytest.raises(Denied):c.consume(ad.sign(p))
    assert rig[0].totals()['held']==1000 and rig[0].totals()['spent']==0

@pytest.mark.parametrize('value',[True,-1,15001,1.5,'200'])
def test_amount_strict(billing,value):
    p=dict(billing[-1]['payload']);p['actual_fen']=value
    with pytest.raises(Denied):validate_event(p)

def test_signature_and_event_id_conflict(billing):
    rig,b,ad,c,e=billing;bad={**e,'signature':'00'*64}
    with pytest.raises(Denied):c.consume(bad)
    c.consume(e);p=dict(e['payload']);p['receipt_id']='different'
    with pytest.raises(Denied,match='EVENT_CONFLICT'):c.consume(ad.sign(p))
    assert rig[0].totals()['spent']==200

def test_crash_after_financial_commit_recovers_once(billing):
    rig,b,ad,c,e=billing
    def crash(where):raise RuntimeError('simulated termination before ACK')
    with pytest.raises(RuntimeError):c.consume(e,fault=crash)
    reopened=ReconciliationConsumer(rig[0],c.path,offline_test=True)
    assert reopened.recover()==1 and reopened.recover()==0
    assert rig[0].totals()['spent']==200 and rig[0].totals()['held']==0

def test_concurrent_delivery_single_charge(billing):
    rig,b,ad,c,e=billing
    with ThreadPoolExecutor(max_workers=4) as pool:assert list(pool.map(lambda _:c.consume(e),range(4)))==['ACK']*4
    assert rig[0].totals()['spent']==200

def test_jsonl_partial_duplicate_and_changed_prefix(billing,tmp_path):
    rig,b,ad,c,e=billing;p=tmp_path/'events.jsonl';raw=canonical(e)
    p.write_bytes(raw[:20]);assert c.ingest_jsonl(p,'journal')==0
    p.write_bytes(raw+b'\n');assert c.ingest_jsonl(p,'journal')==1
    p.write_bytes(raw+b'\n'+raw+b'\n');assert c.ingest_jsonl(p,'journal')==1
    assert rig[0].totals()['spent']==200
    p.write_bytes(b'corrupted\n')
    with pytest.raises(Denied,match='JOURNAL_CHANGED'):c.ingest_jsonl(p,'journal')

def test_bad_jsonl_is_audited_not_charged(billing,tmp_path):
    rig,b,ad,c,e=billing;p=tmp_path/'bad.jsonl';p.write_bytes(b'{"payload":1,"payload":2}\n')
    assert c.ingest_jsonl(p,'bad')==1
    with c.db() as db:assert db.execute("SELECT count(*) FROM audit WHERE kind='QUARANTINE_LINE'").fetchone()[0]==1
    assert rig[0].totals()['held']==1000

def test_reserved_release_requires_explicit_trusted_terminal(rig,tmp_path):
    b=begin(rig);c=ReconciliationConsumer(rig[0],tmp_path/'inbox.sqlite',offline_test=True)
    with pytest.raises(Denied):c.retry_release(b['identity']['attempt_id'])
    c.retry_release(b['identity']['attempt_id'],trusted_terminal=True)
    c.retry_release(b['identity']['attempt_id'],trusted_terminal=True)
    assert rig[0].totals()['held']==0 and rig[0].totals()['spent']==0

def test_production_activation_denied(rig,tmp_path,monkeypatch):
    with pytest.raises(Denied):OfflineSettlementAdapter(rig[0])
    monkeypatch.setenv('M1_DEPLOYMENT_ENV','production')
    with pytest.raises(Denied):ReconciliationConsumer(rig[0],tmp_path/'x',offline_test=True)
