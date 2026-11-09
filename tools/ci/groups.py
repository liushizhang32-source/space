"""Audited test inventory, not a promise of remote execution results."""
GROUPS = {
    'schema': (409, ['orchestrator/tests/test_schema_contract.py',
                     'orchestrator/tests/test_schema_round2.py']),
    'api': (42, ['orchestrator/tests/test_mock_api.py']),
    'member134': (134, ['orchestrator/vendor/member3_v116/tests']),
    'enhanced': (12, ['orchestrator/vendor/member3_v116/agents/generation',
                      'orchestrator/vendor/member3_v116/examples/book01_p03']),
    'integration': (21, ['orchestrator/tests/test_member3_integration.py']),
    'lifecycle': (10, ['orchestrator/tests/test_member3_lifecycle.py']),
    'replay': (2, ['orchestrator/services/member3_jobs.py',
                   'orchestrator/services/member3_adapter.py']),
    'http': (12, ['orchestrator/main.py', 'orchestrator/services/member3_jobs.py',
                  'orchestrator/vendor/member3_v116/examples/book01_p03/book01_p03_orig.png']),
}
MEDIA = {'member134', 'enhanced', 'integration', 'http'}


def junit_counts(path, expected):
    """Failures include errors; xfail is skipped and is rejected by the gate."""
    from xml.etree import ElementTree
    root = ElementTree.parse(path).getroot()
    cases = list(root.iter('testcase'))
    failed = sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
    skipped = sum(c.find('skipped') is not None for c in cases)
    return dict(passed=len(cases)-failed-skipped, failed=failed, skipped=skipped,
                not_executed=max(0, expected-len(cases)), executed=len(cases))


def green(result):
    return (result.get('status') == 'passed' and result.get('exit_code') == 0
            and result.get('passed') == result['expected']
            and all(result.get(k) == 0 for k in ('failed', 'skipped', 'not_executed')))
