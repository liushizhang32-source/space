"""Exact-commit acceptance with raw XML/log and before/after source fingerprints."""
import argparse,hashlib,json,os,subprocess,sys,time,xml.etree.ElementTree as ET
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parents[1];out=a.output.resolve()
    if out.is_relative_to(root):raise ValueError('Evidence must be outside checkout')
    out.mkdir(parents=True,exist_ok=True)
    if (out/'real-model.xml').exists():raise ValueError('Never overwrite historical evidence')
    def git(*args):return subprocess.check_output(['git','-c','safe.directory='+root.as_posix(),'-C',str(root),*args])
    def snapshot():
        return dict(commit=git('rev-parse','HEAD').decode().strip(),status=git('status','--porcelain=v1','-uall').decode('utf-8'),
            files={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in git('ls-files','-z').decode('utf-8').split('\0') if name})
    before=snapshot()
    if before['status']:raise ValueError('Commit source before exact-SHA acceptance')
    (out/'source-before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
    env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ['KEY','TOKEN','SECRET','PASSWORD'])}
    guard=out/'guard';guard.mkdir()
    # Cloud requests in tests must use explicit MockTransport. Only loopback is
    # allowed for the actual browser/HTTP tests; OCR weights are warmed first.
    (guard/'sitecustomize.py').write_text("import sys\ndef guard(e,a):\n if e in {'socket.connect','socket.getaddrinfo'}:\n  h=a[1][0] if e=='socket.connect' and isinstance(a[1],tuple) else a[0]\n  if h not in {'127.0.0.1','localhost','::1',None}:raise RuntimeError('NO_CLOUD_NETWORK_IN_ACCEPTANCE')\nsys.addaudithook(guard)\n",encoding='utf-8')
    env.update(PYTHONPATH=os.pathsep.join([str(guard),str(root)]),PYTHONIOENCODING='utf-8',PYTHONUTF8='1',
        PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',REAL_MODEL_EVIDENCE_DIR=str(out),
        PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True')
    # OCR child gets the same guard (but no API credentials), preserving offline
    # proof after weights have been downloaded/verified by install_all.
    command=[sys.executable,'-B','-m','pytest','orchestrator/tests/real_model','-o','addopts=','-p','no:cacheprovider',
        '-v','--tb=short','--basetemp',str(out/'tmp'),'--junitxml',str(out/'real-model.xml')]
    started=time.monotonic()
    with (out/'real-model.log').open('w',encoding='utf-8') as log:
        result=subprocess.run(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
    after=snapshot();(out/'source-after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2),encoding='utf-8')
    xml=ET.parse(out/'real-model.xml');counts={name:sum(int(s.get(name,'0')) for s in xml.findall('testsuite')) for name in ['tests','failures','errors','skipped']}
    passed=result.returncode==0 and before==after and not any(counts[n] for n in ['failures','errors','skipped'])
    record=dict(status='PASS' if passed else 'FAIL',tested_commit=before['commit'],source_match=before==after,counts=counts,
        command=command,elapsed_seconds=round(time.monotonic()-started,2),cloud='MOCK_HTTP_ONLY',real_local=['PaddleOCR','OpenCV','FFmpeg','Chromium HTTP'],
        real_cloud_model_test='WAITING_FOR_KEY',production_ready=False)
    (out/'RESULT.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(record,ensure_ascii=True))
    return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
