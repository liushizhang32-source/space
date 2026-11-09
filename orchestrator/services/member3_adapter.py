"""Opt-in v1.1.6 adapter. Visual inputs are fixtures; no external models are configured."""
import hashlib
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from orchestrator.core.errors import APIError
from orchestrator.schemas.ocr import OCRData
from orchestrator.schemas.story import StoryData
from orchestrator.schemas.vlm import VLMData
from orchestrator.vendor.member3_v116.agents.generation.config import Settings as MemberSettings
from orchestrator.vendor.member3_v116.agents.generation.errors import AppError, VideoPublishError
from orchestrator.vendor.member3_v116.agents.generation.media import MediaStatus, validate_audio, validate_video
from orchestrator.vendor.member3_v116.agents.generation.pipeline import record_publish_recovery
from orchestrator.vendor.member3_v116.agents.generation.safety import ensure_story_safe
from orchestrator.vendor.member3_v116.agents.generation.story.builder import build_page_story
from orchestrator.vendor.member3_v116.agents.generation.tts.client import TTSClient
from orchestrator.vendor.member3_v116.agents.generation.tts.engine import estimate_duration_sec
from orchestrator.vendor.member3_v116.agents.generation.video import compose_video

logger = logging.getLogger(__name__)


@dataclass
class Outcome:
    status: str = 'ok'
    degraded: str | None = None
    error: dict | None = None


def fixed_visual(stage, page):
    """Deliberately fixed MOCK content, with IDs/bounds derived from the capture."""
    pid = page['page_id']
    common = {key: page[key] for key in ('book_id', 'page_id', 'page_no', 'image_width', 'image_height')}
    common.update(schema_version='1.0', elapsed_ms=0)
    box = [0, 0, page['image_width'], page['image_height']]
    if stage == 'ocr':
        return dict(common, status='ok', page_confidence=1, text_blocks=[dict(
            block_id=pid+'_t01', order=1, text='MOCK：小兔子在书页里寻找朋友。', bbox=box, confidence=1)])
    return dict(common, status='ok', description='MOCK：书页中的小兔子。',
                objects=[dict(object_id=pid+'_o01', label='小兔子', bbox=box, confidence=1)],
                scene_tags=['MOCK'], safety={'pass': True, 'flags': []})


class DeferredTTS:
    """Use the member builder's safety/normalization, then synthesize in the Jobs TTS stage."""
    def synthesize(self, text):
        return SimpleNamespace(duration_ms=round(estimate_duration_sec(text)*1000),
                               duration_source='estimate', audio_url=None)


class Member3Adapter:
    def __init__(self, storage):
        self.storage = storage
        self.fixture_factory = fixed_visual
        self.client_factory = TTSClient

    def session(self, page_id, job_id):
        return Member3Session(self, page_id, job_id)


