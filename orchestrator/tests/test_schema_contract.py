"""First-round checks against API_v1.0 chapter 1, never appendix decisions.

No xfail: contract violations must remain visible in the test result.
Required/default snapshots describe the current implementation; document field
presence is checked separately because C1/C2 have no required-field table.
"""
import copy
import importlib
import json
import re
from pathlib import Path

import pydantic
import pytest
from pydantic import ValidationError

from orchestrator.schemas.common import APIResponse
from orchestrator.schemas.capture import CaptureData, CaptureResponse
from orchestrator.schemas.ocr import OCRData, OCRTextBlock
from orchestrator.schemas.vlm import VLMData, VLMObject, VLMSafety
from orchestrator.schemas.story import StoryData, StorySegment, StoryModelInfo

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / 'docs/API_v1.0.md').read_text(encoding='utf-8').split('# 附录 A')[0]


def example(start, end):
    section = DOC.split(start, 1)[1].split(end, 1)[0]
    return json.loads(re.search(r'```json\s*(.*?)\s*```', section, re.S)[1])


CAPTURE_RESPONSE = example('## 1.5 ', '## 1.6 ')
OCR = example('### C1 ', '### C2 ')
VLM = example('### C2 ', '### C3 ')
STORY = example('### C3 ', '### C4 ')
TRACE = CAPTURE_RESPONSE['trace_id']
CASES = [
    (APIResponse[CaptureData], CAPTURE_RESPONSE),
    (CaptureResponse, CAPTURE_RESPONSE),
    (CaptureData, CAPTURE_RESPONSE['data']),
    (OCRData, OCR), (OCRTextBlock, OCR['text_blocks'][0]),
    (VLMData, VLM), (VLMObject, VLM['objects'][0]),
    (VLMSafety, VLM['safety']),
    (StoryData, STORY), (StorySegment, STORY['segments'][0]),
    (StoryModelInfo, STORY['model']),
]
IDS = [model.__name__ for model, _ in CASES]


