"""Provider restart must not restore trust in a previously revoked key."""
import pytest
from orchestrator.services.integration_reference import Authority,OfflineKMS,Denied

def test_revoked_key_does_not_regain_trust_after_provider_restart(tmp_path):
    seed=b'explicit-offline-key-restart-test-seed'
    first=OfflineKMS(seed=seed)
    a=Authority.provision(tmp_path/'authority.sqlite',tmp_path/'anchor',first,lambda:1000,offline_test=True)
    a.provision_project('M1');a.grant('M3','M1','generate');a.grant('M3','M1','assets.read')
    a.put_asset('M1','inputs/c2.json',b'fixture')
    service=a.service_token('M3')
    task=a.begin(service,'M1','page','request',100,['inputs/c2.json'])
    first.revoke('offline-1')
    with pytest.raises(Denied,match='UNKNOWN_KEY'):a.read(service,task['token'],task['identity'],'inputs/c2.json')
    second=OfflineKMS(seed=seed)
    reopened=Authority(a.path,a.anchor,second,lambda:1000,offline_test=True)
    with pytest.raises(Denied):reopened.read(service,task['token'],task['identity'],'inputs/c2.json')

def test_durable_key_id_pins_public_material_and_distribution_excludes_revoked(tmp_path):
    seed=b'explicit-offline-key-pin-test-seed-32'
    keys=OfflineKMS(seed=seed)
    a=Authority.provision(tmp_path/'state.sqlite',tmp_path/'anchor',keys,lambda:1000,offline_test=True)
    first=a.public_keys();assert set(first)=={'offline-1'} and len(first['offline-1'])==64
    with pytest.raises(Denied,match='KEY_ID_REUSE'):
        Authority(a.path,a.anchor,OfflineKMS(seed=b'different-offline-test-seed-more-than-32'),lambda:1000,offline_test=True)
    keys.revoke('offline-1')
    restarted=OfflineKMS(seed=seed);b=Authority(a.path,a.anchor,restarted,lambda:1000,offline_test=True)
    assert b.public_keys()=={}
    with pytest.raises(Denied,match='UNKNOWN_KEY'):b.service_token('M3')
    restarted.rotate('offline-2')
    assert set(b.public_keys())=={'offline-2'}
    assert b.service_token('M3')

def test_revoked_key_stays_denied_in_real_new_process(tmp_path):
    import json,subprocess,sys
    seed=b'explicit-offline-key-process-restart-seed'
    keys=OfflineKMS(seed=seed)
    a=Authority.provision(tmp_path/'state.sqlite',tmp_path/'anchor',keys,lambda:1000,offline_test=True)
    a.provision_project('M1');a.grant('M3','M1','generate');a.grant('M3','M1','assets.read');a.put_asset('M1','asset',b'fixture')
    service=a.service_token('M3');attempt=a.begin(service,'M1','page','req',100,['asset']);keys.revoke('offline-1')
    code='''import json,sys
from orchestrator.services.integration_reference import Authority,OfflineKMS,Denied
v=json.loads(sys.stdin.read())
a=Authority(v['path'],v['anchor'],OfflineKMS(seed=b'explicit-offline-key-process-restart-seed'),lambda:1000,offline_test=True)
try:
 a.read(v['service'],v['attempt']['token'],v['attempt']['identity'],'asset');print('UNEXPECTED_ALLOW')
except Denied as e:print(str(e))
'''
    result=subprocess.run([sys.executable,'-B','-c',code],input=json.dumps(dict(path=str(a.path),anchor=str(a.anchor),service=service,attempt=attempt)),capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='UNKNOWN_KEY'

def test_source_proof_key_revocation_survives_provider_restart(tmp_path):
    seed=b'explicit-offline-source-key-restart-seed'
    keys=OfflineKMS(seed=seed)
    a=Authority.provision(tmp_path/'state.sqlite',tmp_path/'anchor',keys,lambda:1000,offline_test=True)
    a.provision_project('M1');a.grant('M3','M1','generate');a.grant('M3','M1','assets.read');a.put_asset('M1','asset',b'fixture')
    service=a.service_token('M3');attempt=a.begin(service,'M1','page','req',100,['asset'])
    a.submit(service,attempt['token'],attempt['identity'],b'result')
    proof=a.provenance(service,attempt['token'],attempt['identity']);keys.revoke('offline-1')
    b=Authority(a.path,a.anchor,OfflineKMS(seed=seed),lambda:1000,offline_test=True)
    with pytest.raises(Denied,match='UNKNOWN_KEY'):b.verify_provenance(proof,expected_identity=attempt['identity'],expected_result=b'result')
