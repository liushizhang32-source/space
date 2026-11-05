"""Targeted regressions for the four authorized round-two fixes."""
import copy
import json

import pytest
from pydantic import ValidationError

from orchestrator.schemas.capture import CaptureData
from orchestrator.schemas.ocr import OCRTextBlock
from orchestrator.schemas.story import StoryData, StorySegment
from orchestrator.schemas.vlm import VLMData, VLMObject, VLMSafety
from test_schema_contract import CAPTURE_RESPONSE, OCR, STORY, VLM


@pytest.mark.parametrize('model,payload', [
    (OCRTextBlock, OCR['text_blocks'][0]),
    (VLMObject, VLM['objects'][0]),
], ids=['ocr', 'vlm'])
@pytest.mark.parametrize('position', range(4))
@pytest.mark.parametrize('kind', ['integral_float', 'fractional_float', 'bool', 'numeric_string'])
@pytest.mark.parametrize('mode', ['python', 'json'])
def test_bbox_each_coordinate_requires_integer(model, payload, position, kind, mode):
    bbox = [0, 0, 10, 10]
    original = bbox[position]
    bbox[position] = {
        'integral_float': float(original),
        'fractional_float': original + 0.5,
        'bool': bool(original),
        'numeric_string': str(original),
    }[kind]
    changed = dict(payload, bbox=bbox)
    with pytest.raises(ValidationError) as exc:
        if mode == 'json':
            model.model_validate_json(json.dumps(changed))
        else:
            model.model_validate(changed)
    assert any(error['loc'] == ('bbox', position) and error['type'] == 'int_type'
               for error in exc.value.errors())


@pytest.mark.parametrize('model,payload', [
    (OCRTextBlock, OCR['text_blocks'][0]),
    (VLMObject, VLM['objects'][0]),
], ids=['ocr', 'vlm'])
def test_bbox_integer_json_array_still_roundtrips(model, payload):
    changed = dict(payload, bbox=[0, 0, 10, 10])
    obj = model.model_validate_json(json.dumps(changed))
    output = json.loads(obj.model_dump_json())['bbox']
    assert output == changed['bbox'] and isinstance(output, list)
    assert all(type(value) is int for value in output)


@pytest.mark.parametrize('url', [
    'http://example.com',
    'https://Example.COM:443/a%2fb?q=Ab%2F#Part',
    'HTTP://EXAMPLE.COM/Preview.JPG',
    'http://127.0.0.1:8000/previews/page.jpg',
    'http://localhost:8000/page.jpg',
    'https://[::1]:8000/page.jpg',
])
def test_capture_valid_http_url_preserves_string(url):
    obj = CaptureData.model_validate(dict(CAPTURE_RESPONSE['data'], preview_url=url))
    assert type(obj.preview_url) is str
    assert obj.preview_url == url
    assert obj.model_dump()['preview_url'] == url
    assert json.loads(obj.model_dump_json())['preview_url'] == url


@pytest.mark.parametrize('url', [
    '', 'previews/page.jpg', '//example.com/page.jpg',
    'ftp://example.com/page.jpg', 'file:///page.jpg', 'mailto:user@example.com',
    'http://', 'http:///page.jpg', 'https://?x=1',
    'https://exa mple.com/page.jpg', 'https://example.com:99999/page.jpg',
])
def test_capture_rejects_non_http_or_missing_invalid_host(url):
    with pytest.raises(ValidationError):
        CaptureData.model_validate(dict(CAPTURE_RESPONSE['data'], preview_url=url))


@pytest.mark.parametrize('model', [VLMSafety, VLMData], ids=['standalone', 'nested'])
@pytest.mark.parametrize('input_name', ['pass', 'pass_'])
@pytest.mark.parametrize('passed', [True, False])
def test_safety_default_dict_and_json_alias_output(model, input_name, passed):
    safety = {input_name: passed, 'flags': []}
    payload = safety if model is VLMSafety else dict(VLM, safety=safety)
    obj = model.model_validate(payload)
    inner = obj if model is VLMSafety else obj.safety
    assert inner.pass_ is passed
    for output in (obj.model_dump(), json.loads(obj.model_dump_json()),
                   obj.model_dump(by_alias=True),
                   json.loads(obj.model_dump_json(by_alias=True))):
        result = output if model is VLMSafety else output['safety']
        assert result == {'pass': passed, 'flags': []}
        assert 'pass_' not in result
    restored = model.model_validate_json(obj.model_dump_json(by_alias=True))
    assert restored.model_dump() == obj.model_dump()


@pytest.mark.parametrize('object_id', ['book01_p03_o01', 'book01_p03_o99'])
def test_story_valid_highlight_ids_without_cross_file_lookup(object_id):
    changed = copy.deepcopy(STORY)
    changed['segments'][0]['highlight_object_ids'] = [object_id]
    assert StoryData.model_validate(changed).segments[0].highlight_object_ids == [object_id]


@pytest.mark.parametrize('object_id', [
    'book01_p03_o1', 'book01_p03_o001', 'book01_p03_oBAD',
    'book01_p03_o01extra', 'Book01_p03_o01', 'book_01_p03_o01',
])
def test_story_rejects_malformed_highlight_id_elements(object_id):
    changed = dict(STORY['segments'][0], highlight_object_ids=[object_id])
    with pytest.raises(ValidationError) as exc:
        StorySegment.model_validate(changed)
    assert any(error['loc'] == ('highlight_object_ids', 0) for error in exc.value.errors())


@pytest.mark.parametrize('object_id', ['book01_p04_o01', 'book02_p03_o01'])
def test_story_rejects_well_formed_cross_page_highlights(object_id):
    changed = copy.deepcopy(STORY)
    changed['segments'][0]['highlight_object_ids'] = [object_id]
    with pytest.raises(ValidationError, match='highlight_object_id must belong'):
        StoryData.model_validate(changed)


def test_story_omitted_highlights_remain_independent_empty_lists():
    changed = copy.deepcopy(STORY)
    del changed['segments'][0]['highlight_object_ids']
    first = StoryData.model_validate(changed).segments[0]
    second = StoryData.model_validate(changed).segments[0]
    assert first.highlight_object_ids == second.highlight_object_ids == []
    assert first.highlight_object_ids is not second.highlight_object_ids
