import hashlib,json,os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from orchestrator.tests.test_m1_integration_reference import rig,begin
from orchestrator.services.integration_reference import Denied
from orchestrator.services.integration_reference.files import WindowsAssetReader
from orchestrator.services.offline_protocols.assets import PrivateAssets
from orchestrator.main import create_app
from orchestrator.core.config import Settings
from orchestrator.schemas.common import APIResponse
from orchestrator.vendor.member3_v116.agents.generation.tts.service import create_app as tts_app
from orchestrator.vendor.member3_v116.agents.generation.config import Settings as TTSSettings

@pytest.fixture
def private(rig,tmp_path,monkeypatch):
    monkeypatch.setenv('M1_ASSET_MODE','blocked')
    a,k,n,s=rig;b=begin(rig);a.submit(s,b['token'],b['identity'],b'story')
    root=tmp_path/'private';(root/'audios').mkdir(parents=True)
    raw=b'private-audio-do-not-leak';path=root/'audios/fixture.mp3';path.write_bytes(raw)
    class Reader:
        calls=[]
        def read_bytes(self,name):
            self.calls.append(name);return WindowsAssetReader(root).read_bytes(name)
    reader=Reader();assets=PrivateAssets(a,root,offline_test=True,reader=reader)
    ref=dict(asset_id='audio1',project_id='M1',job_id='req',attempt_id=b['identity']['attempt_id'],
        sha256=hashlib.sha256(raw).hexdigest(),relative_path='audios/fixture.mp3',content_type='audio/mpeg')
    assets.register_output(s,b['token'],b['identity'],ref)
    credential=assets.issue(s,'audio1',project='M1',job='req')
    return rig,b,assets,credential,reader,path,raw,ref

def headers(private):return {'Authorization':'Bearer '+private[0][3],'X-M1-Asset-Token':private[3],'X-M1-Project':'M1','X-M1-Job':'req'}

def test_same_M1_positive_bytes_main_and_TTS(private,tmp_path):
    rig,b,assets,token,reader,path,raw,ref=private
    for app in [create_app(Settings(data_dir=tmp_path/'main',asset_mode='blocked'),m1_assets=assets),
                tts_app(TTSSettings(data_dir=tmp_path/'tts',tts_engine='silent'),m1_assets=assets)]:
        with TestClient(app) as client:
            r=client.get('/_m1/assets/audio1',headers=headers(private))
            assert r.status_code==200 and r.content==raw and r.headers['content-type'].startswith('audio/mpeg')
            assert r.headers['cache-control']=='no-store'
            denied=client.get('/_m1/assets/audio1')
            assert denied.status_code==403 and denied.json()['code']==1005 and raw not in denied.content
            APIResponse[dict].model_validate(denied.json())
            assert denied.json()['trace_id']==denied.headers['X-Trace-ID']
    assert len(reader.calls)==2

@pytest.mark.parametrize('change',['missing','project','job','subject','expired','access_revoked','service_revoked','grant_revoked','task_revoked','key_revoked'])
def test_unauthorized_denied_before_target_open(private,tmp_path,change):
    rig,b,assets,token,reader,path,raw,ref=private;a,k,now,s=rig;h=headers(private)
    if change=='missing':h={}
    elif change=='project':h['X-M1-Project']='other'
    elif change=='job':h['X-M1-Job']='other-job'
    elif change=='subject':h['Authorization']='Bearer '+a.service_token('M2')
    elif change=='expired':now[0]+=61
    elif change=='access_revoked':a.revoke(token,kind='asset_access')
    elif change=='service_revoked':a.revoke(s,kind='service')
    elif change=='grant_revoked':a.grant('M3','M1','assets.read',False)
    elif change=='task_revoked':assets.revoke_task('M1','req')
    elif change=='key_revoked':k.revoke(k.active)
    with TestClient(assets.http_app()) as client:
        r=client.get('/audio1',headers=h)
        assert r.status_code==403 and r.headers['content-type'].startswith('application/json')
        APIResponse[dict].model_validate(r.json())
        assert r.json()['trace_id']==r.headers['X-Trace-ID']
        assert raw not in r.content and hashlib.sha256(r.content).digest()!=hashlib.sha256(raw).digest()
    assert reader.calls==[]

@pytest.mark.parametrize('name',['../secret','audios/../secret','C:/x','audios\\x.mp3','audios/%2e%2e.mp3','json/manifest_story.json'])
def test_registration_path_denied(private,name):
    rig,b,assets,token,reader,path,raw,ref=private
    with pytest.raises(Denied):assets.register_output(rig[3],b['token'],b['identity'],{**ref,'asset_id':'bad','relative_path':name})
    assert reader.calls==[]

