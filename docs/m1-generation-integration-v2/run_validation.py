"""Isolated CI_ONLY assembly from exact source ZIP; never install Runtime in feature tree."""
from pathlib import Path
import hashlib,json,zipfile,shutil,os,subprocess,sys,time
O=Path(__file__).resolve().parent;R=O.parents[1];W=R/'m1-m3-implementation-v2';S=O/('ci-only-boundary' if len(sys.argv)>1 and sys.argv[1]=='boundary' else 'ci-only-assembly')
PY=R/'reports/M1-M3-RUNTIME-001/test-env/Scripts/python.exe'
ZIP=R/'space-m1-m2-v12-supervisor/reports/M1_DOC_P2_20261114/M1_OFFLINE_INTEGRATION_KIT_V0_8_1.zip'
sha=lambda b:hashlib.sha256(b).hexdigest()
assert sha(ZIP.read_bytes())=='5cfbbbebbdcb16aefb52c0e634291f06d929c5d778594f74cd5e9c0df957dad1'
mode=sys.argv[1] if len(sys.argv)>1 else 'focused'
shutil.copytree(W,S,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','__pycache__','_test_tmp','.pytest_cache'))
with zipfile.ZipFile(ZIP) as z:
 manifest=json.loads(z.read('KIT_MANIFEST.json'))
 assert z.testzip() is None
 assert set(z.namelist())==set(manifest)|{'KIT_MANIFEST.json'}
 assert all(sha(z.read(n))==h for n,h in manifest.items())
 selected={n:h for n,h in manifest.items() if n.startswith(tuple('orchestrator/services/'+d+'/' for d in ['integration_reference','vision_supervisor','poc_security']))}
 assert len(selected)==29
 for n,h in selected.items():
  assert not (W/n).exists(),'formal runtime assembly prohibited pending signoff'
  p=S/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(n))
 if mode=='boundary':
  for n in manifest:
   if n.startswith('orchestrator/tests/'):
    dest=S/n;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(n))
 audit=dict(status='CI_ONLY; M1_SIGNOFF_PENDING; production assembly stopped',archive=str(ZIP),archive_sha256=sha(ZIP.read_bytes()),manifest_sha256=sha(z.read('KIT_MANIFEST.json')),manifest_entries=len(manifest),runtime_files=selected)
 (O/'runtime-source-verification.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
guard=O/'network_guard';guard.mkdir(exist_ok=True)
(guard/'sitecustomize.py').write_text("import sys\ndef guard(event,args):\n if event in {'socket.connect','socket.getaddrinfo'}:\n  target=args[1] if event=='socket.connect' else args[0]\n  host=target[0] if isinstance(target,tuple) else target\n  if host not in {'localhost','127.0.0.1','::1',None}:raise RuntimeError('CI_ONLY_EXTERNAL_NETWORK_DENIED')\nsys.addaudithook(guard)\n",encoding='utf-8')
env=dict(os.environ)
for k in list(env):
 if any(n in k.upper() for n in ['TOKEN','SECRET','API_KEY','APIKEY']):env.pop(k,None)
env.update(PYTHONPATH=os.pathsep.join([str(guard),str(S)]),PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',TTS_ENGINE='silent',
 FFMPEG_PATH=str(R/'.venv-schema-tests/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v9.0.2.exe'),FFPROBE_PATH=str(R/'module-review-20261109/member3-pr-review/tools/ffprobe.exe'),VIDEO_FONT='C:/Windows/Fonts/msyh.ttc')
tests=(['orchestrator/tests/test_m1_integration_reference.py'] if mode=='boundary' else
 ['orchestrator/tests/test_member3_m1_callchain.py'] if mode=='focused' else ['orchestrator/vendor/member3_v116/tests','orchestrator/tests/test_member3_integration.py','orchestrator/tests/test_member3_lifecycle.py','orchestrator/tests/test_member3_m1_callchain.py'])
label='M3_FULL_TEST' if mode=='full' else mode.upper()
log=O/(label+'_LOG.txt');xml=O/(label+'_RESULTS.xml')
if log.exists():
 idx=1
 while (O/f'{label}_previous_{idx}.txt').exists():idx+=1
 log.rename(O/f'{label}_previous_{idx}.txt')
 if xml.exists():xml.rename(O/f'{label}_previous_{idx}.xml')
cmd=[str(PY),'-B','-m','pytest','-c',str(S/'pytest.ini'),*tests,'-o','addopts=','-p','no:cacheprovider','-v','--tb=short','--basetemp',str(O/('tmp-'+mode)),'--junitxml',str(xml)]
start=time.monotonic()
with log.open('w',encoding='utf-8') as f:p=subprocess.run(cmd,cwd=S,env=env,stdout=f,stderr=subprocess.STDOUT)
(O/(label+'_COMMAND.json')).write_text(json.dumps(dict(command=cmd,cwd=str(S),exit=p.returncode,seconds=time.monotonic()-start,status='CI_ONLY',network='external blocked; loopback only'),indent=2),encoding='utf-8')
print(p.returncode);print(log.read_text(encoding='utf-8')[-11000:])
