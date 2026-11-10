import argparse
import json
import os
from pathlib import Path

from groups import GROUPS, green


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--require-evidence', action='store_true')
    parser.add_argument('--sha')
    args = parser.parse_args()
    lines = ['# Paperbook CI test groups', '',
             '| Group | Baseline | Passed | Failed | Skipped | Not executed | Status |',
             '|---|---:|---:|---:|---:|---:|---|']
    all_green = True
    report_errors = []
    tested_revisions = set()
    if os.environ.get('CI_DEPENDENCY_RESULTS'):
        dependencies = json.loads(os.environ['CI_DEPENDENCY_RESULTS'])
        all_green = (set(dependencies) == {'resolve', 'infrastructure', 'tests'}
                     and all(d.get('result') == 'success' for d in dependencies.values()))
    for name, (expected, _) in GROUPS.items():
        evidence_error = None
        if args.require_evidence:
            from reports import validate
            try:
                if not args.sha:
                    raise ValueError('Expected current test SHA is required')
                validate(args.output/name, name, args.sha)
            except Exception as exc:
                print(f'ERROR: {name}: {exc}')
                evidence_error = str(exc)
                report_errors.append(f'ERROR: {name}: {exc}')
                all_green = False
        path = args.output/name/'result.json'
        try:
            result = json.loads(path.read_text('utf-8')) if path.is_file() else None
            if not isinstance(result, dict) or not all(k in result for k in
                    ('group', 'expected', 'passed', 'failed', 'skipped', 'not_executed', 'status', 'exit_code')):
                raise ValueError('Missing or malformed result: '+str(path))
        except (ValueError, OSError) as exc:
            print(f'ERROR: {exc}')
            all_green = False
            result = dict(
            group=name, expected=expected, passed=0, failed=0, skipped=0,
            not_executed=expected, status='not_executed', exit_code=None)
        if evidence_error:
            result['status'] = 'invalid_evidence'
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
    lines += report_errors
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