def reject(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize('path', sorted((ROOT / 'orchestrator/schemas').glob('*.py')), ids=lambda p: p.name)
def test_python_import(path):
    importlib.import_module('.'.join(path.relative_to(ROOT).with_suffix('').parts))


def test_pydantic_2():
    assert pydantic.__version__.split('.')[0] == '2'


@pytest.mark.parametrize('model,payload', CASES, ids=IDS)
def test_document_example_and_v2_roundtrip(model, payload):
    obj = model.model_validate_json(json.dumps(payload))
    assert json.loads(obj.model_dump_json(by_alias=True)) == payload
    model.model_json_schema()


@pytest.mark.parametrize('model,payload', CASES, ids=IDS)
def test_document_fields_match(model, payload):
    assert {f.alias or name for name, f in model.model_fields.items()} == set(payload)


@pytest.mark.parametrize('model,payload', CASES, ids=IDS)
def test_unknown_fields_ignored(model, payload):
    obj = model.model_validate(dict(payload, future_field='v1.1'))
    assert 'future_field' not in obj.model_dump()
    assert model.model_json_schema().get('additionalProperties') is not False


# Explicit required/default snapshot, not generated from model_fields.
OPTIONAL = {
    APIResponse[CaptureData]: {'code': 0, 'msg': 'ok', 'data': None},
    CaptureResponse: {'code': 0, 'msg': 'ok', 'data': None},
    CaptureData: {}, OCRData: {'text_blocks': []}, OCRTextBlock: {},
    VLMData: {'objects': [], 'scene_tags': []}, VLMObject: {},
    VLMSafety: {'flags': []}, StoryData: {'safety_flags': []},
    StorySegment: {'image_prompt': None, 'audio_url': None, 'highlight_object_ids': []},
    StoryModelInfo: {},
}
FIELD_CASES = [(m, p, f) for m, p in CASES for f in p]


@pytest.mark.parametrize('model,payload,field', FIELD_CASES,
                         ids=[f'{m.__name__}.{f}' for m,p,f in FIELD_CASES])
def test_required_field_snapshot(model, payload, field):
    if field in OPTIONAL[model]:
        assert not model.model_fields[field].is_required()
        return
    assert model.model_fields['pass_' if field == 'pass' else field].is_required()
    altered = copy.deepcopy(payload)
    del altered[field]
    reject(model, altered)


@pytest.mark.parametrize('model,payload', CASES, ids=IDS)
def test_defaults_snapshot(model, payload):
    defaults = OPTIONAL[model]
    minimal = {k: v for k, v in payload.items() if k not in defaults}
    # Conditional validation requires a matching branch before testing defaults.
    if model is StorySegment:
        minimal['duration_source'] = 'estimate'
    if model is VLMData:
        minimal['status'] = 'empty'
    if model is OCRData:
        minimal.update(status='empty', page_confidence=0)
    obj = model.model_validate(minimal)
    dumped = obj.model_dump(by_alias=True)
    for name, expected in defaults.items():
        assert dumped[name] == expected
    if defaults:
        other = model.model_validate(minimal)
        for name, value in defaults.items():
            if isinstance(value, list):
                assert getattr(obj, name) is not getattr(other, name)


@pytest.mark.parametrize('model,payload,field', FIELD_CASES,
                         ids=[f'{m.__name__}.{f}' for m,p,f in FIELD_CASES])
def test_field_rejects_incompatible_type(model, payload, field):
    altered = copy.deepcopy(payload)
    altered[field] = {'unexpected': 'object'} if not isinstance(payload[field], dict) else ['wrong']
    reject(model, altered)


ID_CASES = [
    (CaptureData, CAPTURE_RESPONSE['data'], 'book_id', ['abcd', 'a12345678901'], ['abc', 'a123456789012', 'Book01', '1book', 'book_01']),
    (CaptureData, CAPTURE_RESPONSE['data'], 'page_id', ['abcd_p01', 'book01_p99'], ['book01-03', 'book01_p3', 'book01_p003', 'Book01_p03']),
    (VLMObject, VLM['objects'][0], 'object_id', ['abcd_p01_o01'], ['book01_p03_o1', 'book01_p03_o001', 'book01_p03_s01']),
    (StorySegment, STORY['segments'][0], 'segment_id', ['abcd_p01_s01'], ['book01_p03_s1', 'book01_p03_s001', 'book01_p03_o01']),
    (OCRTextBlock, OCR['text_blocks'][0], 'block_id', ['abcd_p01_t01'], ['book01_p03_t1', 'book01_p03_o01']),
]


@pytest.mark.parametrize('model,payload,field,valid,invalid', ID_CASES, ids=[c[2] for c in ID_CASES])
def test_id_format(model, payload, field, valid, invalid):
    for value in valid:
        model.model_validate(dict(payload, **{field: value}))
    for value in invalid:
        reject(model, dict(payload, **{field: value}))


@pytest.mark.parametrize('model,payload', [(OCRData, OCR), (VLMData, VLM), (StoryData, STORY)], ids=['ocr','vlm','story'])
@pytest.mark.parametrize('field,value', [('schema_version','2.0'), ('page_no',0), ('elapsed_ms',-1), ('page_id','book01_p04'), ('book_id','book02')])
def test_page_identity_and_constraints(model, payload, field, value):
    reject(model, dict(payload, **{field:value}))


@pytest.mark.parametrize('model,payload', [(OCRTextBlock,OCR['text_blocks'][0]),(VLMObject,VLM['objects'][0])], ids=['ocr','vlm'])
@pytest.mark.parametrize('bbox', [[-1,0,10,10],[0,-1,10,10],[10,0,10,10],[0,10,10,10],[11,0,10,10],[0,11,10,10],[0,0,10],[0,0,1,1,2],[0.5,0,10,10]])
def test_bbox_rejects_invalid(model, payload, bbox):
    reject(model, dict(payload, bbox=bbox))


@pytest.mark.parametrize('model,payload', [(OCRTextBlock,OCR['text_blocks'][0]),(VLMObject,VLM['objects'][0])], ids=['ocr','vlm'])
def test_bbox_forbids_integral_float(model, payload):
    # §1.2.3 explicitly prohibits floats, including JSON 0.0.
    reject(model, dict(payload, bbox=[0.0,0,10,10]))


@pytest.mark.parametrize('model,payload,key', [(OCRData,OCR,'text_blocks'),(VLMData,VLM,'objects')], ids=['ocr','vlm'])
@pytest.mark.parametrize('bbox,valid', [([0,0,1654,2339],True),([0,0,1655,2339],False),([0,0,1654,2340],False)])
def test_bbox_image_boundary(model,payload,key,bbox,valid):
    altered = copy.deepcopy(payload)
    altered[key][0]['bbox'] = bbox
    if valid:
        model.model_validate(altered)
    else:
        reject(model, altered)


@pytest.mark.parametrize('model,payload', [(OCRTextBlock,OCR['text_blocks'][0]),(VLMObject,VLM['objects'][0])], ids=['ocr','vlm'])
@pytest.mark.parametrize('confidence', [-0.01,1.01])
def test_confidence_range(model,payload,confidence):
    reject(model, dict(payload, confidence=confidence))


@pytest.mark.parametrize('field', ['page_no','image_width','image_height'])
def test_capture_positive_numbers(field):
    reject(CaptureData, dict(CAPTURE_RESPONSE['data'], **{field:0}))


def test_capture_absolute_preview_url():
    # §1.15.3: HTTP responses contain absolute asset URLs.
    reject(CaptureData, dict(CAPTURE_RESPONSE['data'], preview_url='previews/page.jpg'))


def test_ocr_empty_valid():
    OCRData.model_validate(dict(OCR,status='empty',text_blocks=[],page_confidence=0))


@pytest.mark.parametrize('blocks,confidence', [(OCR['text_blocks'],0),([],0.1)])
def test_ocr_empty_invariants(blocks,confidence):
    reject(OCRData,dict(OCR,status='empty',text_blocks=blocks,page_confidence=confidence))


def test_vlm_empty_valid():
    VLMData.model_validate(dict(VLM,status='empty',objects=[]))


def test_vlm_empty_rejects_objects():
    reject(VLMData,dict(VLM,status='empty'))


def test_vlm_no_objects_requires_empty():
    reject(VLMData,dict(VLM,objects=[]))


def test_vlm_unique_object_ids():
    reject(VLMData,dict(VLM,objects=[VLM['objects'][0],VLM['objects'][0]]))


@pytest.mark.parametrize('model,payload,key,id_field,bad', [(OCRData,OCR,'text_blocks','block_id','book02_p03_t01'),(VLMData,VLM,'objects','object_id','book02_p03_o01'),(StoryData,STORY,'segments','segment_id','book02_p03_s01')], ids=['ocr','vlm','story'])
def test_child_id_matches_page(model,payload,key,id_field,bad):
    altered = copy.deepcopy(payload)
    altered[key][0][id_field] = bad
    reject(model,altered)


@pytest.mark.parametrize('model,payload', [(VLMSafety,VLM['safety']),(VLMData,VLM)], ids=['safety','nested_vlm'])
def test_safety_pass_default_json_serialization(model,payload):
    assert json.loads(model.model_validate(payload).model_dump_json()) == payload


@pytest.mark.parametrize('passed', [True,False])
def test_safety_pass_explicit_alias_serialization(passed):
    payload = {'pass':passed,'flags':[]}
    assert json.loads(VLMSafety.model_validate(payload).model_dump_json(by_alias=True)) == payload


@pytest.mark.parametrize('source,audio,valid', [('tts',None,False),('tts','',False),('tts','http://localhost/a.mp3',True),('estimate',None,True),('estimate','http://localhost/a.mp3',True),('unknown',None,False)])
def test_story_audio_condition(source,audio,valid):
    payload = dict(STORY['segments'][0],duration_source=source,audio_url=audio)
    if valid:
        StorySegment.model_validate(payload)
    else:
        reject(StorySegment,payload)


def test_story_tts_requires_audio_key():
    payload = copy.deepcopy(STORY['segments'][0])
    del payload['audio_url']
    reject(StorySegment,payload)


def test_story_unique_segment_ids():
    reject(StoryData,dict(STORY,segments=[STORY['segments'][0],STORY['segments'][0]]))


def test_story_highlight_object_id_format():
    altered = copy.deepcopy(STORY)
    altered['segments'][0]['highlight_object_ids'] = ['book01_p03_oBAD']
    reject(StoryData,altered)


@pytest.mark.parametrize('field,value', [('age_level','9-12'),('status','empty'),('segments',[]),('total_duration_sec',0)])
def test_story_constraints(field,value):
    reject(StoryData,dict(STORY,**{field:value}))


@pytest.mark.parametrize('model,payload,key', [(OCRData,OCR,'text_blocks'),(StoryData,STORY,'segments')], ids=['ocr','story'])
def test_order_starts_at_one(model,payload,key):
    altered = copy.deepcopy(payload)
    altered[key][0]['order'] = 2
    reject(model,altered)


def test_api_response_success():
    obj = APIResponse[CaptureData].model_validate(CAPTURE_RESPONSE)
    assert isinstance(obj.data,CaptureData)
    assert obj.code == 0 and obj.msg == 'ok'


def test_api_response_failure():
    payload = dict(code=1001,msg='缺少参数 page_id',data=None,trace_id=TRACE)
    assert json.loads(APIResponse[CaptureData].model_validate(payload).model_dump_json()) == payload


def test_api_response_business_nonzero_can_have_data():
    # §1.9 permits data on business codes 3003/3004; no global null rule.
    obj = APIResponse[dict].model_validate(dict(code=3003,msg='超出绘本范围',data={'answer':'兜底'},trace_id=TRACE))
    assert obj.data == {'answer':'兜底'}


def test_api_response_generic_rejects_wrong_data():
    reject(APIResponse[CaptureData],dict(CAPTURE_RESPONSE,data={'wrong':True}))


@pytest.mark.parametrize('trace', ['bad','tr_abc','tr_'+'I'*26])
def test_api_response_trace_format(trace):
    reject(APIResponse[CaptureData],dict(CAPTURE_RESPONSE,trace_id=trace))


@pytest.mark.parametrize('model,payload', [(OCRData,OCR),(VLMData,VLM)], ids=['ocr','vlm'])
@pytest.mark.parametrize('field,value', [('image_width',0),('image_height',0),('status','unknown')])
def test_vision_dimensions_and_status(model,payload,field,value):
    reject(model,dict(payload,**{field:value}))


@pytest.mark.parametrize('value', [-0.01,1.01])
def test_ocr_page_confidence_range(value):
    reject(OCRData,dict(OCR,page_confidence=value))


@pytest.mark.parametrize('field,value', [('duration_sec',0),('narration',''),('scene',''),('order',0)])
def test_story_segment_constraints(field,value):
    reject(StorySegment,dict(STORY['segments'][0],**{field:value}))


def test_story_estimate_allows_missing_audio_key():
    payload = dict(STORY['segments'][0],duration_source='estimate')
    del payload['audio_url']
    assert StorySegment.model_validate(payload).audio_url is None


def test_ocr_order_unique():
    first = OCR['text_blocks'][0]
    second = dict(first,block_id='book01_p03_t02')
    reject(OCRData,dict(OCR,text_blocks=[first,second]))


@pytest.mark.parametrize('model,payload', CASES, ids=IDS)
def test_json_schema_field_types(model,payload):
    # Compare externally visible JSON Schema types to the formal examples.
    schema = model.model_json_schema(by_alias=True)
    def resolves(node):
        if '$ref' in node:
            node = schema['$defs'][node['$ref'].rsplit('/',1)[1]]
        if 'anyOf' in node:
            return set().union(*(resolves(part) for part in node['anyOf']))
        return {node.get('type')}
    for field,value in payload.items():
        expected = ('boolean' if isinstance(value,bool) else
                    'integer' if isinstance(value,int) else
                    'number' if isinstance(value,float) else
                    'string' if isinstance(value,str) else
                    'array' if isinstance(value,list) else
                    'object' if isinstance(value,dict) else 'null')
        types = resolves(schema['properties'][field])
        assert expected in types or (expected == 'integer' and 'number' in types), field
