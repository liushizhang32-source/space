"""Install pinned public native tools, validate archives/signatures and font hash."""
import argparse,hashlib,json,os,shutil,subprocess,sys,urllib.request,zipfile
from pathlib import Path,PurePosixPath

def download(url,path):
    with urllib.request.urlopen(url,timeout=120) as source,path.open('wb') as out:shutil.copyfileobj(source,out)
def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',type=Path,required=True);p.add_argument('--ocr-python',required=True);a=p.parse_args()
    root=a.runtime.resolve();tools=root/'tools';tools.mkdir(parents=True,exist_ok=True)
    ffmpeg=str(tools/'ffmpeg.exe') if (tools/'ffmpeg.exe').is_file() else shutil.which('ffmpeg')
    ffprobe=str(tools/'ffprobe.exe') if (tools/'ffprobe.exe').is_file() else shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        # Official BtbN FFmpeg builds, versioned release; pin the downloaded
        # checksum manifest before extraction and verify the exact asset entry.
        name='ffmpeg-n9.0-latest-win64-gpl-9.0.zip'
        base='https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/latest/'
        archive=tools/name;manifest=tools/'checksums.sha256'
        download(base+'checksums.sha256',manifest);lines=manifest.read_text().splitlines()
        expected=next((line.split()[0] for line in lines if line.split()[-1].lstrip('*')==name),None)
        if not expected:raise RuntimeError('Pinned media asset missing from upstream checksum catalogue')
        download(base+name,archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:raise RuntimeError('FFmpeg checksum mismatch')
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                path=PurePosixPath(info.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in info.filename or ':' in info.filename:raise RuntimeError('Unsafe media archive')
                if path.name in {'ffmpeg.exe','ffprobe.exe','LICENSE.txt'}:
                    (tools/path.name).write_bytes(z.read(info))
        ffmpeg=str(tools/'ffmpeg.exe');ffprobe=str(tools/'ffprobe.exe')
    font=tools/'NotoSansCJKsc-Regular.otf'
    if not font.exists():subprocess.run([sys.executable,str(Path(__file__).with_name('prepare_ci_font.py')),'--output',str(font)],check=True)
    expected='2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b'
    if hashlib.sha256(font.read_bytes()).hexdigest()!=expected:raise RuntimeError('Font checksum mismatch')
    for tool in (ffmpeg,ffprobe):subprocess.run([tool,'-version'],check=True,stdout=subprocess.DEVNULL)
    result=dict(ocr_python=str(Path(a.ocr_python).resolve()),ffmpeg=ffmpeg,ffprobe=ffprobe,font=str(font),
        media_sha256={str(x):hashlib.sha256(Path(x).read_bytes()).hexdigest() for x in (ffmpeg,ffprobe)},font_sha256=expected)
    (root/'tools.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print('Native tools verified')
if __name__=='__main__':main()
