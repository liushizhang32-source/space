"""Validate current-run evidence and stage only explicitly allowed reports."""
import argparse
import json
from pathlib import Path
import re

from groups import GROUPS, green, junit_counts


def required(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise ValueError(f'Missing, empty or unsafe report: {path}')
    data = path.read_bytes()
    if re.search(rb'gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----', data):
        raise ValueError(f'Possible credential in report: {path}')
    return data


def read_json(path):
    try:
        return json.loads(required(path))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f'Invalid report {path}: {exc}') from exc


def validate(directory, group, sha):
    result = read_json(directory/'result.json')
    expected = GROUPS[group][0]
    if (result.get('group') != group or result.get('expected') != expected
            or not green(result) or result.get('tested_sha') != sha):
        raise ValueError(f'Invalid, failed or stale group report: {directory}/result.json')
    evidence = directory/('http-integration-results.json' if group == 'http' else 'junit.xml')
    required(evidence)
    if group == 'http':
        data = read_json(evidence)
        if (data['passed'] != result['passed'] or data['failed'] != 0
                or data['server_exit'] != 0 or data['port_closed'] is not True):
            raise ValueError(f'HTTP evidence disagrees with result: {evidence}')
    else:
        counts = junit_counts(evidence, expected)
        if any(counts[k] != result[k] for k in ('passed', 'failed', 'skipped', 'not_executed')):
            raise ValueError(f'JUnit evidence disagrees with result: {evidence}')
    return result


def stage(output, group, sha):
    directory = output/group
    result = read_json(directory/'result.json')
    attempt = Path(result['run_dir']).resolve()
    if attempt.parent != directory.resolve() or not attempt.name.startswith('attempt-'):
        raise ValueError(f'Attempt outside current group: {attempt}')
    if read_json(attempt/'result.json') != result:
        raise ValueError(f'Current attempt and group result disagree: {attempt}')
    validate(attempt, group, sha)
    destination = output/'.upload'/group
    destination.mkdir(parents=True, exist_ok=False)
    for name in ('result.json', 'http-integration-results.json' if group == 'http' else 'junit.xml'):
        (destination/name).write_bytes(required(attempt/name))
    validate(destination, group, sha)
    print(f'Validated current reports for {group}: {destination}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--group', choices=GROUPS, required=True)
    parser.add_argument('--sha', required=True)
    args = parser.parse_args()
    stage(args.output.resolve(), args.group, args.sha)
