"""Single entry: PROPOSED protocols and full offline acceptance; no network.

Run with the existing test interpreter and an output directory outside the repo.
M2's optional evidence is enabled in an exact external copy, never by editing tests.
"""
import argparse,hashlib,json,os,pathlib,shutil,subprocess,sys,time,xml.etree.ElementTree as ET

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--phase',choices=['unit','full'],default='full')
    parser.add_argument('--extra-site',action='append',default=[]);args=parser.parse_args()
    W=pathlib.Path(__file__).resolve().parents[1];O=pathlib.Path(args.output).resolve()
    assert not O.is_relative_to(W),'Evidence must remain outside source checkout'
    O.mkdir(parents=True,exist_ok=True)
    def git(*a):return subprocess.check_output(['git','-c',f'safe.directory={W.as_posix()}','-C',str(W),*a])
    def snapshot():return dict(commit=git('rev-parse','HEAD').decode().strip(),status=git('status','--porcelain=v1','-uall').decode('utf-8'),
        sha256={p:hashlib.sha256((W/p).read_bytes()).hexdigest() for p in git('ls-files','-z').decode('utf-8').split('\0') if p and (W/p).is_file()})
    guard=O/'network_guard';guard.mkdir(exist_ok=True)
    (guard/'sitecustomize.py').write_text("import sys\ndef deny(e,a):\n if e in {'socket.connect','socket.getaddrinfo'}:\n  t=a[1] if e=='socket.connect' else a[0];h=t[0] if isinstance(t,tuple) else t\n  if h not in {'localhost','127.0.0.1','::1',None}:raise RuntimeError('OFFLINE_ACCEPTANCE_ONLY')\nsys.addaudithook(deny)\n",encoding='utf-8')
    env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)','SYSTEMDRIVE','NUMBER_OF_PROCESSORS'}}
    parent=W.parent
    env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',M1_DEPLOYMENT_ENV='local',M1_ASSET_MODE='offline_mock',TTS_ENGINE='silent',PYTHONPATH=os.pathsep.join([str(guard),str(W)]),MISSION_EVIDENCE=str(O),CLOSURE004_EVIDENCE=str(O),JOINT_SECURITY_EVIDENCE_DIR=str(O/'main-http'),SCHEMA_REPO_ROOT=str(W),
        FFMPEG_PATH=str(parent/'.venv-schema-tests/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v9.0.2.exe'),FFPROBE_PATH=str(parent/'module-review-20261109/member3-pr-review/tools/ffprobe.exe'),VIDEO_FONT='C:/Windows/Fonts/msyh.ttc')
    groups=[('protocols',[str(p.relative_to(W)) for p in sorted((W/'orchestrator/tests').glob('test_offline_*.py'))])]
    copied=None
    if args.phase=='full':
        D=O/'m2-exact';copied={}
        for p in git('ls-files','-z').decode('utf-8').split('\0'):
            if p.startswith('paperbook-ai-m2/paperbook-ai/'):dest=D/'paperbook-ai'/p.removeprefix('paperbook-ai-m2/paperbook-ai/')
            elif p.startswith('orchestrator/') and p.endswith('.py'):dest=D/'.m1evidence'/p
            else:continue
            raw=(W/p).read_bytes();dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw);copied[str(dest)]=hashlib.sha256(raw).hexdigest()
        (O/'m2-copy-fingerprints.json').write_text(json.dumps(copied,ensure_ascii=False,indent=2),encoding='utf-8')
        groups += [('m1',[str(p.relative_to(W)) for p in sorted((W/'orchestrator/tests').glob('test_m1_*.py'))]),
            ('m2',[str(D/'paperbook-ai/tests')]),
            ('m3',['orchestrator/vendor/member3_v116/tests','orchestrator/tests/test_member3_integration.py','orchestrator/tests/test_member3_lifecycle.py','orchestrator/tests/test_member3_m1_callchain.py','orchestrator/tests/test_member3_asset_security.py','orchestrator/tests/test_member3_unknown_semantics.py']),
            ('joint',['orchestrator/tests/test_m2_mission_worker.py','orchestrator/tests/test_m123_mission_chain.py','orchestrator/tests/test_m123_mission_failures.py','orchestrator/tests/test_member3_tts_factory_security.py','orchestrator/tests/test_offline_protocol_joint.py'])]
        groups += [('ci-'+n,None) for n in ['schema','api','member134','enhanced','integration','lifecycle','replay','http','m1-runtime']]
    results=[]
    for label,tests in groups:
        assert not (O/(label+'.log')).exists(),'Never overwrite historical evidence'
        before=snapshot();assert not before['status'],before['status']
        (O/(label+'-before.json')).write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
        if tests is None:cmd=[sys.executable,'-B','tools/ci/run.py','--target',str(W),'--output',str(O/'team-ci'),'--group',label[3:]]
        else:cmd=[sys.executable,'-B','-m','pytest','-c',str(W/'pytest.ini'),*tests,'-o','addopts=','-p','no:cacheprovider','-v','--tb=short','--basetemp',str(O/('tmp-'+label)),'--junitxml',str(O/(label+'.xml'))]
        this_env=dict(env)
        if label=='m2':this_env['PYTHONPATH']+=os.pathsep+os.pathsep.join(args.extra_site)
        start=time.monotonic()
        with (O/(label+'.log')).open('w',encoding='utf-8') as out:r=subprocess.run(cmd,cwd=W,env=this_env,stdout=out,stderr=subprocess.STDOUT)
        after=snapshot();match=before==after
        (O/(label+'-after.json')).write_text(json.dumps(after,ensure_ascii=False,indent=2),encoding='utf-8')
        record=dict(group=label,exit=r.returncode,command=cmd,commit=before['commit'],source_match=match,seconds=time.monotonic()-start)
        (O/(label+'-command.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');results.append(record)
        print(label,r.returncode,'SOURCE_MATCH',match,flush=True)
        if r.returncode:print((O/(label+'.log')).read_text(encoding='utf-8')[-6000:],flush=True)
        if not match:break
    if copied:assert all(hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()==h for p,h in copied.items())
    # Preserve group suites. The consolidated JUnit deduplicates identical case
    # identities across overlapping groups; raw group XML remains authoritative.
    all_suites=ET.Element('testsuites');seen={};duplicates=0
    for p in sorted(O.rglob('*.xml')):
        if p.name=='M1_M2_M3_FULL_TEST_RESULTS.xml' or any(part.startswith('tmp-') for part in p.parts):continue
        for case in ET.fromstring(p.read_bytes()).iter('testcase'):
            key=(case.get('classname'),case.get('name'));outcome=any(case.find(x) is not None for x in ['failure','error','skipped'])
            if key in seen:
                duplicates+=1
                if outcome and not seen[key][1]:seen[key]=(case,True)
            else:seen[key]=(case,outcome)
    suite=ET.SubElement(all_suites,'testsuite',name='deduplicated_offline_acceptance')
    for case,_ in seen.values():suite.append(case)
    suite.set('tests',str(len(seen)))
    for tag,attr in [('failure','failures'),('error','errors'),('skipped','skipped')]:suite.set(attr,str(sum(c.find(tag) is not None for c,_ in seen.values())))
    ET.ElementTree(all_suites).write(O/'M1_M2_M3_FULL_TEST_RESULTS.xml',encoding='utf-8',xml_declaration=True)
    (O/'RUN_SUMMARY.json').write_text(json.dumps(dict(results=results,duplicate_cases_excluded=duplicates,aggregate_scope='overlapping groups deduplicated; raw group counts reported separately',status='PASS' if all(x['exit']==0 and x['source_match'] for x in results) else 'FAIL'),ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if all(x['exit']==0 and x['source_match'] for x in results) else 1

if __name__=='__main__':raise SystemExit(main())
