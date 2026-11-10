"""Infrastructure regressions: empty/failed/skipped/partial runs must never go green."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from groups import GROUPS, green, junit_counts


class GateTests(unittest.TestCase):
    def result(self, **updates):
        result = dict(expected=2, passed=2, failed=0, skipped=0,
                      not_executed=0, status='passed', exit_code=0)
        result.update(updates)
        return result

    def test_complete_success(self):
        self.assertTrue(green(self.result()))

    def test_empty_missing_and_partial(self):
        for result in (self.result(passed=0, not_executed=2),
                       self.result(passed=1, not_executed=1),
                       self.result(status='not_executed'), self.result(exit_code=None)):
            self.assertFalse(green(result))

    def test_failure_skip_and_xpass_rejected(self):
        for updates in ({'failed': 1}, {'skipped': 1}, {'exit_code': 1}, {'passed': 3}):
            self.assertFalse(green(self.result(**updates)))

    def test_junit_mixed_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp)/'junit.xml'
            file.write_text('<testsuites><testsuite><testcase/><testcase><failure/></testcase>'
                            '<testcase><error/></testcase><testcase><skipped type="pytest.xfail"/>'
                            '</testcase></testsuite></testsuites>', encoding='utf-8')
            self.assertEqual(junit_counts(file, 5), dict(passed=1, failed=2, skipped=1,
                                                      not_executed=1, executed=4))

    def test_summary_rejects_missing_groups(self):
        script = Path(__file__).resolve().parents[1]/'summarize.py'
        with tempfile.TemporaryDirectory() as tmp:
            p = subprocess.run([sys.executable, '-B', str(script), '--output', tmp], capture_output=True)
            self.assertEqual(p.returncode, 1)
            text = (Path(tmp)/'summary.md').read_text('utf-8')
            self.assertIn('not_executed', text)
            for group in GROUPS:
                self.assertIn('| '+group+' |', text)

    def summary_fixture(self, mixed, dependencies=None):
        script = Path(__file__).resolve().parents[1]/'summarize.py'
        with tempfile.TemporaryDirectory() as tmp:
            for name, (expected, _) in GROUPS.items():
                path = Path(tmp)/name
                path.mkdir()
                result = self.result(group=name, expected=expected, passed=expected,
                                     tested_sha=('b'*40 if mixed and name == 'http' else 'a'*40))
                (path/'result.json').write_text(json.dumps(result), encoding='utf-8')
            env = os.environ.copy()
            env.pop('CI_DEPENDENCY_RESULTS', None)
            if dependencies is not None:
                env['CI_DEPENDENCY_RESULTS'] = json.dumps(dependencies)
            return subprocess.run([sys.executable, '-B', str(script), '--output', tmp],
                                  capture_output=True, env=env).returncode

    def test_summary_complete_same_revision(self):
        self.assertEqual(self.summary_fixture(False), 0)

    def test_summary_rejects_mixed_revisions(self):
        self.assertEqual(self.summary_fixture(True), 1)

    def test_summary_rejects_failed_upstream_despite_passing_tests(self):
        dependencies = {name: {'result': 'success'} for name in ('resolve', 'infrastructure', 'tests')}
        dependencies['infrastructure']['result'] = 'failure'
        self.assertEqual(self.summary_fixture(False, dependencies), 1)


if __name__ == '__main__':
    unittest.main()
