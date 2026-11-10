"""Reviewer-owned checks for write-stage OSError, beyond the open/mkdir tests."""
import json
from pathlib import Path

import pytest

from test_independent import settings, story
from test_v115_boundary import inject_recovery


@pytest.mark.parametrize('fail_fallback', [False, True], ids=['primary-write-fails', 'all-writes-fail'])
def test_write_failure_preserves_recovery_result(settings, story, monkeypatch, caplog, fail_fallback):
    pipeline = inject_recovery(monkeypatch, story)
    real_open = Path.open
    primary = 'book01_p03_publish_errors.jsonl'
    fallback = 'publish_errors_fallback.jsonl'
    attempted = []

    class FailingWriter:
        def __init__(self, handle, name):
            self.handle = handle
            self.name = name

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def write(self, data):
            attempted.append(self.name)
            raise OSError(28, 'MOCK storage full while writing recovery event')

    def open_with_write_failure(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get('mode', 'r')
        if mode == 'a' and (path.name == primary or (fail_fallback and path.name == fallback)):
            return FailingWriter(handle, path.name)
        return handle

    monkeypatch.setattr(Path, 'open', open_with_write_failure)
    with caplog.at_level('WARNING'):
        result = pipeline.run_page('book01_p03', '3-6', settings)
    assert result.status == 'partial' and result.video_url is None
    assert result.video_error['code'] == 3007
    recovery_id = result.video_error['recovery_id']
    assert recovery_id and primary in attempted
    assert 'MOCK_PRIVATE_BACKUP_PATH' not in json.dumps(result.to_dict())
    assert 'MOCK_PRIVATE_BACKUP_PATH' in caplog.text and recovery_id in caplog.text
    if fail_fallback:
        assert fallback in attempted
        assert '恢复信息未能持久化' in caplog.text
    else:
        event = json.loads((settings.logs_dir/fallback).read_text(encoding='utf-8').splitlines()[-1])
        assert event['recovery_id'] == recovery_id and event['detail'] == 'MOCK_PRIVATE_BACKUP_PATH'
