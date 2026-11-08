"""Public checker regression; SCHEMA_REPO_ROOT must select the target contract."""
import importlib.util,json,os,shutil
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture
def checker():
 spec=importlib.util.spec_from_file_location('public_checker_under_test',ROOT/'scripts/validate_with_orchestrator.py')
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
@pytest.fixture
def source_root():
 value=os.environ.get('SCHEMA_REPO_ROOT')
 if not value:pytest.fail('Set SCHEMA_REPO_ROOT to the target repository; unverified is not pass')
 return value
@pytest.fixture
def docs(tmp_path):
 for kind in ('ocr','vlm'):shutil.copyfile(ROOT/f'samples/example/book01_p01_{kind}.json',tmp_path/f'book01_p01_{kind}.json')
 return tmp_path
def run(checker,source_root,path):return checker.main(['--repo-root',source_root,'--from',str(path),'--page','book01_p01'])
def test_missing_both_is_failure(checker,source_root,tmp_path):assert run(checker,source_root,tmp_path)==1
def test_missing_vlm_is_failure(checker,source_root,docs):
 (docs/'book01_p01_vlm.json').unlink();assert run(checker,source_root,docs)==1
def test_missing_ocr_is_failure(checker,source_root,docs):
 (docs/'book01_p01_ocr.json').unlink();assert run(checker,source_root,docs)==1
def test_complete_pair_passes(checker,source_root,docs):assert run(checker,source_root,docs)==0
def test_unknown_optional_field_is_accepted(checker,source_root,docs):
 p=docs/'book01_p01_vlm.json';d=json.loads(p.read_text('utf-8'));d['future_field']=True;p.write_text(json.dumps(d),encoding='utf-8');assert run(checker,source_root,docs)==0
def test_non_integer_bbox_is_failure(checker,source_root,docs):
 p=docs/'book01_p01_ocr.json';d=json.loads(p.read_text('utf-8'));d['text_blocks'][0]['bbox'][0]=1.5;p.write_text(json.dumps(d),encoding='utf-8');assert run(checker,source_root,docs)==1
def test_invalid_json_is_failure(checker,source_root,docs):
 (docs/'book01_p01_vlm.json').write_text('{',encoding='utf-8');assert run(checker,source_root,docs)==1
def test_missing_public_models_is_unverified(checker,tmp_path):
 assert checker.main(['--repo-root',str(tmp_path),'--from',str(tmp_path)])==2
