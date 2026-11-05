import io
import json
import re
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from orchestrator.core.config import Settings
from orchestrator.main import create_app
from orchestrator.schemas.capture import CaptureData
from orchestrator.schemas.ocr import OCRData
from orchestrator.schemas.story import StoryData
from orchestrator.schemas.vlm import VLMData
from orchestrator.services.storage import ASSETS, MAX_IMAGE_BYTES


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, asset_base_url='http://testserver',
                              queue_delay=0.05, stage_delay=0.05))
    with TestClient(app, raise_server_exceptions=False) as session:
        yield session


def picture(fmt='PNG', size=(64, 48)):
    buffer = io.BytesIO()
    Image.new('RGB', size, 'white').save(buffer, format=fmt)
    return buffer.getvalue()


def envelope(response, code=0):
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {'code', 'msg', 'data', 'trace_id'}
    assert data['code'] == code, data
    assert re.fullmatch(r'tr_[0-9A-HJKMNP-TV-Z]{26}', data['trace_id'])
    if code:
        assert data['data'] is None and data['msg']
    return data


def upload(client, page=3, book='book01'):
    result = client.post('/api/v1/capture', data={'page_no': page, 'book_id': book},
                         files={'image': ('page.png', picture(), 'image/png')})
    return envelope(result)['data']


def generate(client, page_ids=None, **extra):
    return client.post('/api/v1/generate', json=dict(
        page_ids=page_ids or ['book01_p03'], age_level='3-6', **extra))


def wait_done(client, job_id):
    deadline = time.monotonic()+5
    history = []
    while time.monotonic() < deadline:
        data = envelope(client.get('/api/v1/jobs/'+job_id))['data']
        history.append(data)
        if data['status'] in ('done', 'failed', 'cancelled'):
            return data, history
        time.sleep(0.01)
    pytest.fail('Mock job did not reach terminal state')


@pytest.mark.parametrize('fmt,extension,mime', [
    ('JPEG','jpg','image/jpeg'), ('PNG','png','image/png'), ('WEBP','webp','image/webp')])
def test_upload_and_preview(client, fmt, extension, mime):
    original = picture(fmt)
    response = client.post('/api/v1/capture', data={'page_no':3,'book_id':'book01'},
                           files={'image':('page.'+extension,original,mime)})
    data = envelope(response)['data']
    CaptureData.model_validate(data)
    assert (data['image_width'],data['image_height']) == (64,48)
    assert data['page_id'] == 'book01_p03'
    assert (client.app.state.storage.root / f'uploads/book01_p03_orig.{extension}').read_bytes() == original
    preview = client.get(data['preview_url'])
    assert preview.status_code == 200 and preview.headers['content-type'] == 'image/jpeg'
    with Image.open(io.BytesIO(preview.content)) as image:
        assert image.size == (64,48)
    assert client.app.state.jobs.jobs == {}
    assert list((client.app.state.storage.root/'json').iterdir()) == []


def test_optional_book_id(client):
    response = client.post('/api/v1/capture',data={'page_no':1},
                           files={'image':('page.png',picture(),'image/png')})
    data = envelope(response)['data']
    assert re.fullmatch('[a-z][a-z0-9]{3,11}',data['book_id'])
    assert data['page_id'] == data['book_id']+'_p01'


@pytest.mark.parametrize('filename,content,mime', [
    ('a.gif',picture('GIF'),'image/gif'),
    ('a.png',b'not an image','image/png'),
    ('a.jpg',picture(),'image/jpeg'),
    ('a.png',picture(),'image/jpeg')])
def test_invalid_image_format(client,filename,content,mime):
    envelope(client.post('/api/v1/capture',data={'page_no':1},
        files={'image':(filename,content,mime)}),1006)
    assert not client.app.state.storage.pages


def test_image_file_size_limit(client):
    envelope(client.post('/api/v1/capture',data={'page_no':1},
        files={'image':('a.png',b'x'*(MAX_IMAGE_BYTES+1),'image/png')}),1004)


def test_exact_file_size_boundary(client):
    content = picture()
    content += b'\0'*(MAX_IMAGE_BYTES-len(content))
    envelope(client.post('/api/v1/capture',data={'page_no':1},
        files={'image':('a.png',content,'image/png')}))


