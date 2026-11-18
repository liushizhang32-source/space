"""Real local image/OCR/media tools; no substitute model outputs in this module."""
import array,io,json,math,os,shutil,subprocess,sys,tempfile,time
from contextlib import contextmanager
from pathlib import Path
from PIL import Image,ImageOps
from .errors import IntegrationError,Cancelled
from .jsonutil import loads

MAX_FILE=20*1024*1024
MAX_PIXELS=24_000_000
@contextmanager
def media_workspace(root,*,prefix='paperbook-media-'):
    from ..vision_supervisor.tree import ContainmentError
    root=Path(root).resolve();work=Path(tempfile.mkdtemp(prefix=prefix,dir=root));drained=True
    try:yield work
    except ContainmentError:
        drained=False;raise
    finally:
        if drained and work.resolve().parent==root and work.name.startswith(prefix):shutil.rmtree(work)

def rectify_image(image):
    """Correct a clearly detected photographed page, preserve other artwork.

    Output is the canonical Capture image: preview, SHA, OCR/VLM coordinates and
    Wan all use these same pixels. EXIF orientation is normalized beforehand.
    """
    import cv2,numpy as np
    pixels=np.asarray(image);gray=cv2.cvtColor(pixels,cv2.COLOR_RGB2GRAY)
    edges=cv2.Canny(cv2.GaussianBlur(gray,(5,5),0),50,150)
    contours,_=cv2.findContours(edges,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    area=image.width*image.height
    for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:5]:
        ratio=cv2.contourArea(contour)/area
        if not .55<ratio<.98:continue
        polygon=cv2.approxPolyDP(contour,.02*cv2.arcLength(contour,True),True)
        if len(polygon)!=4 or not cv2.isContourConvex(polygon):continue
        pts=polygon.reshape(4,2).astype(np.float32)
        sums=pts.sum(axis=1);diff=np.diff(pts,axis=1).ravel()
        ordered=np.array([pts[sums.argmin()],pts[diff.argmin()],pts[sums.argmax()],pts[diff.argmax()]],np.float32)
        if len({tuple(p) for p in ordered})!=4:continue
        tl,tr,br,bl=ordered
        width=round(max(np.linalg.norm(tr-tl),np.linalg.norm(br-bl)))
        height=round(max(np.linalg.norm(bl-tl),np.linalg.norm(br-tr)))
        if min(width,height)<240:continue
        matrix=cv2.getPerspectiveTransform(ordered,np.array([[0,0],[width-1,0],[width-1,height-1],[0,height-1]],np.float32))
        corrected=cv2.warpPerspective(pixels,matrix,(width,height),borderValue=(255,255,255))
        return Image.fromarray(corrected),True
    return image,False

def normalize_image(raw):
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {'JPEG','PNG'} or source.width*source.height>MAX_PIXELS:raise ValueError()
            source.load();im=ImageOps.exif_transpose(source).convert('RGB')
            im.thumbnail((2048,2048))
            im,_=rectify_image(im)
            if min(im.size)<240:im=ImageOps.pad(im,(max(240,im.width),max(240,im.height)),color='white')
            out=io.BytesIO();im.save(out,format='JPEG',quality=94)
            return out.getvalue(),im.width,im.height
    except (OSError,ValueError,Image.DecompressionBombError):raise IntegrationError('IMAGE_INVALID') from None

def parse_upload(raw,filename):
    if len(raw)>MAX_FILE:raise IntegrationError('UPLOAD_FILE_TOO_LARGE')
    if filename.lower().endswith(('.heic','.heif')):
        try:
            from pillow_heif import open_heif
            heif=open_heif(raw)
            if heif.size[0]*heif.size[1]>MAX_PIXELS:raise ValueError()
            im=Image.frombytes(heif.mode,heif.size,heif.data,'raw',heif.mode,heif.stride).convert('RGB')
            out=io.BytesIO();im.save(out,format='PNG');return [normalize_image(out.getvalue())]
        except Exception:raise IntegrationError('HEIC_INVALID') from None
    if filename.lower().endswith('.pdf'):
        import pymupdf
        result=[]
        try:
            with pymupdf.open(stream=raw,filetype='pdf') as doc:
                if doc.is_encrypted or not 1<=len(doc)<=30:raise ValueError()
                for page in doc:
                    scale=min(2,2048/max(page.rect.width,page.rect.height))
                    if page.rect.width*page.rect.height*scale*scale>MAX_PIXELS:raise ValueError()
                    pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False)
                    result.append(normalize_image(pix.tobytes('png')))
        except Exception:raise IntegrationError('PDF_INVALID_OR_LIMIT') from None
        return result
    if not filename.lower().endswith(('.jpg','.jpeg','.png')):raise IntegrationError('UPLOAD_TYPE_UNSUPPORTED')
    return [normalize_image(raw)]

