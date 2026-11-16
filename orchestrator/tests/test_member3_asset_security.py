"""Asset policy integration: real HTTP bytes, not status-code-only assertions."""
import hashlib
import json
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from orchestrator.core.config import Settings
from orchestrator.main import create_app
from orchestrator.services.vision_supervisor.authorization.asset_policy import AssetFiles

ASSET=b'{"fixture_secret":"protected-story-bytes"}'

def record(response, case):
    dest=os.getenv('JOINT_SECURITY_EVIDENCE_DIR')
    if dest:
        path=Path(dest);path.mkdir(parents=True,exist_ok=True)
        with (path/'asset-http-observations.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(case=case,url=str(response.request.url),
                authorization_present='authorization' in response.request.headers,
                status=response.status_code,content_type=response.headers.get('content-type'),
                body=response.text,body_sha256=hashlib.sha256(response.content).hexdigest(),
                asset_sha256=hashlib.sha256(ASSET).hexdigest()))+'\n')

@pytest.mark.parametrize('environment',['dev','production'])
def test_blocked_real_M3_application_never_serves_asset_bytes(tmp_path,environment):
    app=create_app(Settings(data_dir=tmp_path,deployment_env=environment,asset_mode='blocked',generation_backend='member3'))
    (tmp_path/'json/book01_p03_story.json').write_bytes(ASSET)
    with TestClient(app) as client:
        response=client.get('/json/book01_p03_story.json')
        record(response,environment+'-blocked')
        assert response.status_code==503
        assert response.json()['status']=='BLOCKED'
        assert response.headers['content-type'].startswith('application/json')
        assert response.content!=ASSET and b'protected-story-bytes' not in response.content

@pytest.mark.parametrize('environment',['dev','production'])
@pytest.mark.parametrize('url',[
    '/json/book01_p03_story.json','/json/book01_p03_ocr.json',
    '/json/%62ook01_p03_story.json','/json/../json/book01_p03_story.json',
    '/json/%2e%2e/json/book01_p03_story.json','/json/..%5cjson%5cbook01_p03_story.json',
    '/audios/../json/book01_p03_story.json','/videos/../json/book01_p03_story.json'])
def test_anonymous_static_and_encoded_paths_cannot_bypass(tmp_path,environment,url):
    app=create_app(Settings(data_dir=tmp_path,deployment_env=environment,asset_mode='blocked'))
    for name in ['book01_p03_story.json','book01_p03_ocr.json']:(tmp_path/'json'/name).write_bytes(ASSET)
    with TestClient(app) as client:
        response=client.get(url,headers={'X-User':'fixture-identity-has-no-authority'})
        record(response,environment+'-path')
        assert response.content!=ASSET and b'protected-story-bytes' not in response.content
        if response.status_code==503:assert response.json()['status']=='BLOCKED'
        else:
            assert response.status_code==200 and response.json()['code']==1003

@pytest.mark.parametrize('environment',['unknown','','LOCAL'])
def test_unknown_environment_is_not_local(tmp_path,environment):
    with pytest.raises(ValueError):Settings(data_dir=tmp_path,deployment_env=environment,asset_mode='blocked')

@pytest.mark.parametrize('environment',['dev','production'])
def test_deployed_offline_mock_rejected(tmp_path,environment):
    with pytest.raises(ValueError):Settings(data_dir=tmp_path,deployment_env=environment,asset_mode='offline_mock')

def test_explicit_local_mock_keeps_final_asset_rule_and_API_routes(tmp_path,monkeypatch):
    monkeypatch.setenv('M1_DEPLOYMENT_ENV','local')
    app=create_app(Settings(data_dir=tmp_path,deployment_env='local',asset_mode='offline_mock'))
    (tmp_path/'json/book01_p03_story.json').write_bytes(ASSET)
    (tmp_path/'json/book01_p03_ocr.json').write_bytes(ASSET)
    with TestClient(app) as client:
        public=client.get('/json/book01_p03_story.json');record(public,'local-explicit-final')
        assert public.status_code==200 and public.content==ASSET
        internal=client.get('/json/book01_p03_ocr.json');record(internal,'local-internal')
        assert internal.status_code==503 and internal.json()['status']=='BLOCKED'
        assert client.get('/openapi.json').status_code==200
        assert client.get('/api/v1/jobs/not-found').json()['code']==1003
        # The existing orchestrator has no Health route; keep its original error contract.
        assert client.get('/health').json()['code']==1003

def test_all_actual_static_mounts_use_original_M1_policy(tmp_path):
    app=create_app(Settings(data_dir=tmp_path,asset_mode='blocked'))
    mounts=[r for r in app.routes if getattr(r,'path',None) in ['/previews','/json','/audios','/videos']]
    assert len(mounts)==4
    assert all(type(r.app) is AssetFiles for r in mounts)
