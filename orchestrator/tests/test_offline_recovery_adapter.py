from pathlib import Path
import pytest
import orchestrator.services.integration_reference.recovery as recovery

def test_transient_Windows_sharing_retries_same_atomic_replace(tmp_path,monkeypatch):
    source=tmp_path/'source';target=tmp_path/'quarantine';source.mkdir();(source/'marker').write_bytes(b'original')
    original=recovery.os.replace;calls=[]
    def transient(a,b):
        calls.append((a,b))
        if len(calls)<3:
            exc=PermissionError('sharing');exc.winerror=5;raise exc
        return original(a,b)
    monkeypatch.setattr(recovery.os,'replace',transient)
    recovery.replace_offline(source,target)
    assert len(calls)==3 and all(x==(source,target) for x in calls)
    assert not source.exists() and (target/'marker').read_bytes()==b'original'

def test_persistent_sharing_denial_preserves_source_and_raises(tmp_path,monkeypatch):
    source=tmp_path/'source';source.mkdir();(source/'marker').write_bytes(b'original')
    times=iter([0,2])
    monkeypatch.setattr(recovery.time,'monotonic',lambda:next(times))
    def denied(*args):
        exc=PermissionError('persistent');exc.winerror=32;raise exc
    monkeypatch.setattr(recovery.os,'replace',denied)
    with pytest.raises(PermissionError):recovery.replace_offline(source,tmp_path/'target')
    assert (source/'marker').read_bytes()==b'original' and not (tmp_path/'target').exists()

def test_unrelated_error_not_retried(tmp_path,monkeypatch):
    calls=[]
    def denied(*args):calls.append(args);raise PermissionError('not a Windows sharing error')
    monkeypatch.setattr(recovery.os,'replace',denied)
    with pytest.raises(PermissionError):recovery.replace_offline(tmp_path/'a',tmp_path/'b')
    assert len(calls)==1
