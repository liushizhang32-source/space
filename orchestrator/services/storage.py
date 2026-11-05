import hashlib
import io
import json
import secrets
import shutil
import threading
import warnings
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from orchestrator.core.config import Settings
from orchestrator.core.errors import APIError
from orchestrator.schemas.capture import CaptureData
from orchestrator.schemas.ocr import OCRData
from orchestrator.schemas.story import StoryData
from orchestrator.schemas.vlm import VLMData

MAX_IMAGE_BYTES = 10 * 1024 * 1024
FORMATS = {'JPEG': ('jpg', {'jpg', 'jpeg'}, 'image/jpeg'),
           'PNG': ('png', {'png'}, 'image/png'),
           'WEBP': ('webp', {'webp'}, 'image/webp')}
ASSETS = Path(__file__).resolve().parents[1] / 'assets'


class Storage:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.data_dir
        self.pages: dict[str, dict] = {}
        self.lock = threading.RLock()
        for folder in ('uploads', 'previews', 'json', 'audios', 'videos', 'logs'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)

    def capture(self, content: bytes, filename: str, content_type: str,
                page_no: int, book_id: str | None) -> CaptureData:
        if len(content) > MAX_IMAGE_BYTES:
            raise APIError(1004, '图片超过 10MB')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    fmt = FORMATS.get(image.format)
                    if not fmt or Path(filename).suffix.lower().lstrip('.') not in fmt[1] or content_type != fmt[2]:
                        raise APIError(1006, '仅支持匹配内容的 jpg/png/webp 图片')
                    width, height = image.size
                    if max(width, height) > 4096:
                        raise APIError(1002, '图片长边不得超过 4096')
                    image.verify()
                with Image.open(io.BytesIO(content)) as image:
                    preview = image.convert('RGB')
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as exc:
            raise APIError(1006, '图片内容损坏或无法解码') from exc
        with self.lock:
            book_id = book_id or ('b' + secrets.token_hex(5))
            page_id = f'{book_id}_p{page_no:02d}'
            original = f'uploads/{page_id}_orig.{fmt[0]}'
            preview_path = f'previews/{page_id}_preview.jpg'
            result = CaptureData(book_id=book_id, page_id=page_id, page_no=page_no,
                                 preview_url=self.settings.url(preview_path),
                                 image_width=width, image_height=height)
            (self.root / original).write_bytes(content)
            preview.thumbnail((1024, 1024))
            preview.save(self.root / preview_path, format='JPEG')
            self.pages[page_id] = dict(book_id=book_id, page_id=page_id, page_no=page_no,
                                       image_width=width, image_height=height,
                                       original=original, preview=preview_path)
            return result

    def write_model(self, page_id: str, kind: str, model: BaseModel):
        path = self.root / f'json/{page_id}_{kind}.json'
        path.write_text(model.model_dump_json(by_alias=True, indent=2), encoding='utf-8')

    def produce(self, page_id: str, stage: str, age_level: str):
        page = self.pages[page_id]
        common = {k: page[k] for k in ('book_id', 'page_id', 'page_no')}
        visual = dict(common, schema_version='1.0', elapsed_ms=0,
                      image_width=page['image_width'], image_height=page['image_height'])
        if stage == 'ocr':
            self.write_model(page_id, 'ocr', OCRData(**visual, status='empty', page_confidence=0))
        elif stage == 'vlm':
            self.write_model(page_id, 'vlm', VLMData(**visual, status='empty',
                             description='MOCK：未调用视觉模型', safety={'pass': True, 'flags': []}))
        elif stage == 'story':
            story = StoryData(**common, schema_version='1.0', title='MOCK 联调故事',
                age_level=age_level, status='ok', total_duration_sec=1, safety_pass=True,
                model={'name': 'mock', 'version': '1.0'}, elapsed_ms=0,
                segments=[dict(segment_id=page_id+'_s01', order=1,
                    narration='这是用于接口联调的模拟故事。', scene='MOCK 测试画面',
                    duration_sec=1, duration_source='estimate')])
            self.write_model(page_id, 'story', story)
        elif stage == 'tts':
            # A real silent fixture, not synthesized narration or a model call.
            path = self.root / f'json/{page_id}_story.json'
            data = json.loads(path.read_text(encoding='utf-8'))
            key = data['segments'][0]['narration'] + 'mock_silence' + '1.0'
            audio = 'audios/tts_' + hashlib.sha1(key.encode()).hexdigest()[:12] + '.mp3'
            shutil.copyfile(ASSETS / 'mock.mp3', self.root / audio)
            data['segments'][0].update(duration_source='tts', audio_url=self.settings.url(audio))
            self.write_model(page_id, 'story', StoryData.model_validate(data))
        elif stage == 'render':
            relative = f'videos/{page_id}_video.mp4'
            shutil.copyfile(ASSETS / 'mock.mp4', self.root / relative)
            data = dict(common, schema_version='1.0', status='ok',
                        video_url=self.settings.url(relative), duration_sec=1,
                        resolution='320x240', fps=25, elapsed_ms=0,
                        segments=[dict(segment_id=page_id+'_s01', start_sec=0, end_sec=1)])
            (self.root / f'json/{page_id}_video.json').write_text(
                json.dumps(data, ensure_ascii=False), encoding='utf-8')
