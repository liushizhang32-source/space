"""Create fresh silent/template media for the unchanged reviewer assertions."""
import json
import os
from pathlib import Path
import shutil

from agents.generation.config import Settings
from agents.generation.story.builder import build_page_story
from agents.generation.tts.client import TTSClient
from agents.generation.video import compose_video

out = Path(os.environ['CI_RUN_DIR'])
source = Path(os.environ['CI_TARGET'])/'orchestrator/vendor/member3_v116/examples/book01_p03'
settings = Settings.from_env()
assert settings.tts_engine == 'silent' and not settings.llm_api_key and not settings.llm_base_url
settings.ensure_dirs()
for name in ('book01_p03_ocr.json', 'book01_p03_vlm.json'):
    shutil.copyfile(source/name, settings.json_dir/name)
shutil.copyfile(source/'book01_p03_orig.png', settings.uploads_dir/'book01_p03_orig.png')
story = build_page_story('book01_p03', '3-6', settings)
assert story.doc['model']['name'] == 'mock-template'
tts = TTSClient(settings)
tts.synthesize('MOCK 独立音频测试。', fmt='mp3')
tts.synthesize('MOCK 独立音频测试。', fmt='wav')
video = compose_video('book01_p03', story.doc, settings)
assert video.path.is_file()
(out/'fixture-provenance.json').write_text(json.dumps({
    'source': 'fresh mock-template + silent TTS; no author artifacts reused',
    'story': str(settings.json_dir/'book01_p03_story.json'),
    'video': str(video.path)}, ensure_ascii=False, indent=2), encoding='utf-8')
