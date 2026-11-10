"""Synthetic unit fixtures for report transport; never substitute for suite results."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from groups import GROUPS
from reports import stage, validate

SHA = 'a'*40


def fixture(root, group):
    expected = GROUPS[group][0]
    attempt = root/group/'attempt-unit'
    attempt.mkdir(parents=True)
    result = dict(group=group, expected=expected, passed=expected, failed=0,
                  skipped=0, not_executed=0, exit_code=0, status='passed',
                  tested_sha=SHA, run_dir=str(attempt))
    for path in (root/group/'result.json', attempt/'result.json'):
        path.write_text(json.dumps(result), 'utf-8')
    if group == 'http':
        (attempt/'http-integration-results.json').write_text(json.dumps(dict(
            passed=12, failed=0, server_exit=0, port_closed=True)), 'utf-8')
    else:
        (attempt/'junit.xml').write_text('<testsuite>'+'<testcase/>'*expected+'</testsuite>', 'utf-8')
    return attempt


class ArtifactTests(unittest.TestCase):
    def test_hidden_stage_whitelist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'.ci-results'
            attempt = fixture(root, 'schema')
            (attempt/'.env').write_text('SYNTHETIC MUST NOT UPLOAD', 'utf-8')
            (attempt/'runtime.log').write_text('SYNTHETIC MUST NOT UPLOAD', 'utf-8')
            stage(root, 'schema', SHA)
            payload = root/'.upload/schema'
            self.assertEqual({p.name for p in payload.iterdir()}, {'result.json', 'junit.xml'})
            self.assertEqual(validate(payload, 'schema', SHA)['passed'], 409)

    def test_missing_empty_malformed_result(self):
        for value in (None, '', '{bad'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                fixture(root, 'schema')
                path = root/'schema/result.json'
                if value is None:
                    path.unlink()
                else:
                    path.write_text(value, 'utf-8')
                with self.assertRaisesRegex(ValueError, 'result.json'):
                    stage(root, 'schema', SHA)

    def test_missing_empty_malformed_junit(self):
        for value in (None, '', '<broken'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                attempt = fixture(root, 'schema')
                path = attempt/'junit.xml'
                if value is None:
                    path.unlink()
                else:
                    path.write_text(value, 'utf-8')
                with self.assertRaises(Exception):
                    stage(root, 'schema', SHA)

    def test_stale_sha_and_count_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            attempt = fixture(root, 'schema')
            with self.assertRaisesRegex(ValueError, 'stale'):
                stage(root, 'schema', 'b'*40)
            (attempt/'junit.xml').write_text('<testsuite><testcase/></testsuite>', 'utf-8')
            with self.assertRaisesRegex(ValueError, 'disagrees'):
                stage(root, 'schema', SHA)

    def test_attempt_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            attempt = fixture(root, 'schema')
            (attempt/'result.json').write_text('{}', 'utf-8')
            with self.assertRaisesRegex(ValueError, 'disagree'):
                stage(root, 'schema', SHA)

    def test_http_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            attempt = fixture(root, 'http')
            stage(root, 'http', SHA)
            (attempt/'http-integration-results.json').write_text(json.dumps(dict(
                passed=12, failed=0, server_exit=0, port_closed=False)), 'utf-8')
            with self.assertRaisesRegex(ValueError, 'HTTP'):
                validate(attempt, 'http', SHA)

    def test_summary_roundtrip_and_missing_report(self):
        script = Path(__file__).resolve().parents[1]/'summarize.py'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in GROUPS:
                fixture(root, name)
                stage(root, name, SHA)
            command = [sys.executable, '-B', str(script), '--output', str(root/'.upload'),
                       '--require-evidence', '--sha', SHA]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            (root/'.upload/schema/junit.xml').unlink()
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('junit.xml', result.stdout)
            self.assertIn('invalid_evidence', (root/'.upload/summary.md').read_text('utf-8'))

    def test_empty_summary_result_fails(self):
        script = Path(__file__).resolve().parents[1]/'summarize.py'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in GROUPS:
                fixture(root, name)
                stage(root, name, SHA)
            (root/'.upload/api/result.json').write_text('', 'utf-8')
            result = subprocess.run([sys.executable, '-B', str(script), '--output', str(root/'.upload'),
                                     '--require-evidence', '--sha', SHA], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('result.json', result.stdout)
