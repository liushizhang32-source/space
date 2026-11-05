import os
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import HttpUrl


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv('DATA_DIR', './data')))
    asset_base_url: str = field(default_factory=lambda: os.getenv('ASSET_BASE_URL', 'http://127.0.0.1:8000'))
    max_concurrent_jobs: int = field(default_factory=lambda: int(os.getenv('MAX_CONCURRENT_JOBS', '3')))
    queue_delay: float = 0.2
    stage_delay: float = 0.3

    def __post_init__(self):
        HttpUrl(self.asset_base_url)
        if self.max_concurrent_jobs < 1 or self.queue_delay < 0 or self.stage_delay < 0:
            raise ValueError('Invalid mock timing or concurrency settings')

    def url(self, relative: str) -> str:
        return self.asset_base_url.rstrip('/') + '/' + relative