@pytest.mark.parametrize('width,code', [(4096,0),(4097,1002)])
def test_image_dimension_limit(client,width,code):
    envelope(client.post('/api/v1/capture',data={'page_no':1},
        files={'image':('a.png',picture(size=(width,2)),'image/png')}),code)


@pytest.mark.parametrize('fields', [
    {'page_no':0}, {'page_no':100}, {'page_no':'wrong'},
    {'page_no':1,'book_id':'Bad_ID'}, {'page_no':1,'book_id':'../x'}])
def test_capture_invalid_parameters(client,fields):
    envelope(client.post('/api/v1/capture',data=fields,
             files={'image':('a.png',picture(),'image/png')}),1002)


@pytest.mark.parametrize('missing', ['image','page_no'])
def test_capture_missing_fields(client,missing):
    kwargs = {'data':{'page_no':1},'files':{'image':('a.png',picture(),'image/png')}}
    del kwargs['files' if missing == 'image' else 'data']
    data = envelope(client.post('/api/v1/capture',**kwargs),1001)
    assert missing in data['msg']


def test_job_progress_completion_and_real_artifacts(client):
    upload(client)
    created = envelope(generate(client))['data']
    assert created['status'] == 'queued' and created['poll_after_ms'] == 2000
    assert re.fullmatch(r'job_[0-9A-HJKMNP-TV-Z]{26}',created['job_id'])
    done,history = wait_done(client,created['job_id'])
    assert done['status'] == 'done' and done['progress'] == 100
    assert any(j['status']=='queued' for j in history)
    assert any(j['status']=='running' for j in history)
    assert [j['progress'] for j in history] == sorted(j['progress'] for j in history)
    page = done['pages'][0]
    assert page['status']=='done' and page['degraded']==[] and page['error'] is None
    assert [s['name'] for s in page['stages']]==['ocr','vlm','story','tts','render']
    assert [s['status'] for s in page['stages']]==['empty','empty','ok','ok','ok']
    assert all(s['elapsed_ms'] >= 0 for s in page['stages'])
    assert done['created_at'].endswith('Z') and done['updated_at'].endswith('Z')
    for state in history:
        for p in state['pages']:
            if p['video_url']:
                assert client.get(p['video_url']).status_code == 200
    video = client.get(page['video_url'])
    assert video.content == (ASSETS/'mock.mp4').read_bytes()
    assert video.headers['content-type']=='video/mp4'
    story = StoryData.model_validate(client.get(page['story_url']).json())
    audio = client.get(story.segments[0].audio_url)
    assert audio.content == (ASSETS/'mock.mp3').read_bytes()
    root = client.app.state.storage.root/'json'
    OCRData.model_validate_json((root/'book01_p03_ocr.json').read_text(encoding='utf-8'))
    VLMData.model_validate_json((root/'book01_p03_vlm.json').read_text(encoding='utf-8'))
    assert client.get('/json/book01_p03_video.json').json()['video_url']==page['video_url']


def test_queued_and_running_idempotency(client):
    upload(client)
    first = envelope(generate(client))['data']['job_id']
    assert envelope(generate(client))['data']['job_id']==first
    deadline = time.monotonic()+3
    while time.monotonic()<deadline:
        state = envelope(client.get('/api/v1/jobs/'+first))['data']
        if state['status']=='running':
            assert envelope(generate(client))['data']['job_id']==first
            break
        time.sleep(0.005)
    else:
        pytest.fail('running state was not observed')


@pytest.mark.parametrize('old_state', ['queued', 'running'])
def test_force_cancels_old_job(client, old_state):
    upload(client)
    first = envelope(generate(client))['data']['job_id']
    if old_state == 'running':
        deadline = time.monotonic()+3
        while time.monotonic()<deadline:
            if envelope(client.get('/api/v1/jobs/'+first))['data']['status']=='running':
                break
            time.sleep(0.005)
        else:
            pytest.fail('running state was not observed')
    second = envelope(generate(client,force=True))['data']['job_id']
    assert first != second
    assert envelope(client.get('/api/v1/jobs/'+first))['data']['status']=='cancelled'
    assert wait_done(client,second)[0]['status']=='done'
    assert envelope(client.get('/api/v1/jobs/'+first))['data']['status']=='cancelled'


