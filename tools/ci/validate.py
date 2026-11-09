"""Parse workflow YAML, assert gate invariants, AST and whitespace-check CI files."""
import ast
from pathlib import Path
import re
import subprocess

import yaml

from groups import GROUPS

ROOT = Path(__file__).resolve().parents[2]


def validate():
    path = ROOT/'.github/workflows/paperbook-ci.yml'
    workflow = yaml.load(path.read_text('utf-8'), Loader=yaml.BaseLoader)
    triggers = workflow['on']
    assert set(triggers) == {'pull_request', 'push', 'workflow_dispatch'}
    assert set(triggers['pull_request']['branches']) == {'main', 'dev'}
    assert set(triggers['push']['branches']) == {'main', 'dev'}
    assert 'test_ref' in triggers['workflow_dispatch']['inputs']
    assert workflow['permissions'] == {'contents': 'read'}
    jobs = workflow['jobs']
    assert set(jobs) == {'resolve', 'infrastructure', 'tests', 'summary'}
    assert set(jobs['summary']['needs']) == {'resolve', 'infrastructure', 'tests'}
    matrix = jobs['tests']['strategy']['matrix']['include']
    assert [m['group'] for m in matrix] == list(GROUPS)
    assert jobs['tests']['needs'] == 'resolve'
    for job in jobs.values():
        assert job['runs-on'] == 'ubuntu-latest'
        assert 1 <= int(job['timeout-minutes']) <= 20
        assert 'continue-on-error' not in job
        for step in job['steps']:
            assert 'continue-on-error' not in step
            if 'uses' in step:
                assert re.fullmatch(r'actions/[a-z-]+@[0-9a-f]{40}', step['uses'])
            assert 'secrets.' not in str(step)
    assert 'pull_request_target' not in path.read_text('utf-8')
    for file in (ROOT/'tools/ci').rglob('*'):
        if file.is_file() and file.suffix in ('.py', '.ini', '.txt', '.md', '.json'):
            data = file.read_text('utf-8-sig')
            assert all(line == line.rstrip(' \t') for line in data.splitlines()), str(file)
            if file.suffix == '.py':
                ast.parse(data, filename=str(file))
    subprocess.run(['git', '-c', 'safe.directory='+ROOT.as_posix(), '-C', str(ROOT),
                    'diff', '--check'], check=True)
    print('YAML parsed; triggers, eight groups, dependencies, permissions, SHA pins, AST and diff checks passed')


if __name__ == '__main__':
    validate()
