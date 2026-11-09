import argparse
import json
import os
from pathlib import Path

from groups import GROUPS, green


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    lines = ['# Paperbook CI test groups', '',
             '| Group | Baseline | Passed | Failed | Skipped | Not executed | Status |',
             '|---|---:|---:|---:|---:|---:|---|']
    all_green = True
    tested_revisions = set()
    if os.environ.get('CI_DEPENDENCY_RESULTS'):
        dependencies = json.loads(os.environ['CI_DEPENDENCY_RESULTS'])
        all_green = (set(dependencies) == {'resolve', 'infrastructure', 'tests'}
                     and all(d.get('result') == 'success' for d in dependencies.values()))
    for name, (expected, _) in GROUPS.items():
        path = args.output/name/'result.json'
        result = json.loads(path.read_text('utf-8')) if path.is_file() else dict(
            group=name, expected=expected, passed=0, failed=0, skipped=0,
            not_executed=expected, status='not_executed', exit_code=None)
        if result.get('group') != name or result.get('expected') != expected:
            all_green = False
        all_green = green(result) and all_green
        if result.get('tested_sha'):
            tested_revisions.add(result['tested_sha'])
        elif green(result):
            all_green = False
        lines.append('| '+' | '.join(str(result[k]) for k in
            ('group', 'expected', 'passed', 'failed', 'skipped', 'not_executed', 'status'))+' |')
    lines += ['', 'Groups are reported separately; overlapping checks are not added into a unique total.',
              'Missing results, count drift, skip/xfail and failures prevent a green gate.']
    if os.environ.get('CI_DEPENDENCY_RESULTS') and not all(
            d.get('result') == 'success' for d in dependencies.values()):
        lines.append('ERROR: a required upstream job failed, was cancelled or did not execute.')
    if len(tested_revisions) != 1:
        all_green = False
        lines.append('ERROR: all eight groups must report the same resolved test SHA.')
    else:
        lines.append('Tested SHA: `'+next(iter(tested_revisions))+'`')
    text = '\n'.join(lines)+'\n'
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'summary.md').write_text(text, encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as handle:
            handle.write(text)
    print(text)
    return 0 if all_green else 1


if __name__ == '__main__':
    raise SystemExit(main())
