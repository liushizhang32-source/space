"""Run one independently reported gate against a separate selected checkout."""
import argparse
import ast
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

from groups import GROUPS, MEDIA, green, junit_counts

CONTROL = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--group', required=True, choices=GROUPS)
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    target = args.target.resolve()
    report_dir = args.output.resolve()/args.group
    out = report_dir/('attempt-'+uuid.uuid4().hex[:12])
    out.mkdir(parents=True, exist_ok=True)
    expected, required = GROUPS[args.group]
    result = dict(group=args.group, expected=expected, passed=0, failed=0, skipped=0,
                  not_executed=expected, status='not_executed', exit_code=None,
                  target=str(target), run_dir=str(out), commands=[], reason='Execution has not started')

    def save():
        (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        (report_dir/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    save()
    start = time.monotonic()
    try:
        missing = [p for p in [*required, 'orchestrator/tests/requirements-api-test.txt'] if not (target/p).exists()]
        if missing:
            raise FileNotFoundError('Missing test/resources: '+', '.join(missing))
        result['tested_sha'] = subprocess.check_output(['git', '-c', 'safe.directory='+target.as_posix(),
            '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip()
        sources = [p for p in (target/'orchestrator').rglob('*.py')
                   if not any(part in {'__pycache__', '_test_tmp', '.venv'} for part in p.parts)]
        for source in sources:
            ast.parse(source.read_bytes(), filename=str(source))
        result['target_ast_files'] = len(sources)
        if args.preflight:
            result['reason'] = 'Required files present; setup/execution still pending'
            save()
            return 0
        env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'COMSPEC', 'SYSTEMDRIVE',
               'LD_LIBRARY_PATH') if k in os.environ}
        (out/'tmp').mkdir(exist_ok=True)
        (out/'logs').mkdir(exist_ok=True)
        (out/'downloads').mkdir(exist_ok=True)
        ff = str(Path(os.environ.get('FFMPEG_PATH') or shutil.which('ffmpeg') or '/missing/ffmpeg').resolve())
        probe = str(Path(os.environ.get('FFPROBE_PATH') or shutil.which('ffprobe') or '/missing/ffprobe').resolve())
        env.update(CI_TARGET=str(target), CI_RUN_DIR=str(out), DATA_DIR=str(out/'data'),
            TMPDIR=str(out/'tmp'), TEMP=str(out/'tmp'), TMP=str(out/'tmp'),
            PATH=os.pathsep.join([str(Path(sys.executable).parent), os.defpath]),
            PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
            GENERATION_BACKEND='mock', TTS_ENGINE='silent', TTS_HTTP_URL='', TTS_API_KEY='',
            LLM_BASE_URL='', LLM_MODEL='', LLM_API_KEY='', SAFETY_ENABLED='0', SAFETY_BLOCKLIST='',
            ASSET_BASE_URL='http://127.0.0.1:8001', FFMPEG_PATH=ff, FFPROBE_PATH=probe,
            VIDEO_FONT=os.environ.get('VIDEO_FONT', ''), VIDEO_RESOLUTION='720x1280', VIDEO_FPS='25')
        result['versions'] = {'python': sys.version, **{n: importlib.metadata.version(n) for n in
            ('pydantic', 'pytest', 'fastapi', 'starlette', 'httpx', 'Pillow')}}

        def execute(mode, arguments, cwd, label, timeout=240):
            cmd = [sys.executable, str(CONTROL/'guard.py'), mode, *map(str, arguments)]
            result['commands'].append({'command': cmd, 'cwd': str(cwd), 'timeout': timeout})
            save()
            process = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                start_new_session=(os.name != 'nt'),
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            timed_out = False
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == 'nt':
                    # Terminate only this test-owned process tree; never delete its files.
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   capture_output=True, timeout=15)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    stdout, stderr = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name != 'nt':
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    stdout, stderr = process.communicate(timeout=5)
            (out/(label+'.log')).write_text(stdout+'\n'+stderr, encoding='utf-8')
            print(stdout[-3500:], flush=True)
            if process.returncode:
                print(stderr[-1500:], flush=True)
            return 124 if timed_out else process.returncode

        if args.group in MEDIA:
            for tool in (ff, probe):
                p = subprocess.run([tool, '-version'], capture_output=True, text=True, timeout=10)
                if p.returncode:
                    raise RuntimeError('Media tool preflight failed')
                result.setdefault('media_versions', []).append(p.stdout.splitlines()[0])
            if not Path(env['VIDEO_FONT']).is_file():
                raise FileNotFoundError('VIDEO_FONT must identify an installed CJK font')
        if args.group == 'enhanced':
            if execute('prepare', [], target/'orchestrator/vendor/member3_v116', 'prepare'):
                raise RuntimeError('Fresh MOCK fixture preparation failed')
        if args.group == 'http':
            code = execute('http', [], target, 'http', timeout=150)
            http = json.loads((out/'http-integration-results.json').read_text(encoding='utf-8'))
            result.update(passed=http['passed'], failed=http['failed'], skipped=0,
                not_executed=max(0, expected-http['passed']-http['failed']))
            if http['server_exit'] != 0 or not http['port_closed']:
                raise RuntimeError('HTTP server did not shut down cleanly')
        else:
            if args.group == 'member134':
                cwd = target/'orchestrator/vendor/member3_v116'
                tests = ['tests']
                options = []  # Preserve author's pytest.ini and warning policy.
            else:
                cwd = target
                tests = ([str(CONTROL/'member3'/n) for n in
                    ('test_independent.py', 'test_v115_boundary.py', 'test_v116_boundary.py')]
                    if args.group == 'enhanced' else
                    [str(CONTROL/'member3/test_pr_boundaries.py')]
                    if args.group == 'replay' else [str(target/p) for p in required])
                options = ['-c', str(CONTROL/'pytest-review.ini'), '--basetemp', str(out/'tmp/pytest')]
                if args.group != 'enhanced':
                    options += ['-W', 'error']
            code = execute('pytest', [*tests, *options, '-q', '-ra', '--tb=short',
                '-o', 'xfail_strict=true', '-o', 'log_file='+str(out/'logs/pytest.log'),
                '--junitxml', out/'junit.xml'], cwd, 'pytest')
            if (out/'junit.xml').is_file():
                result.update(junit_counts(out/'junit.xml', expected))
        result.update(exit_code=code, status='passed' if code == 0 else 'failed', reason='')
        changed = subprocess.check_output(['git', '-c', 'safe.directory='+target.as_posix(),
            '-C', str(target), 'diff', '--name-only'], text=True).splitlines()
        if changed:
            raise RuntimeError('Tests modified tracked target files: '+', '.join(changed))
        if not green(result):
            result.update(status='failed', reason='Nonzero exit, count drift, skipped/xfail or missing tests')
    except Exception as exc:
        result.update(reason=type(exc).__name__+': '+str(exc), exit_code=1)
        if result['status'] != 'not_executed':
            result['status'] = 'failed'
        print(result['reason'], file=sys.stderr)
    finally:
        result['seconds'] = round(time.monotonic()-start, 3)
        save()
    print(json.dumps({k: result[k] for k in ('group', 'status', 'passed', 'failed', 'skipped', 'not_executed')}, ensure_ascii=False))
    return 0 if green(result) else 1


if __name__ == '__main__':
    raise SystemExit(main())
