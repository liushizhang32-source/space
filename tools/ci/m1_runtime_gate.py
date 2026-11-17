"""Required Windows M1 offline gate; no credentials or provider settings inherited.

Unlike the media guard, M1 worker tests require actual Windows Job Objects and
their reviewed local subprocess fixtures. This runner never substitutes a weaker
Linux process-group containment policy or skips those tests.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import uuid
from groups import GROUPS, green, junit_counts


def verify_runtime_sources(target):
    """Retain original kit provenance; only two enumerated offline patches.

    A proposal is not an owner signature. It permits CI of the candidate while
    binding every changed byte and preserving the original archive manifest.
    """
    original=(target/'docs/m1-ci-runtime/source-audit.json').read_bytes()
    files=json.loads(original)['files']
    proposed=target/'docs/protocols/M1_RUNTIME_PROPOSED_SOURCE_SHA256.json'
    changes={}
    if proposed.exists():
        p=json.loads(proposed.read_bytes())
        if set(p)!={'version','status','scope','base_source_audit_sha256','changes'} or p['version']!='1.0' or p['status']!='PROPOSED' or p['scope']!='CI_ONLY':
            raise ValueError('M1 candidate source profile invalid')
        if hashlib.sha256(original).hexdigest()!=p['base_source_audit_sha256']:
            raise ValueError('M1 original source audit changed')
        changes=p['changes']
        allowed={'orchestrator/services/integration_reference/authority.py',
                 'orchestrator/services/integration_reference/recovery.py'}
        if set(changes)!=allowed or not allowed.issubset(files):
            raise ValueError('M1 candidate source patch inventory invalid')
        for name,change in changes.items():
            if set(change)!={'before_sha256','after_sha256','reason'} or change['before_sha256']!=files[name] or not change['reason']:
                raise ValueError('M1 source baseline mismatch: '+name)
            if type(change['after_sha256']) is not str or len(change['after_sha256'])!=64 or any(x not in '0123456789abcdef' for x in change['after_sha256']):
                raise ValueError('M1 candidate source SHA invalid')
    for name,expected in files.items():
        expected=changes.get(name,{}).get('after_sha256',expected)
        if hashlib.sha256((target/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('M1 source mismatch: '+name)
    return dict(status='CI_ONLY',proposal='PROPOSED' if changes else None,
                original_files=len(files),original_unchanged=len(files)-len(changes),patched=len(changes))


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv)
    target=args.target.resolve(); output=args.output.resolve()
    attempt=output/'m1-runtime'/('attempt-'+uuid.uuid4().hex[:12])
    attempt.mkdir(parents=True)
    result=dict(group='m1-runtime',expected=GROUPS['m1-runtime'][0],passed=0,failed=0,
                skipped=0,not_executed=GROUPS['m1-runtime'][0],status='not_executed',
                exit_code=1,run_dir=str(attempt),reason='Not started')
    started=time.monotonic()
    try:
        if platform.system()!='Windows' or sys.version_info[:2]!=(3,12):
            raise RuntimeError('Windows CPython 3.12 required; no fallback or skips')
        result['tested_sha']=subprocess.check_output(['git','-c','safe.directory='+target.as_posix(),
            '-C',str(target),'rev-parse','HEAD'],text=True).strip()
        result['source_audit']=verify_runtime_sources(target)
        for name in GROUPS['m1-runtime'][1]:
            if not (target/name).is_file():raise FileNotFoundError(name)
        tests=sorted(p.relative_to(target).as_posix() for p in (target/'orchestrator/tests').glob('test_m1_*.py'))
        if len(tests)!=9:raise ValueError('M1 test-file inventory drift')
        env={k:os.environ[k] for k in ('SystemRoot','WINDIR','COMSPEC','SYSTEMDRIVE') if k in os.environ}
        temporary=attempt/'tmp';temporary.mkdir()
        env.update(PATH=os.pathsep.join([str(Path(sys.executable).parent),os.defpath]),
            PYTHONPATH=str(target),PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1',
            PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',TEMP=str(temporary),TMP=str(temporary),
            TMPDIR=str(temporary),DATA_DIR=str(attempt/'data'),
            M1_DEPLOYMENT_ENV='local',M1_ASSET_MODE='offline_mock',GENERATION_BACKEND='mock',
            TTS_ENGINE='silent',TTS_API_KEY='',LLM_API_KEY='',LLM_BASE_URL='',LLM_MODEL='')
        cmd=[sys.executable,'-B','-m','pytest','-o','addopts=','-p','no:cacheprovider',
             *tests,'-q','-ra','--tb=short','-o','xfail_strict=true',
             '--basetemp',str(temporary/'pytest'),'--junitxml',str(attempt/'junit.xml')]
        result['command']=cmd
        with (attempt/'pytest.log').open('w',encoding='utf-8') as log:
            process=subprocess.run(cmd,cwd=target,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=480)
        result.update(junit_counts(attempt/'junit.xml',result['expected']))
        result.update(exit_code=process.returncode,status='passed' if process.returncode==0 else 'failed',reason='')
        if not green(result):result.update(status='failed',reason='Failure, skip/xfail or inventory drift')
    except Exception as exc:
        result.update(status='failed',exit_code=1,reason=type(exc).__name__+': '+str(exc))
    result['seconds']=round(time.monotonic()-started,3)
    for directory in (attempt,output/'m1-runtime',output/'.upload/m1-runtime'):
        directory.mkdir(parents=True,exist_ok=True)
        (directory/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        if directory!=attempt:
            for name in ('junit.xml','pytest.log'):
                if (attempt/name).exists():shutil.copyfile(attempt/name,directory/name)
    print(json.dumps(result,ensure_ascii=True))
    return 0 if green(result) else 1


if __name__=='__main__':
    raise SystemExit(main())