class Member3Session:
    def __init__(self, adapter, page_id, job_id):
        self.adapter = adapter
        self.storage = adapter.storage
        self.page_id = page_id
        self.preserve = False
        private = self.storage.root / '.member3'
        private.mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(prefix=job_id+'-', dir=private))
        self.root = workdir
        try:
            config = self.storage.settings
            # Explicit construction never reads .env, LLM_*, TTS_HTTP_URL or credentials.
            self.settings = MemberSettings(data_dir=self.root, asset_base_url=config.asset_base_url,
                ffmpeg_path=config.ffmpeg_path, ffprobe_path=config.ffprobe_path,
                tts_engine='silent', safety_enabled=True, safety_blocklist=config.safety_blocklist,
                max_retry=1, retry_backoff_sec=0, video_timeout_sec=60)
            self.settings.ensure_dirs()
            self.inputs = {}
            self.audio_paths = set()
            self.media_hashes = {}
            self.story = None
            self.video = None
        except BaseException:
            try:
                shutil.rmtree(workdir)
            except Exception:
                logger.exception("member3 initialization cleanup failed: workdir=%s", self.root)
            raise
        self._closed = False

    def check_story(self):
        model = StoryData.model_validate(self.story)
        if not model.safety_pass:
            raise APIError(3004, '故事内容安全拦截')
        ensure_story_safe(self.story, self.settings, stage='Orchestrator 产物检查')
        return model

    def save_story(self):
        model = self.check_story()
        (self.settings.json_dir/f'{self.page_id}_story.json').write_text(
            model.model_dump_json(indent=2), encoding='utf-8')

    def step(self, stage, age_level):
        try:
            return self._step(stage, age_level)
        except ValidationError as exc:
            raise APIError(1002, '成员3输入或产物不符合公共 Schema') from exc
        except AppError as exc:
            raise APIError(int(exc.code), exc.msg) from exc

    def _step(self, stage, age_level):
        if stage == 'ocr':
            with self.storage.lock:
                self.page = self.storage.pages[self.page_id].copy()
                source = self.storage.root/self.page['original']
                if not source.is_file():
                    raise APIError(1003, '原始图片不存在')
                shutil.copy2(source, self.settings.uploads_dir/source.name)
        if stage in ('ocr', 'vlm'):
            cls = OCRData if stage == 'ocr' else VLMData
            model = cls.model_validate(self.adapter.fixture_factory(stage, self.page))
            if model.page_id != self.page_id or (model.image_width, model.image_height) != (
                    self.page['image_width'], self.page['image_height']):
                raise APIError(1002, '视觉测试输入与当前图片不一致')
            if stage == 'vlm' and not model.safety.pass_:
                raise APIError(3004, '画面内容安全拦截')
            self.inputs[stage] = model.model_dump(mode='json', by_alias=True)
            (self.settings.json_dir/f'{self.page_id}_{stage}.json').write_text(
                model.model_dump_json(by_alias=True), encoding='utf-8')
            return Outcome(status=model.status)
        if stage == 'story':
            result = build_page_story(self.page_id, age_level, self.settings, tts_client=DeferredTTS(),
                ocr=self.inputs['ocr'], vlm=self.inputs['vlm'], persist=False)
            self.story = result.doc
            self.save_story()
            # no_audio here is deliberately deferred, not a synthesis failure.
            return Outcome(degraded=next((d for d in result.degraded if d != 'no_audio'), None))
        if stage == 'tts':
            self.check_story()
            client = self.adapter.client_factory(self.settings)
            error = None
            for segment in self.story['segments']:
                try:
                    call = client.synthesize(segment['narration'])
                    path = Path(call.audio_path).resolve()
                    if not path.is_relative_to(self.settings.audios_dir.resolve()):
                        raise APIError(3008, '音频产物路径非法')
                    check = validate_audio(path, self.settings, deep=True)
                    if check.status is not MediaStatus.OK or check.probe is None:
                        raise APIError(3008, '音频产物未通过解码验证')
                    self.audio_paths.add(path)
                    self.media_hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
                    segment.update(duration_sec=round(check.probe.duration_ms/1000, 3),
                        duration_source='tts', audio_url=self.settings.asset_base_url.rstrip('/')+'/audios/'+path.name)
                except (AppError, APIError) as exc:
                    if int(exc.code) == 3004:
                        raise
                    error = {'code': int(exc.code), 'msg': exc.msg}
                    segment.update(duration_sec=round(estimate_duration_sec(segment['narration']), 3),
                                   duration_source='estimate')
                    segment.pop('audio_url', None)
            self.story['total_duration_sec'] = round(sum(s['duration_sec'] for s in self.story['segments']), 3)
            self.save_story()
            return Outcome('failed', 'no_audio', error) if error else Outcome()
        if stage == 'render':
            self.check_story()
            try:
                result = compose_video(self.page_id, self.story, self.settings)
                path = self.settings.videos_dir/f'{self.page_id}_video.mp4'
                check = validate_video(path, self.settings, deep=True)
                probe = check.probe
                if check.status is not MediaStatus.OK or probe is None or not probe.has_audio:
                    raise APIError(3007, '视频产物未通过解码验证')
                if (probe.width, probe.height, probe.fps) != (self.settings.video_width,
                        self.settings.video_height, self.settings.video_fps) or abs(
                        probe.duration_ms/1000-result.doc['duration_sec']) > 0.2:
                    raise APIError(3007, '视频产物元数据不一致')
                self.video = result.doc
                self.media_hashes[path.resolve()] = hashlib.sha256(path.read_bytes()).hexdigest()
                return Outcome()
            except (AppError, APIError) as exc:
                if int(exc.code) == 3004:
                    raise
                if isinstance(exc, VideoPublishError):
                    self.preserve = True
                    record_publish_recovery(self.settings.replace(data_dir=self.storage.root), self.page_id, exc)
                return Outcome('failed', 'no_video', {'code': int(exc.code), 'msg': exc.msg})
        raise ValueError(stage)

    def publish(self):
        """Called on the event loop only after worker success/cancellation checks.

        Atomic per file; URLs are exposed only after every selected file is copied.
        This is not a cross-file transaction or a multi-process writer guarantee.
        """
        self.check_story()
        files = [self.settings.json_dir/f'{self.page_id}_{kind}.json' for kind in ('ocr', 'vlm', 'story')]
        files.extend(self.audio_paths)
        if self.video:
            files.extend([self.settings.json_dir/f'{self.page_id}_video.json',
                          self.settings.videos_dir/f'{self.page_id}_video.mp4'])
        # Preflight all media before publishing any file. A previously verified
        # file disappearing/changing must never turn into a dangling public URL.
        for source, expected in self.media_hashes.items():
            code = 3008 if source.parent.name == 'audios' else 3007
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                raise APIError(code, '已验证媒体在发布前丢失或变更')
        for source in files:
            target = self.storage.root/source.relative_to(self.root)
            fd, name = tempfile.mkstemp(prefix='.publish-', dir=target.parent)
            os.close(fd)
            try:
                shutil.copyfile(source, name)
                expected = self.media_hashes.get(source.resolve())
                if expected and hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected:
                    raise APIError(3008 if source.parent.name == 'audios' else 3007,
                                   '媒体发布副本完整性校验失败')
                os.replace(name, target)
            finally:
                Path(name).unlink(missing_ok=True)
        return (self.storage.settings.url(f'json/{self.page_id}_story.json'),
                self.video['video_url'] if self.video else None)

    def close(self):
        if not self.preserve and not self._closed:
            shutil.rmtree(self.root)
            self._closed = True
