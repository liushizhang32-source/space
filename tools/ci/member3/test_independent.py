import json,os,socket,threading,subprocess
from pathlib import Path
import pytest
from agents.generation.config import Settings
from agents.generation.errors import VideoPublishError
from agents.generation.storage import PageFiles
from agents.generation.media import validate_audio,validate_video,MediaStatus
from agents.generation.video import compose_video,_publish_pair
from orchestrator.schemas.story import StoryData
ROOT=Path(os.environ['CI_RUN_DIR'])
VENDOR=Path(os.environ['CI_TARGET'])/'orchestrator/vendor/member3_v116'
@pytest.fixture
def settings(tmp_path):
 s=Settings(data_dir=tmp_path/'data',asset_base_url='http://127.0.0.1:8001',ffmpeg_path=os.environ['FFMPEG_PATH'],ffprobe_path=os.environ['FFPROBE_PATH'],tts_engine='silent',max_retry=1,retry_backoff_sec=0)
 s.ensure_dirs();return s
@pytest.fixture
def story():return json.loads((ROOT/'data/json/book01_p03_story.json').read_text('utf-8'))
def seed_page(settings):
 p=settings.uploads_dir/'book01_p03_orig.png';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((VENDOR/'examples/book01_p03/book01_p03_orig.png').read_bytes())
def test_actual_story_matches_current_public_model(story):
 model=StoryData.model_validate(story);assert model.model.name=='mock-template';assert all(s.scene and s.highlight_object_ids is not None for s in model.segments)
def test_new_media_decodes_and_matches_declared_metadata(settings):
 for p in (ROOT/'data/audios').iterdir():
  check=validate_audio(p,settings,deep=True);assert check.status is MediaStatus.OK;assert check.probe.sample_rate==24000
 p=ROOT/'data/videos/book01_p03_video.mp4';check=validate_video(p,settings,deep=True);assert check.status is MediaStatus.OK
 doc=json.loads((ROOT/'data/json/book01_p03_video.json').read_text('utf-8'));v=check.probe
 assert v.has_audio and (v.width,v.height)==(720,1280) and v.fps==25
 assert abs(v.duration_ms/1000-doc['duration_sec'])<=0.2
 details={'probe':v.__dict__,'declared':doc};(ROOT/'logs/media_verified.json').write_text(json.dumps(details,ensure_ascii=False,indent=2),encoding='utf-8')
def test_missing_ffmpeg_is_unavailable(settings):
 s=settings.replace(ffmpeg_path=str(ROOT/'does-not-exist.exe'))
 p=next((ROOT/'data/audios').glob('*.mp3'));assert validate_audio(p,s,deep=True).status is MediaStatus.UNAVAILABLE
def test_recovery_required_error_stops_automatic_retry(settings,story,monkeypatch):
 import agents.generation.video as video
 seed_page(settings);calls=[]
 def fail(*a,**k):calls.append(1);raise VideoPublishError('需要人工恢复',detail='backups=MOCK_RECOVERY_BACKUP')
 monkeypatch.setattr(video,'_render_once',fail)
 with pytest.raises(VideoPublishError):compose_video('book01_p03',story,settings)
 assert len(calls)==1,'Recovery-required errors should stop instead of retrying over unresolved recovery state'
def test_pipeline_records_recovery_diagnostics(settings,story,monkeypatch,caplog):
 from types import SimpleNamespace
 import agents.generation.pipeline as pipeline
 monkeypatch.setattr(pipeline,'build_page_story',lambda *a,**k:SimpleNamespace(doc=story,degraded=[]))
 def fail(*a,**k):raise VideoPublishError('需要人工恢复',detail='MOCK_RECOVERY_BACKUP_PATH')
 monkeypatch.setattr(pipeline,'compose_video',fail)
 with caplog.at_level('WARNING'):result=pipeline.run_page('book01_p03','3-6',settings)
 assert result.video_error['code']==3007
 assert 'MOCK_RECOVERY_BACKUP_PATH' in caplog.text,'Pipeline must retain recovery details in internal diagnostics, without exposing local paths in public responses'
def test_rollback_lock_order_and_threads_join(settings,monkeypatch):
 import agents.generation.video as video
 files=PageFiles(settings,'book01_p03');files.video.write_bytes(b'OLD');files.video_json.write_text('{"v":"OLD"}',encoding='utf-8')
 a=settings.tmp_dir/'a.mp4';b=settings.tmp_dir/'b.mp4';a.write_bytes(b'AAA');b.write_bytes(b'BBB')
 rollback_waiting=threading.Event();allow_rollback=threading.Event();b_attempt=threading.Event();b_entered=threading.Event();errors={}
 real_lock=video._page_lock;real_replace=video.os.replace
 class ObservedLock:
  def __init__(self,pid):self.lock=real_lock(pid)
  def __enter__(self):
   if threading.current_thread().name=='B':b_attempt.set()
   self.lock.acquire()
   if threading.current_thread().name=='B':b_entered.set()
  def __exit__(self,*args):self.lock.release()
 monkeypatch.setattr(video,'_page_lock',ObservedLock)
 def replace(src,dst):
  if threading.current_thread().name=='A':
   if Path(dst)==files.video_json and '.tmp.' in Path(src).name:raise PermissionError('MOCK commit failure')
   if Path(dst)==files.video and '.bak.' in Path(src).name:
    rollback_waiting.set();assert allow_rollback.wait(10)
  return real_replace(src,dst)
 monkeypatch.setattr(video.os,'replace',replace)
 def publish(name,path):
  try:_publish_pair(path,{'v':name},files)
  except Exception as e:errors[name]=e
 ta=threading.Thread(target=publish,args=('A',a),name='A');tb=threading.Thread(target=publish,args=('B',b),name='B')
 ta.start()
 try:
  assert rollback_waiting.wait(10);tb.start();assert b_attempt.wait(10);assert not b_entered.is_set()
 finally:
  allow_rollback.set();ta.join(15)
  if tb.ident is not None:tb.join(15)
 assert not ta.is_alive() and not tb.is_alive();assert isinstance(errors.get('A'),PermissionError) and 'B' not in errors
 assert files.video.read_bytes()==b'BBB' and json.loads(files.video_json.read_text('utf-8'))['v']=='B'
def test_network_and_real_model_protection():
 with pytest.raises(PermissionError):socket.create_connection(('198.51.100.1',443),timeout=.01)
 with pytest.raises(ImportError):__import__('openai')