def test_done_creates_new_job(client):
    upload(client)
    first = envelope(generate(client))['data']['job_id']
    assert wait_done(client,first)[0]['status']=='done'
    assert envelope(generate(client))['data']['job_id'] != first


def test_missing_job(client):
    envelope(client.get('/api/v1/jobs/job_missing'),1003)


@pytest.mark.parametrize('payload,code', [
    ({},1001), ({'page_ids':['book01_p03']},1001),
    ({'page_ids':[],'age_level':'3-6'},1002),
    ({'page_ids':['book01-03'],'age_level':'3-6'},1002),
    ({'page_ids':['book01_p03'],'age_level':'9-12'},1002),
    ({'page_ids':['book01_p03']*31,'age_level':'3-6'},1002),
    ({'page_ids':['book01_p03','book01_p03'],'age_level':'3-6'},1002),
    ({'page_ids':['book02_p01'],'age_level':'3-6'},1003),
    ({'page_ids':['book01_p03'],'age_level':'3-6','force':'wrong'},1002)])
def test_generate_errors(client,payload,code):
    envelope(client.post('/api/v1/generate',json=payload),code)


def test_bad_json_uniform_error(client):
    envelope(client.post('/api/v1/generate',content='{',headers={'Content-Type':'application/json'}),1002)


def test_concurrency_limit_and_duplicate_at_capacity(client):
    # Use a longer queue so all four captures stay active during this check.
    object.__setattr__(client.app.state.storage.settings,'queue_delay',1)
    for page in range(1,5):
        upload(client,page)
    jobs = [envelope(generate(client,[f'book01_p{page:02d}']))['data']['job_id'] for page in range(1,4)]
    envelope(generate(client,['book01_p04']),2003)
    assert envelope(generate(client,['book01_p01']))['data']['job_id']==jobs[0]


def test_partial_overlap_rejected_without_silent_page_loss(client):
    object.__setattr__(client.app.state.storage.settings,'queue_delay',1)
    upload(client,1)
    upload(client,2)
    first = envelope(generate(client,['book01_p01']))['data']['job_id']
    envelope(generate(client,['book01_p01','book01_p02']),2003)
    assert envelope(client.get('/api/v1/jobs/'+first))['data']['status']=='queued'


def test_batch_sorted_by_page_number(client):
    upload(client,10)
    upload(client,2)
    job = envelope(generate(client,['book01_p10','book01_p02']))['data']['job_id']
    state = envelope(client.get('/api/v1/jobs/'+job))['data']
    assert [p['page_no'] for p in state['pages']]==[2,10]
    assert wait_done(client,job)[0]['status']=='done'


def test_unknown_route_uniform_error(client):
    envelope(client.get('/api/v1/not-present'),1003)


def test_mock_artifact_failure_visible(client,monkeypatch):
    upload(client)
    def fail(*args):
        raise OSError('simulated disk failure')
    monkeypatch.setattr(client.app.state.storage,'produce',fail)
    job = envelope(generate(client))['data']['job_id']
    done,_ = wait_done(client,job)
    assert done['status']=='failed' and done['error']['code']==9001
    assert done['pages'][0]['stages'][0]['status']=='failed'
    assert done['pages'][0]['video_url'] is None


def test_unhandled_exception_uniform_error(client,monkeypatch):
    def fail(*args):
        raise RuntimeError('private details should not appear')
    monkeypatch.setattr(client.app.state.jobs,'get',fail)
    data = envelope(client.get('/api/v1/jobs/anything'),9001)
    assert 'private' not in data['msg']


def test_openapi_and_trace_per_request(client):
    schema = client.get('/openapi.json').json()
    assert all(p in schema['paths'] for p in ('/api/v1/capture','/api/v1/generate','/api/v1/jobs/{job_id}'))
    first = envelope(client.get('/api/v1/jobs/a'),1003)
    second = envelope(client.get('/api/v1/jobs/a'),1003)
    assert first['trace_id'] != second['trace_id']
