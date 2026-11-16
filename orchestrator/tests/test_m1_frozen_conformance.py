"""Behavioral conformance to unchanged OWNER_APPROVED M1/M2 V1.0 Sidecar."""
from pathlib import Path
from dataclasses import asdict
import copy,hashlib,json
import pytest
from orchestrator.services.vision_supervisor.gate import Gate
from orchestrator.services.vision_supervisor.supervisor import Identity
from orchestrator.schemas.vlm import VLMData

BASE=Path(__file__).resolve().parents[2]/'reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113'
EXAMPLES=json.loads((BASE/'SIDECAR_EXAMPLES.json').read_text(encoding='utf-8'))['examples']

def validate(doc,example):
    raw=(BASE/example['c2_fixture_file']).read_bytes()
    identity=Identity(**{k:doc[k] for k in Identity.__dataclass_fields__})
    Gate.refs(json.dumps(doc,ensure_ascii=False).encode('utf-8'),identity,VLMData.model_validate_json(raw),hashlib.sha256(raw).hexdigest())

@pytest.mark.parametrize('example',EXAMPLES,ids=[e['name'] for e in EXAMPLES])
def test_frozen_sidecar_positive_examples(example):validate(copy.deepcopy(example['sidecar']),example)

@pytest.mark.parametrize('fault',['root-extra','c2-extra','source-extra','observation-extra','confidence-extra','clothing-empty','clothing-whitespace','calibration-self-asserted'])
def test_frozen_sidecar_negative_fields(fault):
    example=EXAMPLES[0];doc=copy.deepcopy(example['sidecar']);obs=doc['observations'][0]
    if fault=='root-extra':doc['contract_status']='self-approved'
    elif fault=='c2-extra':doc['c2']['extra']=True
    elif fault=='source-extra':doc['source']['extra']=True
    elif fault=='observation-extra':obs['extra']=True
    elif fault=='confidence-extra':obs['confidence']['extra']=True
    elif fault=='clothing-empty':obs['appearance']['clothing']=''
    elif fault=='clothing-whitespace':obs['appearance']['clothing']='   '
    else:obs['confidence'].update(kind='model_estimate',value=.7,calibrated=True)
    with pytest.raises(ValueError):validate(doc,example)

@pytest.mark.parametrize('fault',['unknown','missing','bad-transient','unknown-artifact','null-artifact','bool-code'])
def test_frozen_result_envelope_negative(fault):
    from orchestrator.services.vision_supervisor.supervisor import validate_result_envelope
    doc=json.loads((BASE/'fixtures/OCR_RESULT.json').read_text(encoding='utf-8'))
    identity=Identity(**doc['identity'])
    if fault=='unknown':doc['extra']=True
    elif fault=='missing':doc.pop('artifacts')
    elif fault=='bad-transient':doc['transient']='true'
    elif fault=='unknown-artifact':doc['artifacts']['other']='x'
    elif fault=='null-artifact':doc['artifacts']['c1']=None
    else:doc['code']=True
    with pytest.raises(ValueError):validate_result_envelope(doc,identity)

def test_frozen_result_envelope_positive():
    from orchestrator.services.vision_supervisor.supervisor import validate_result_envelope
    doc=json.loads((BASE/'fixtures/OCR_RESULT.json').read_text(encoding='utf-8'))
    validate_result_envelope(doc,Identity(**doc['identity']))

@pytest.mark.parametrize('raw',[b'{"message":"\\ud800"}',b'{"value":1e999}',b'{"nested":["\\udfff"]}'])
def test_frozen_json_rejects_surrogates_and_overflow_numbers(raw):
    from orchestrator.services.vision_supervisor.supervisor import unique_json
    with pytest.raises(ValueError):unique_json(raw)
