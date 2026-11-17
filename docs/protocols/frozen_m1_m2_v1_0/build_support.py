"""Read-only helper for validation; does not import the package generator."""
from pathlib import Path
import json, os, subprocess
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
M1ZIP=ROOT/'space-m1-m2-v12-supervisor/reports/M1_LEASE_002_REVIEW_AND_M2_HANDOFF/M1_LEASE_002_AND_M2_HANDOFF_EVIDENCE.zip'
M2ZIP=Path(r'C:\Users\16173\AppData\Local\Temp\codex-file-preview-vJ8c9S\M2_V1.2.6_WORKER(1).zip')
def git(p,*a):
 r=subprocess.run(['git','--no-optional-locks','-c','safe.directory='+str(p),'-C',str(p),*a],capture_output=True,env={**os.environ,'GIT_OPTIONAL_LOCKS':'0'})
 return {'exit':r.returncode,'out':r.stdout.decode('utf-8','replace'),'err':r.stderr.decode('utf-8','replace')}
def snapshot():
 paths=json.loads((ROOT/'review-m1-m2-final-baseline-20261112/checkout-before.json').read_text(encoding='utf-8'))['repos']
 return [{'path':x['path'],**{k:git(Path(x['path']),*a) for k,a in {'branch':('symbolic-ref','--quiet','--short','HEAD'),'head':('rev-parse','HEAD'),'status':('status','--porcelain=v1','--untracked-files=all'),'staged':('diff','--cached','--binary','--no-ext-diff'),'unstaged':('diff','--binary','--no-ext-diff')}.items()}} for x in paths]
