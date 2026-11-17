"""The new CI profile must never waive the original byte provenance gate."""
import importlib.util,json,sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
@pytest.fixture
def gate(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'tools/ci'))
    spec=importlib.util.spec_from_file_location('proposed_m1_gate',ROOT/'tools/ci/m1_runtime_gate.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.verify_runtime_sources

@pytest.fixture
def candidate(tmp_path):
    paths=['docs/m1-ci-runtime/source-audit.json','docs/protocols/M1_RUNTIME_PROPOSED_SOURCE_SHA256.json']
    baseline=json.loads((ROOT/paths[0]).read_bytes())
    for name in [*paths,*baseline['files']]:
        target=tmp_path/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
    return tmp_path

def test_exact_proposed_patches_preserve_original_27(gate,candidate):
    assert gate(candidate)==dict(status='CI_ONLY',proposal='PROPOSED',original_files=29,original_unchanged=27,patched=2)

def test_changed_candidate_byte_still_fails(gate,candidate):
    path=candidate/'orchestrator/services/integration_reference/authority.py'
    path.write_bytes(path.read_bytes()+b'\n# unrecorded change\n')
    with pytest.raises(ValueError,match='M1 source mismatch'):gate(candidate)

def test_unlisted_third_patch_is_forbidden(gate,candidate):
    path=candidate/'docs/protocols/M1_RUNTIME_PROPOSED_SOURCE_SHA256.json';doc=json.loads(path.read_bytes())
    doc['changes']['orchestrator/services/integration_reference/files.py']=next(iter(doc['changes'].values()))
    path.write_text(json.dumps(doc),encoding='utf-8')
    with pytest.raises(ValueError,match='patch inventory'):gate(candidate)

def test_original_provenance_manifest_cannot_be_rewritten(gate,candidate):
    path=candidate/'docs/m1-ci-runtime/source-audit.json';path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError,match='original source audit changed'):gate(candidate)
