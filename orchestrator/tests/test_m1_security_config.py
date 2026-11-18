"""Exercise real Settings -> create_app -> mounted AssetFiles, never production services."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from orchestrator.core.config import Settings
from orchestrator.main import create_app
from orchestrator.services.vision_supervisor.authorization.asset_policy import AssetFiles


@pytest.mark.parametrize('environment,mode', [
    ('dev','offline_mock'), ('production','offline_mock'), ('unknown','blocked'),
    ('unknown','offline_mock'), ('','blocked'), ('LOCAL','blocked'),
    ('local',''), ('local','unknown'), ('local','production'),
])
def test_invalid_real_application_configuration(monkeypatch, tmp_path, environment, mode):
    monkeypatch.setenv('M1_DEPLOYMENT_ENV', environment)
    monkeypatch.setenv('M1_ASSET_MODE', mode)
    monkeypatch.setenv('DATA_DIR', str(tmp_path/'must-not-create'))
    with pytest.raises(ValueError):
        create_app()
    assert not (tmp_path/'must-not-create').exists()


@pytest.mark.parametrize('environment', ['local','dev','production'])
def test_blocked_real_mounts_reject_existing_assets(monkeypatch, tmp_path, environment):
    monkeypatch.setenv('M1_DEPLOYMENT_ENV', environment)
    monkeypatch.setenv('M1_ASSET_MODE','blocked')
    app=create_app(Settings(data_dir=tmp_path))
    for directory,name in [('json','page_story.json'),('previews','page_preview.jpg'),
                           ('audios','page.mp3'),('videos','page_video.mp4')]:
        (tmp_path/directory/name).write_bytes(b'offline-fixture')
    mounts=[r for r in app.routes if getattr(r,'name',None) in {'json','previews','audios','videos'}]
    assert len(mounts)==4 and all(isinstance(r.app,AssetFiles) for r in mounts)
    with TestClient(app) as client:
        for directory,name in [('json','page_story.json'),('previews','page_preview.jpg'),
                               ('audios','page.mp3'),('videos','page_video.mp4')]:
            response=client.get(f'/{directory}/{name}')
            assert response.status_code==503 and response.json()['status']=='BLOCKED'


def test_missing_configuration_defaults_to_blocked(monkeypatch, tmp_path):
    monkeypatch.delenv('M1_DEPLOYMENT_ENV',raising=False)
    monkeypatch.delenv('M1_ASSET_MODE',raising=False)
    settings=Settings(data_dir=tmp_path)
    assert settings.deployment_env=='local' and settings.asset_mode=='blocked'
    (tmp_path/'json').mkdir()
    (tmp_path/'json/page_story.json').write_text('{}')
    with TestClient(create_app(settings)) as client:
        assert client.get('/json/page_story.json').status_code==503


def test_local_mock_serves_final_demo_assets_only(monkeypatch,tmp_path):
    monkeypatch.setenv('M1_DEPLOYMENT_ENV','local')
    monkeypatch.setenv('M1_ASSET_MODE','offline_mock')
    app=create_app(Settings(data_dir=tmp_path))
    for name in ['page_story.json','page_video.json','page_ocr.json','page_vlm.json',
                 'page_refs.json','page_sidecar.json','ASSET_MANIFEST.json','secret.json']:
        (tmp_path/'json'/name).write_text('{}')
    with TestClient(app) as client:
        for name in ['page_story.json','page_video.json']:
            assert client.get('/json/'+name).status_code==200
        for name in ['page_ocr.json','page_vlm.json','page_refs.json','page_sidecar.json',
                     'ASSET_MANIFEST.json','secret.json']:
            assert client.get('/json/'+name).status_code==503


@pytest.mark.parametrize('environment',['dev','production'])
def test_protected_routes_remain_unavailable(monkeypatch,tmp_path,environment):
    monkeypatch.setenv('M1_DEPLOYMENT_ENV',environment)
    monkeypatch.setenv('M1_ASSET_MODE','blocked')
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        for path in ['/internal/gate-authorizations/verify','/internal/generation/submit',
                     '/internal/approvals/issue','/internal/approvals/verify']:
            response=client.post(path,json={})
            # Preserve the team's existing unknown-route business envelope.
            assert response.status_code==200
            assert response.json()['code']==1003 and response.json()['data'] is None
