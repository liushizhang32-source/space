"""Reviewer-owned boundary checks; never calls a real model or TTS provider."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_independent import settings, story, seed_page
from agents.generation.errors import VideoError, VideoPublishError


def inject_recovery(monkeypatch, story):
    import agents.generation.pipeline as pipeline
    monkeypatch.setattr(pipeline, 'build_page_story', lambda *a, **kw: SimpleNamespace(doc=story, degraded=[]))
    def fail(*a, **kw):
        raise VideoPublishError('MOCK recovery required', detail='MOCK_PRIVATE_BACKUP_PATH')
    monkeypatch.setattr(pipeline, 'compose_video', fail)
    return pipeline


def test_ordinary_video_failure_still_retries(settings, story, monkeypatch):
    import agents.generation.video as video
    seed_page(settings)
    calls = []
    def fail(*a, **kw):
        calls.append(1)
        raise VideoError('MOCK ordinary encode failure')
    monkeypatch.setattr(video, '_render_once', fail)
    with pytest.raises(VideoError):
        video.compose_video('book01_p03', story, settings)
    assert len(calls) == 2


def test_recovery_log_links_public_reference_without_private_detail(settings, story, monkeypatch, caplog):
    pipeline = inject_recovery(monkeypatch, story)
    with caplog.at_level('WARNING'):
        result = pipeline.run_page('book01_p03', '3-6', settings)
    payload = result.to_dict()
    assert result.status == 'partial' and result.video_url is None
    recovery_id = result.video_error['recovery_id']
    assert re.fullmatch(r'rec_[0-9A-HJKMNP-TV-Z]{26}', recovery_id)
    assert 'MOCK_PRIVATE_BACKUP_PATH' not in json.dumps(payload)
    lines = (settings.logs_dir/'book01_p03_publish_errors.jsonl').read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event['recovery_id'] == recovery_id and event['code'] == 3007
    assert event['detail'] == 'MOCK_PRIVATE_BACKUP_PATH' and event['page_id'] == 'book01_p03'
    assert event['event'] == 'video_publish_recovery_required' and event['at']
    assert 'MOCK_PRIVATE_BACKUP_PATH' in caplog.text


def test_log_io_failure_preserves_original_recovery_result(settings, story, monkeypatch, caplog):
    pipeline = inject_recovery(monkeypatch, story)
    real_open = Path.open
    def fail_only_diagnostic_file(path, *args, **kwargs):
        if path.name == 'book01_p03_publish_errors.jsonl':
            raise PermissionError('MOCK diagnostic storage denied')
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', fail_only_diagnostic_file)
    with caplog.at_level('WARNING'):
        result = pipeline.run_page('book01_p03', '3-6', settings)
    assert result.status in {'partial', 'failed'} and result.video_url is None
    assert result.video_error['code'] == 3007
    assert 'MOCK_PRIVATE_BACKUP_PATH' in caplog.text
    assert 'MOCK_PRIVATE_BACKUP_PATH' not in json.dumps(result.to_dict())