def test_hash_tamper_does_not_return_bytes(private):
    rig,b,assets,token,reader,path,raw,ref=private;path.write_bytes(b'tampered')
    with pytest.raises(Denied):assets.read(rig[3],token,'audio1',project='M1',job='req')
    assert reader.calls==['audios/fixture.mp3']

def test_revocation_during_IO_rechecks(private):
    rig,b,assets,token,reader,path,raw,ref=private;original=reader.read_bytes
    def read(name):
        data=original(name);assets.revoke_task('M1','req');return data
    reader.read_bytes=read
    with pytest.raises(Denied):assets.read(rig[3],token,'audio1',project='M1',job='req')

def test_hardlink_denied(private,tmp_path):
    rig,b,assets,token,reader,path,raw,ref=private;os.link(path,tmp_path/'alias.mp3')
    with pytest.raises(Denied):assets.read(rig[3],token,'audio1',project='M1',job='req')

def test_symlink_denied_when_OS_supports_creation(private,tmp_path):
    rig,b,assets,token,reader,path,raw,ref=private;path.unlink()
    outside=tmp_path/'outside.mp3';outside.write_bytes(raw)
    try:path.symlink_to(outside)
    except OSError as exc:pytest.skip('OS lacks file symlink creation permission: '+str(exc.winerror))
    with pytest.raises(Denied):assets.read(rig[3],token,'audio1',project='M1',job='req')

def test_actual_directory_junction_denied(private,tmp_path):
    import subprocess
    rig,b,assets,token,reader,path,raw,ref=private
    parent=path.parent;path.unlink();parent.rmdir()
    outside=tmp_path/'junction-target';outside.mkdir();(outside/path.name).write_bytes(raw)
    assert parent.absolute().is_relative_to(tmp_path.absolute()) and outside.absolute().is_relative_to(tmp_path.absolute())
    result=subprocess.run(['cmd','/c','mklink','/J',str(parent),str(outside)],capture_output=True)
    assert result.returncode==0,result.stderr
    with pytest.raises(Denied):assets.read(rig[3],token,'audio1',project='M1',job='req')

def test_private_profile_cannot_share_offline_mock_static_root(private,tmp_path,monkeypatch):
    rig,b,assets,token,reader,path,raw,ref=private
    with pytest.raises(ValueError):create_app(Settings(data_dir=tmp_path/'demo',asset_mode='offline_mock'),m1_assets=assets)
    monkeypatch.setenv('M1_ASSET_MODE','offline_mock')
    with pytest.raises(ValueError):tts_app(TTSSettings(data_dir=tmp_path/'demo-tts',tts_engine='silent'),m1_assets=assets)

def test_output_id_immutable_and_production_injection_denied(private,tmp_path):
    rig,b,assets,token,reader,path,raw,ref=private
    with pytest.raises(Denied):assets.register_output(rig[3],b['token'],b['identity'],{**ref,'sha256':'0'*64})
    with pytest.raises(ValueError):create_app(Settings(data_dir=tmp_path/'prod',deployment_env='production',asset_mode='blocked'),m1_assets=assets)

def test_output_registry_tamper_is_detected_by_original_authority_anchor(private):
    import sqlite3
    rig,b,assets,token,reader,path,raw,ref=private
    assets.revoke_task('M1','req')
    with sqlite3.connect(rig[0].path) as db:db.execute('DELETE FROM revoked_output_jobs')
    with pytest.raises(Denied):assets.read(rig[3],token,'audio1',project='M1',job='req')
    assert reader.calls==[]

def test_private_registry_and_grant_survive_authority_reopen(private):
    from orchestrator.services.integration_reference import Authority
    rig,b,assets,token,reader,path,raw,ref=private;a,k,n,s=rig
    reopened=Authority(a.path,a.anchor,k,lambda:n[0],offline_test=True)
    again=PrivateAssets(reopened,path.parents[1],offline_test=True,reader=reader)
    assert again.read(s,token,'audio1',project='M1',job='req')[0]==raw

def test_missing_HTTP_credentials_have_authority_audit(private):
    rig,b,assets,token,reader,path,raw,ref=private
    with TestClient(assets.http_app()) as c:assert c.get('/audio1').status_code==403
    with rig[0].tx() as db:assert any(json.loads(r[0])['kind']=='output_http_denied' for r in db.execute('SELECT payload FROM events'))
    assert reader.calls==[]
