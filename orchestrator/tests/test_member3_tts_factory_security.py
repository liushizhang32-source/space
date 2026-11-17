"""Actual standalone factory HTTP boundary; denied requests must never read assets."""
import builtins
import hashlib
import io
import json
import os
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from orchestrator.vendor.member3_v116.agents.generation.config import Settings
from orchestrator.vendor.member3_v116.agents.generation.tts.service import create_app
from orchestrator.services.vision_supervisor.authorization.asset_policy import AssetFiles
from orchestrator.tests.test_member3_m1_callchain import chain, start, _drain
from orchestrator.services import member3_adapter as adapter

PRIVATE = b'closure004-private-audio-bytes-do-not-release'


def observe(response, label, reads):
    dest = os.getenv('CLOSURE004_EVIDENCE')
    if dest:
        with (Path(dest) / 'tts-http-observations.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(dict(case=label, status=response.status_code,
                url=str(response.request.url), content_type=response.headers.get('content-type'),
                body_hex=response.content.hex(), body_sha256=hashlib.sha256(response.content).hexdigest(),
                asset_sha256=hashlib.sha256(PRIVATE).hexdigest(), asset_opens=reads))+'\n')


@pytest.fixture
def asset(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, tts_engine='silent')
    settings.ensure_dirs()
    names = ['private.mp3', 'projectB.mp3', 'revoked.mp3', 'private_manifest.json', 'tts_cached.mp3']
    targets = []
    for name in names:
        p = settings.audios_dir / name
        p.write_bytes(PRIVATE)
        targets.append(os.path.normcase(str(p.resolve())))
    reads = []
    # Instrument the actual open boundary used by pathlib and Starlette/anyio.
    def instrument(original):
        def wrapped(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                actual = os.path.normcase(os.path.abspath(os.fsdecode(file)))
                if actual in targets:
                    reads.append(actual)
            return original(file, *args, **kwargs)
        return wrapped
    monkeypatch.setattr(builtins, 'open', instrument(builtins.open))
    monkeypatch.setattr(io, 'open', instrument(io.open))
    monkeypatch.setattr(os, 'open', instrument(os.open))
    return settings, reads


@pytest.mark.parametrize('environment', ['local', 'dev', 'production'])
@pytest.mark.parametrize('name,headers', [
    ('private.mp3', {}),
    ('projectB.mp3', {'X-Project-ID': 'projectA', 'Authorization': 'Bearer untrusted'}),
    ('revoked.mp3', {'X-Job-State': 'cancelled'}),
    ('private_manifest.json', {}),
])
def test_direct_factory_denies_before_open(asset, monkeypatch, environment, name, headers):
    settings, reads = asset
    monkeypatch.setenv('M1_DEPLOYMENT_ENV', environment)
    monkeypatch.setenv('M1_ASSET_MODE', 'blocked')
    app = create_app(settings)
    assert type(next(r.app for r in app.routes if getattr(r, 'path', '') == '/audios')) is AssetFiles
    with TestClient(app) as client:
        with client.stream('GET', '/audios/' + name, headers=headers) as stream:
            stream.read()
            response = stream
        observe(response, environment + '-' + name, reads)
        assert response.status_code == 503
        assert response.headers['content-type'].startswith('application/json')
        assert response.json()['status'] == 'BLOCKED'
        assert PRIVATE not in response.content
        assert hashlib.sha256(response.content).digest() != hashlib.sha256(PRIVATE).digest()
        assert reads == []


@pytest.mark.parametrize('url', ['/audios/%70rivate.mp3', '/audios/../audios/private.mp3',
    '/audios/%2e%2e/audios/private.mp3', '/audios/..%5caudios%5cprivate.mp3',
    '/audios/private.mp3?download=1', '/audios/private.mp3'])
def test_encoded_range_and_static_paths_cannot_bypass(asset, monkeypatch, url):
    settings, reads = asset
    monkeypatch.setenv('M1_DEPLOYMENT_ENV', 'production')
    monkeypatch.setenv('M1_ASSET_MODE', 'blocked')
    with TestClient(create_app(settings)) as client:
        response = client.get(url, headers={'Range': 'bytes=0-15'})
        observe(response, 'static-range', reads)
        assert response.status_code == 503
        assert response.headers['content-type'].startswith('application/json')
        assert b'closure004-private' not in response.content
        assert reads == []


@pytest.mark.parametrize('environment', ['local', 'dev', 'production'])
def test_post_cannot_read_cache_or_return_private_bytes(asset, monkeypatch, environment):
    settings, reads = asset
    monkeypatch.setenv('M1_DEPLOYMENT_ENV', environment)
    monkeypatch.setenv('M1_ASSET_MODE', 'blocked')
    app = create_app(settings)
    def forbidden(*args, **kwargs):
        pytest.fail('Denied POST reached cache validation or synthesis')
    monkeypatch.setattr(app.state.tts_client, 'synthesize', forbidden)
    with TestClient(app) as client:
        response = client.post('/api/v1/tts', json={'text': 'cached fixture'})
        observe(response, environment + '-post-cache', reads)
        assert response.status_code == 200  # Existing A6 business error envelope.
        assert response.headers['content-type'].startswith('application/json')
        assert response.json()['code'] == 2004 and response.json()['data'] is None
        assert PRIVATE not in response.content and reads == []


def test_default_factory_and_explicit_member_settings_do_not_bypass(asset, monkeypatch):
    settings, reads = asset
    monkeypatch.setenv('DATA_DIR', str(settings.data_dir))
    monkeypatch.setenv('M1_DEPLOYMENT_ENV', 'dev')
    monkeypatch.delenv('M1_ASSET_MODE', raising=False)
    for app in [create_app(), create_app(settings)]:
        with TestClient(app) as client:
            response = client.get('/audios/private.mp3')
            observe(response, 'default-blocked', reads)
            assert response.status_code == 503 and PRIVATE not in response.content and reads == []


@pytest.mark.parametrize('environment,mode', [('dev','offline_mock'), ('production','offline_mock'),
    ('unknown','blocked'), ('local','invalid')])
def test_M1_configuration_validation_is_reused(asset, monkeypatch, environment, mode):
    settings, _ = asset
    monkeypatch.setenv('M1_DEPLOYMENT_ENV', environment)
    monkeypatch.setenv('M1_ASSET_MODE', mode)
    with pytest.raises(ValueError):
        create_app(settings)


def test_explicit_local_demo_allowed_but_internal_asset_stays_denied(asset, monkeypatch):
    settings, reads = asset
    monkeypatch.setenv('M1_DEPLOYMENT_ENV', 'local')
    monkeypatch.setenv('M1_ASSET_MODE', 'offline_mock')
    with TestClient(create_app(settings)) as client:
        response = client.get('/audios/private.mp3')  # Synthetic demo root only.
        observe(response, 'local-demo-permitted-by-M1', reads)
        assert response.status_code == 200 and response.content == PRIVATE
        assert response.headers['content-type'].startswith('audio/mpeg')
        assert reads  # Positive control proves the read instrumentation works.
        reads.clear()
        response = client.get('/audios/private_manifest.json')
        observe(response, 'local-internal-denied', reads)
        assert response.status_code == 503 and PRIVATE not in response.content and reads == []
        assert client.get('/healthz').json()['status'] == 'ok'


def test_explicit_local_silent_tts_post_retains_contract(tmp_path, monkeypatch):
    monkeypatch.setenv('M1_DEPLOYMENT_ENV', 'local')
    monkeypatch.setenv('M1_ASSET_MODE', 'offline_mock')
    settings = Settings(data_dir=tmp_path, tts_engine='silent',
        ffmpeg_path=os.environ['FFMPEG_PATH'], ffprobe_path=os.environ['FFPROBE_PATH'])
    with TestClient(create_app(settings)) as client:
        response = client.post('/api/v1/tts', json={'text': '离线演示'})
        assert response.status_code == 200 and response.json()['code'] == 0
        data = response.json()['data']
        assert set(data) == {'audio_url', 'duration_ms', 'sample_rate'}
        audio = client.get('/audios/' + data['audio_url'].rsplit('/', 1)[-1])
        assert audio.status_code == 200 and len(audio.content) > 0
        assert audio.headers['content-type'].startswith('audio/mpeg')


@pytest.mark.parametrize('environment', ['dev', 'production'])
def test_real_cancelled_job_and_revoked_fence_cannot_read_tts(chain, monkeypatch, environment):
    client, jobs, rig, sessions = chain
    entered, release = threading.Event(), threading.Event()
    video = adapter.compose_video
    def blocking(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return video(*args, **kwargs)
    monkeypatch.setattr(adapter, 'compose_video', blocking)
    jid = start(client)
    assert entered.wait(15)
    client.portal.call(jobs.tasks[jid].cancel)
    release.set()
    client.portal.call(lambda: _drain(jobs.tasks[jid]))
    rig.fences.cancel(rig.page(3).record)
    assert client.get('/api/v1/jobs/' + jid).json()['data']['status'] == 'cancelled'
    settings = Settings(data_dir=jobs.storage.root, tts_engine='silent')
    path = settings.audios_dir / 'cancelled.mp3'
    path.write_bytes(PRIVATE)
    reads = []
    original = builtins.open
    def watch(file, *args, **kwargs):
        if isinstance(file, (str, os.PathLike)) and Path(file).absolute() == path.absolute():
            reads.append(str(file))
        return original(file, *args, **kwargs)
    monkeypatch.setattr(builtins, 'open', watch)
    monkeypatch.setenv('M1_DEPLOYMENT_ENV', environment)
    monkeypatch.setenv('M1_ASSET_MODE', 'blocked')
    with TestClient(create_app(settings)) as denied:
        response = denied.get('/audios/cancelled.mp3')
        observe(response, 'actual-cancelled-' + environment, reads)
        assert response.status_code == 503
        assert response.headers['content-type'].startswith('application/json')
        assert PRIVATE not in response.content and reads == []
    assert rig.authority.totals()['held'] == 1000  # UNKNOWN remains reserved.
