"""Additional official protocol static checks. Pure reference model, no runtime dispatch."""
from pathlib import Path
import ast,copy,hashlib,json,math,re
OUT=Path(__file__).resolve().parent
def read(n):return json.loads((OUT/n).read_text(encoding='utf-8'))
rows=[]
def test(n,f,reject=False):
 try:f()
 except (AssertionError,ValueError,KeyError,TypeError,UnicodeError) as e:ok=reject;detail=type(e).__name__+': '+str(e)[:160]
 else:ok=not reject;detail='accepted' if ok else 'unexpected acceptance'
 rows.append({'name':n,'pass':ok,'expected':'reject' if reject else 'accept','detail':detail});print(('PASS ' if ok else 'FAIL ')+n+' | '+detail)
def require(c):assert c
def digest(b):return hashlib.sha256(b).hexdigest()
def canonical(messages):
 assert type(messages) is list and messages
 ordered=[]
 for m in messages:
  assert type(m) is dict and set(m)=={'role','content'}
  assert type(m['role']) is str and m['role'] and type(m['content']) is str
  for s in [m['role'],m['content']]:s.encode('utf-8','strict')
  ordered.append({'role':m['role'],'content':m['content']})
 return json.dumps(ordered,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8','strict')
msg=read('fixtures/FINAL_MESSAGES.json');phex=read('PROMPT_HASH_EXAMPLE.json')
test('official final ordered messages exact canonical bytes',lambda:require(canonical(msg)==(OUT/phex['canonical_file']).read_bytes()))
test('prompt hash reproducible',lambda:require(digest(canonical(msg))==phex['prompt_sha256']))
test('canonical JSON has no BOM or added formatting whitespace',lambda:require(not canonical(msg).startswith(b'\xef\xbb\xbf') and b'": "' not in canonical(msg)))
test('input key insertion order cannot change canonical role/content order',lambda:require(canonical([dict(reversed(list(m.items()))) for m in msg])==canonical(msg)))
test('message order changes hash',lambda:require(digest(canonical(list(reversed(msg))))!=phex['prompt_sha256']))
test('role participates in hash',lambda:require(digest(canonical([{**msg[0],'role':'assistant'},msg[1]]))!=phex['prompt_sha256']))
test('final content replacement participates in hash',lambda:require(digest(canonical([msg[0],{**msg[1],'content':'template %s'}]))!=phex['prompt_sha256']))
test('trimming changes hash and is forbidden',lambda:require(digest(canonical([{**m,'content':m['content'].strip()} for m in msg]))!=phex['prompt_sha256']))
test('invalid Unicode rejected',lambda:canonical([{'role':'user','content':'\ud800'}]),True)
test('unknown message key rejected',lambda:canonical([{'role':'user','content':'x','secret':'not read'}]),True)
test('NaN message rejected',lambda:canonical([{'role':'user','content':float('nan')}]),True)
test('non-text multimodal content unsupported',lambda:canonical([{'role':'user','content':[]}]),True)
test('empty message list rejected',lambda:canonical([]),True)
for a in phex['attachments']:
 test('attachment raw hash and ordered-message association',lambda a=a:require(type(a['message_index']) is int and 0<=a['message_index']<len(msg) and digest((OUT/a['fixture_file']).read_bytes())==a['raw_sha256']))
reg=read('fixtures/EVIDENCE_REGISTRY.json')
for e in read('SIDECAR_EXAMPLES.json')['examples']:
 test('Sidecar final message hash '+e['name'],lambda e=e:require(e['sidecar']['source']['prompt_sha256']==phex['prompt_sha256']))
test('no accepted calibrated=true fixture before M5 registry',lambda:require(all(o['confidence']['calibrated'] is False for e in read('SIDECAR_EXAMPLES.json')['examples'] for o in e['sidecar']['observations'])))
def calibration(c,independent_registry):
 assert type(c['calibrated']) is bool
 if c['calibrated']:assert independent_registry.get('operational') and independent_registry.get('actual_model_version') and independent_registry.get('dataset_id') and independent_registry.get('method')
test('model assertion calibrated=true alone rejected',lambda:calibration({'calibrated':True},{}),True)
test('toy calibration cannot bypass incomplete M5 registry',lambda:calibration({'calibrated':True},{'method':'toy','dataset_id':'synthetic'}),True)
private=read('PRIVATE_CONTRACT_SCHEMAS.json')
test('official OCR/VLM Schema views equal internal validator contracts',lambda:require(read('REQUEST_SCHEMA.json')['oneOf']==[private['OCR_REQUEST'],private['VLM_REQUEST']]))
for file,key in [('WORKER_RESULT_SCHEMA.json','WORKER_RESULT'),('SIDECAR_SCHEMA.json','SIDECAR')]:
 test('official '+file+' equals validated structural contract',lambda file=file,key=key:require({k:v for k,v in read(file).items() if k not in ['$schema','$id','$comment']}==private[key]))

# A pure serialized reference ledger for specification examples only.
# Not an M1 implementation, not a real persistence/concurrency/crash test.
KEY=('job','book01_p03','generation',1,1,'ocr')
def reserve(ledger,key,attempt,token,expected_version=None):
 state=copy.deepcopy(ledger);unit=state.setdefault('|'.join(map(str,key)),{'version':0,'attempts':[]})
 if expected_version is not None:assert unit['version']==expected_version,'stale concurrent reservation'
 assert all(r['state'] not in {'unknown','reserved'} for r in unit['attempts']),'unresolved predecessor'
 assert len(unit['attempts'])<2,'stage maximum two total attempts'
 assert all(r['attempt_id']!=attempt and r['fencing_token']!=token for u in state.values() for r in u['attempts'])
 unit['attempts'].append({'ordinal':len(unit['attempts'])+1,'attempt_id':attempt,'fencing_token':token,'state':'reserved'})
 unit['version']+=1;return state
def settled(ledger,state='terminated'):
 v=copy.deepcopy(ledger);v['|'.join(map(str,KEY))]['attempts'][-1]['state']=state;return v
def attempt_counts(l):return [len(u['attempts']) for u in l.values()]
first=reserve({},KEY,'a1','t1');done=settled(first);second=reserve(done,KEY,'a2','t2');second_done=settled(second)
test('reference initial Attempt1 reserved before dispatch',lambda:require(attempt_counts(first)==[1]))
test('reference exactly one legitimate retry',lambda:require(attempt_counts(second)==[2]))
test('reference third attempt rejected',lambda:reserve(second_done,KEY,'a3','t3'),True)
test('reference supervisor restart serialization preserves count',lambda:require(attempt_counts(json.loads(json.dumps(second_done)))==[2]))
test('reference third rejected after serialized restart',lambda:reserve(json.loads(json.dumps(second_done)),KEY,'a3','t3'),True)
test('reference reserved process crash consumes attempt and blocks blind retry',lambda:reserve(json.loads(json.dumps(first)),KEY,'a2','t2'),True)
test('reference duplicate entry cannot reset maximum',lambda:reserve(second_done,KEY,'new','new'),True)
test('reference stale concurrent reservation version rejected',lambda:reserve(done,KEY,'a2','t2',0),True)
test('reference same attempt id rejected',lambda:reserve(done,KEY,'a1','t-new'),True)
test('reference same fencing token rejected',lambda:reserve(done,KEY,'a-new','t1'),True)
test('reference unknown retains consumed attempt and rejects resubmit',lambda:reserve(settled(first,'unknown'),KEY,'a2','t2'),True)
test('reference OCR and VLM counted separately',lambda:require(sorted(attempt_counts(reserve(done,(*KEY[:-1],'vlm'),'v1','vt1')))==[1,1]))
def retry(code,transient=True,typed_cancel=False,terminated=True,count=1,live=True,exact_2004_id=None,msg=''):
 if typed_cancel or not live or not terminated or count>=2:return False
 if code in {9001,3004,3001}:return False
 if code==2004:return False # No exact 2004 identifiers approved in current locked M1.
 return type(code) is int and code in {2001,2002,2003} and transient is True and not(code==2001 and 'safety' in msg.casefold())
for name,kw,expect in [('timeout after termination',{'code':2002},True),('timeout before termination',{'code':2002,'terminated':False},False),('typed cancellation',{'code':2004,'typed_cancel':True},False),('transient 2004 without exact identifier',{'code':2004},False),('invented 2004 identifier',{'code':2004,'exact_2004_id':'self-declared'},False),('9001',{'code':9001},False),('3004',{'code':3004},False),('3001 OCR special nonretry',{'code':3001},False),('second total attempt exhausted',{'code':2002,'count':2},False),('cancelled fences',{'code':2002,'live':False},False),('safety 2001',{'code':2001,'msg':'safety'},False)]:
 test('formal retry '+name,lambda kw=kw,expect=expect:require(retry(**kw)==expect))

evidence=read('audit/LINE_EVIDENCE.json');locks={e['id']:e for e in read('SOURCE_LOCK.json')}
for k,e in evidence.items():
 def verify(k=k,e=e):
  raw=(OUT/e['locked_copy']).read_bytes();assert digest(raw)==e['sha256']
  lines=raw.decode('utf-8-sig').splitlines();assert 1<=e['line_start']<=e['line_end']<=len(lines)
  if e['source_id']!='OWNER_ORDER' and e['locked_copy'].endswith('.py.txt'):
   nodes=list(ast.walk(ast.parse(raw)))
   assert e['line_start']==1 and e['line_end']==len(lines) or any(isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and min([n.lineno]+[d.lineno for d in getattr(n,'decorator_list',[])])==e['line_start'] and n.end_lineno==e['line_end'] for n in nodes)
 test('source range regenerated and hash matches '+k,verify)
test('Profile B exact pairing and A remains independently blocked',lambda:require('NOT_CERTIFIED' in (OUT/'RUNTIME_PAIRING_MATRIX.md').read_text(encoding='utf-8') and 'Profile A 执行接入 BLOCKED' in (OUT/'RUNTIME_PAIRING_MATRIX.md').read_text(encoding='utf-8')))
summary={'scope':'static official protocol cases; ledger examples use only in-memory serialized reference state, NOT M1 persistence or real concurrency/crash execution','passed':sum(r['pass'] for r in rows),'failed':sum(not r['pass'] for r in rows),'results':rows}
(OUT/'audit/OFFICIAL_STATIC_RESULTS.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print('OFFICIAL TOTAL',summary['passed'],'passed;',summary['failed'],'failed')
assert summary['failed']==0
