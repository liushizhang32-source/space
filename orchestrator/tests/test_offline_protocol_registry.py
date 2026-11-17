import hashlib,json,re
from pathlib import Path
import pytest
from orchestrator.services.offline_protocols.billing import KEYS

ROOT=Path(__file__).resolve().parents[2];D=ROOT/'docs/protocols'

@pytest.mark.parametrize('pid',['P1','P2','P3','P4'])
def test_registry_version_status_and_clause_trace(pid):
    record=next(x for x in json.loads((D/'registry.json').read_text(encoding='utf-8')) if x['id']==pid)
    doc=(D/record['file']).read_text(encoding='utf-8');trace=(D/'PROTOCOL_TRACEABILITY_MATRIX.md').read_text(encoding='utf-8')
    assert record['version']=='1.0' and record['status']=='PROPOSED'
    assert 'Status: PROPOSED' in doc
    for i in range(1,record['clauses']+1):assert f'{pid}-{i:02d}' in doc and f'{pid}-{i:02d}' in trace

def test_billing_schema_matches_strict_code_keys():
    schema=json.loads((D/'BILLING_EVENT_SCHEMA.json').read_text(encoding='utf-8'))
    assert set(schema['required'])==set(schema['properties'])==KEYS
    assert schema['additionalProperties'] is False

def test_frozen_copy_unchanged():
    # The original manifest hashes every original frozen artifact except itself.
    root=D/'frozen_m1_m2_v1_0';lines=(root/'MANIFEST.sha256').read_text(encoding='utf-8').splitlines()
    for line in lines:
        if not line.strip():continue
        digest,name=line.split(None,1);name=name.strip().lstrip('*')
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest
    assert 'FROZEN' in (root/'M1_M2_OFFLINE_PROTOCOL_V1.0.md').read_text(encoding='utf-8')
