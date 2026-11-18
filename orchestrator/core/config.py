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
    generation_backend: str = field(default_factory=lambda: os.getenv('GENERATION_BACKEND', 'mock'))
    deployment_env: str = field(default_factory=lambda: os.getenv('M1_DEPLOYMENT_ENV', 'local'))
    asset_mode: str = field(default_factory=lambda: os.getenv('M1_ASSET_MODE', 'blocked'))
    ffmpeg_path: str = field(default_factory=lambda: os.getenv('FFMPEG_PATH', 'ffmpeg'))
    ffprobe_path: str = field(default_factory=lambda: os.getenv('FFPROBE_PATH', 'ffprobe'))
    video_font: str = field(default_factory=lambda: os.getenv('VIDEO_FONT',''))
    member3_tts_engine: str = field(default_factory=lambda: os.getenv('M3_TTS_ENGINE', 'silent'))
    member3_tts_http_url: str = field(default_factory=lambda: os.getenv('M3_TTS_HTTP_URL', ''))
    member3_tts_api_key: str = field(default_factory=lambda: os.getenv('M3_TTS_API_KEY', ''), repr=False)
    member3_llm_base_url: str = field(default_factory=lambda: os.getenv('M3_LLM_BASE_URL', ''))
    member3_llm_model: str = field(default_factory=lambda: os.getenv('M3_LLM_MODEL', ''))
    member3_llm_api_key: str = field(default_factory=lambda: os.getenv('M3_LLM_API_KEY', ''), repr=False)
    persist_state: bool = False
    safety_blocklist: tuple[str, ...] = field(default_factory=lambda: tuple(
        term.strip() for term in os.getenv('SAFETY_BLOCKLIST', '').split(',') if term.strip()))

    def __post_init__(self):
        if self.deployment_env not in {'local', 'dev', 'production'}:
            raise ValueError('Invalid deployment environment')
        if self.asset_mode == 'offline_mock' and self.deployment_env != 'local':
            raise ValueError('Offline Mock assets require local isolated deployment')
        if self.asset_mode not in {'blocked', 'offline_mock'}:
            raise ValueError('Invalid asset mode; production asset release is BLOCKED')
        HttpUrl(self.asset_base_url)
        if self.generation_backend not in ('mock', 'member3'):
            raise ValueError('GENERATION_BACKEND must be mock or member3')
        if self.member3_tts_engine not in {'silent','http'}:
            raise ValueError('M3_TTS_ENGINE must explicitly be silent or http')
        if self.member3_tts_engine=='http' and not self.member3_tts_http_url:
            raise ValueError('M3_TTS_HTTP_URL required for http synthesis')
        for endpoint in (self.member3_tts_http_url,self.member3_llm_base_url):
            if endpoint:HttpUrl(endpoint)
        if self.max_concurrent_jobs < 1 or self.queue_delay < 0 or self.stage_delay < 0:
            raise ValueError('Invalid mock timing or concurrency settings')

    def url(self, relative: str) -> str:
        return self.asset_base_url.rstrip('/') + '/' + relative