@contextmanager
def native_workspace():
    parent=Path(tempfile.gettempdir()).resolve();work=Path(tempfile.mkdtemp(prefix='m1-native-'))
    state={'drained':True}
    try:yield work,state
    finally:
        # On failed process-tree drain retain the complete private workspace for
        # reconciliation. Delete only this function's known files after proof.
        if state['drained'] and work.resolve().parent==parent and work.name.startswith('m1-native-'):
            for name in ('stdin.bin','stdout.bin','command.json','native.log'):(work/name).unlink(missing_ok=True)
            try:work.rmdir()
            except OSError:pass  # unexpected extra files remain quarantined

def run(command,*,raw=None,timeout=180,cancel=lambda:False,cwd=None):
    if cancel():raise Cancelled()
    if os.name!='nt':raise IntegrationError('LOCAL_TOOL_PLATFORM_UNSUPPORTED')
    from ..vision_supervisor.tree import WindowsTree,ContainmentError
    # Reuse the reviewed M1 process-tree containment. Native children are not
    # allowed to outlive a cancellation or hold files after workspace cleanup.
    with native_workspace() as (work,state):
        inp=work/'stdin.bin';out=work/'stdout.bin';spec=work/'command.json'
        inp.write_bytes(raw or b'')
        spec.write_text(json.dumps(dict(command=[str(x) for x in command],cwd=str(cwd or Path.cwd()),
            stdin=str(inp),stdout=str(out))),encoding='utf-8')
        env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('KEY','TOKEN','SECRET','PASSWORD'))}
        env.update(PYTHONIOENCODING='utf-8',PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True',HF_HUB_DISABLE_XET='1')
        with (work/'native.log').open('w+b') as log:
            tree=WindowsTree([sys.executable,str(Path(__file__).with_name('native_worker.py')),str(spec)],
                cwd=str(cwd or Path.cwd()),env=env,log=log)
            state['drained']=False
            started=time.monotonic();drained=False
            try:
                while tree.process.poll() is None:
                    tree.observe()
                    if cancel():raise Cancelled()
                    if time.monotonic()-started>timeout:raise IntegrationError('LOCAL_TOOL_TIMEOUT')
                    time.sleep(.05)
                tree.observe()
                if tree.active():tree.terminate()
                tree.process.wait();tree.wait_members();drained=True;state['drained']=True
                if tree.process.returncode:
                    log.seek(0);failure=IntegrationError('LOCAL_TOOL_FAILED')
                    failure.native_diagnostic=log.read(65536).decode('utf-8',errors='replace');raise failure
                return out.read_bytes()
            finally:
                try:
                    if not drained:
                        tree.terminate();tree.process.wait(timeout=10);tree.wait_members()
                        state['drained']=True
                except BaseException:
                    raise ContainmentError('Native tree drain unverified; private workspaces quarantined') from None
                finally:tree.close()

class LocalTools:
    def __init__(self,*,ocr_python=None,ffmpeg=None,ffprobe=None,font=None):
        self.ocr_python=str(ocr_python or os.getenv('OCR_PYTHON',''))
        self.ffmpeg=str(ffmpeg or os.getenv('FFMPEG_PATH') or shutil.which('ffmpeg') or '')
        self.ffprobe=str(ffprobe or os.getenv('FFPROBE_PATH') or shutil.which('ffprobe') or '')
        self.font=str(font or os.getenv('VIDEO_FONT') or ('C:/Windows/Fonts/msyh.ttc' if os.name=='nt' else ''))
    def status(self):
        return {k:('READY' if v and Path(v).is_file() else 'MISSING') for k,v in dict(
            paddle_python=self.ocr_python,ffmpeg=self.ffmpeg,ffprobe=self.ffprobe,chinese_font=self.font).items()}
    def ocr(self,raw,cancel=lambda:False):
        if not self.ocr_python:raise IntegrationError('OCR_ENVIRONMENT_MISSING')
        runner=Path(__file__).with_name('ocr_runner.py')
        return loads(run([self.ocr_python,runner],raw=raw,timeout=600,cancel=cancel))
    def probe(self,path):
        return loads(run([self.ffprobe,'-v','error','-show_streams','-show_format','-of','json',path]))
    def decode(self,path,cancel=lambda:False):
        run([self.ffmpeg,'-hide_banner','-v','error','-xerror','-i',path,'-f','null','-'],timeout=600,cancel=cancel)
    def audio_duration(self,raw,work,cancel=lambda:False,*,expected_codec='mp3'):
        if cancel():raise Cancelled()
        path=Path(work)/'audio.mp3';path.write_bytes(raw);data=self.probe(path)
        streams=[s for s in data['streams'] if s['codec_type']=='audio']
        if not streams:raise IntegrationError('AUDIO_STREAM_MISSING')
        if expected_codec and streams[0]['codec_name']!=expected_codec:raise IntegrationError('AUDIO_CODEC_MISMATCH')
        duration=float(data['format']['duration'])
        if not .1<duration<=120:raise IntegrationError('AUDIO_DURATION_INVALID')
        pcm=run([self.ffmpeg,'-v','error','-xerror','-i',path,'-ac','1','-ar','16000','-f','s16le','-'],cancel=cancel)
        samples=array.array('h');samples.frombytes(pcm)
        if not samples or math.sqrt(sum(x*x for x in samples)/len(samples))<20:raise IntegrationError('AUDIO_SILENCE_REJECTED')
        return duration
    def validate_video(self,raw,work,minimum,cancel=lambda:False):
        if cancel():raise Cancelled()
        path=Path(work)/'video.mp4';path.write_bytes(raw);data=self.probe(path)
        video=[s for s in data['streams'] if s['codec_type']=='video']
        if not video or video[0]['codec_name']!='h264' or float(data['format']['duration'])+0.1<minimum:
            raise IntegrationError('WAN_VIDEO_INVALID_OR_TOO_SHORT',uncertain=True)
        self.decode(path,cancel);return data
    def compose(self,segments,work,config,cancel=lambda:False):
        if cancel():raise Cancelled()
        work=Path(work);work.mkdir(parents=True,exist_ok=True);entries=[];offset=0;srt=[]
        target_size=(1280,720) if config.resolution=='720P' else (1920,1080)
        fonts=work/'fonts';fonts.mkdir(exist_ok=True);shutil.copyfile(self.font,fonts/('chinese'+Path(self.font).suffix))
        font_family='Noto Sans CJK SC' if 'noto' in Path(self.font).name.lower() else 'Microsoft YaHei'
        for i,s in enumerate(segments):
            if cancel():raise Cancelled()
            d=work/f's{i:03d}';d.mkdir(exist_ok=True)
            (d/'wan.mp4').write_bytes(s['video']);(d/'voice.mp3').write_bytes(s['audio'])
            duration=s['duration'];text=s['narration']
            # Text is data in an SRT file, never interpolated into a command or
            # filter expression. File names are generated, not model-supplied.
            (d/'caption.srt').write_text(f'1\n00:00:00,000 --> {stamp(duration)}\n{text}\n',encoding='utf-8')
            target=d/'segment.mp4';w,h=target_size
            # Work relative paths avoid ffmpeg filter escaping of drive letters.
            filter_=f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,subtitles=caption.srt:fontsdir=../fonts:force_style='FontName={font_family},FontSize=24,Outline=2,Alignment=2,MarginV=28'"
            command=[self.ffmpeg,'-nostdin','-y','-v','error','-xerror','-i',str(d/'wan.mp4'),'-i',str(d/'voice.mp3'),
                '-map','0:v:0','-map','1:a:0','-t',f'{duration:.3f}','-vf',filter_,'-af','loudnorm=I=-18:TP=-1.5:LRA=11',
                '-r','24','-c:v','libx264','-preset','fast','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2','-movflags','+faststart',str(target)]
            # Native CLI runs with a controlled cwd through the helper below.
            run_cwd(command,d,cancel)
            entries.append("file '"+target.as_posix().replace("'","'\\''")+"'")
            srt.append(f'{i+1}\n{stamp(offset)} --> {stamp(offset+duration)}\n{text}\n');offset+=duration
        listing=work/'concat.txt';listing.write_text('\n'.join(entries),encoding='utf-8')
        final=work/'book.mp4'
        # AAC encoder delay makes packet-copy concatenation produce overlapping
        # DTS at page boundaries. Rebuild continuous frame/sample timestamps and
        # encode once; retain strict full-decode validation afterwards.
        run([self.ffmpeg,'-nostdin','-y','-v','error','-xerror','-f','concat','-safe','0','-i',listing,
            '-vf','setpts=N/(24*TB)','-af','asetpts=N/SR/TB','-r','24','-c:v','libx264','-preset','fast',
            '-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2','-movflags','+faststart',final],timeout=600,cancel=cancel)
        self.decode(final,cancel);meta=self.probe(final)
        if {s['codec_type'] for s in meta['streams']}!={'audio','video'}:raise IntegrationError('FINAL_STREAMS_INVALID')
        if abs(float(meta['format']['duration'])-offset)>max(.5,len(segments)*.08):raise IntegrationError('FINAL_TIMELINE_INVALID')
        audio=work/'book.mp3'
        run([self.ffmpeg,'-y','-v','error','-i',final,'-vn','-c:a','libmp3lame',audio],cancel=cancel)
        return dict(video=final.read_bytes(),audio=audio.read_bytes(),subtitles='\n'.join(srt).encode(),duration=offset)

def stamp(seconds):
    ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'

def run_cwd(command,cwd,cancel):
    return run(command,cwd=cwd,timeout=600,cancel=cancel)
