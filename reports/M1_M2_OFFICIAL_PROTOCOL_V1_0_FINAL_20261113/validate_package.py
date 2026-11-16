"""Static JSON/byte contracts and side-effect-free locked model/Gate checks only.

No Worker, Supervisor, lease Core or provider is imported or launched.
The emitted schemas use only the explicitly supported JSON-Schema keywords below.
"""
from pathlib import Path, PurePosixPath, PureWindowsPath
from dataclasses import asdict, make_dataclass
from types import SimpleNamespace, ModuleType
import ast, copy, hashlib, json, math, re, sys
from build_support import OUT, ROOT, M1ZIP, M2ZIP, snapshot

def sha(b): return hashlib.sha256(b).hexdigest()
def strict_load(raw):
 def pairs(items):
  d={}
  for k,v in items:
   if k in d: raise ValueError('duplicate key: '+k)
   d[k]=v
  return d
 return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite '+x)))
def read(n): return strict_load((OUT/n).read_text(encoding='utf-8'))
results=[]
def check(name,fn,negative=False):
 try:
  fn()
 except (ValueError,TypeError,KeyError,AssertionError) as e:
  ok=negative; detail=type(e).__name__+': '+str(e)[:230]
 else: ok=not negative; detail='accepted' if ok else 'unexpected acceptance'
 results.append({'name':name,'pass':ok,'expected':'reject' if negative else 'accept','detail':detail})
 print(('PASS ' if ok else 'FAIL ')+name+' | '+detail)

lock=read('SOURCE_LOCK.json')
for e in lock:
 assert sha((OUT/e['locked_copy']).read_bytes())==e['sha256'],e['id']
 if e['source_checkout']: assert sha((Path(e['source_checkout'])/e['source_relative_path']).read_bytes())==e['sha256']
inputs=read('audit/INPUT_VERIFICATION.json')
assert sha(M1ZIP.read_bytes())==inputs['M1']['sha256']
assert sha(M2ZIP.read_bytes())==inputs['M2']['sha256']

# A deliberately small validator for the complete keyword subset emitted here.
# It fails on unsupported keywords rather than pretending to be a full JSON Schema engine.
ANNOTATIONS={'$schema','$id','$comment','title','description'}
SUPPORTED=ANNOTATIONS|{'type','const','enum','minimum','maximum','minLength','pattern','properties','required','additionalProperties','items'}
def schema_check(s):
 assert not set(s)-SUPPORTED, 'unsupported schema keyword '+str(set(s)-SUPPORTED)
 for c in s.get('properties',{}).values(): schema_check(c)
 if 'items' in s: schema_check(s['items'])
def validate(x,s,path='$'):
 def istype(t):
  return {'object':type(x) is dict,'array':type(x) is list,'string':type(x) is str,'integer':type(x) is int,'number':type(x) in (int,float) and math.isfinite(x),'boolean':type(x) is bool,'null':x is None}[t]
 if 'type' in s: assert any(istype(t) for t in (s['type'] if type(s['type']) is list else [s['type']])),path+' wrong native type'
 if 'const' in s: assert type(x) is type(s['const']) and x==s['const'],path+' wrong constant'
 if 'enum' in s: assert any(type(x) is type(v) and x==v for v in s['enum']),path+' wrong enum'
 if type(x) in (int,float):
  assert math.isfinite(x),path+' nonfinite'
  if 'minimum' in s: assert x>=s['minimum'],path+' minimum'
  if 'maximum' in s: assert x<=s['maximum'],path+' maximum'
 if type(x) is str:
  if 'minLength' in s: assert len(x)>=s['minLength'],path+' minLength'
  if 'pattern' in s: assert re.search(s['pattern'],x),path+' pattern'
 if type(x) is dict:
  assert set(s.get('required',[]))<=x.keys(),path+' missing keys'
  props=s.get('properties',{})
  if s.get('additionalProperties') is False: assert not set(x)-set(props),path+' unknown keys '+str(set(x)-set(props))
  for k,v in x.items():
   if k in props: validate(v,props[k],path+'.'+k)
 if type(x) is list and 'items' in s:
  for i,v in enumerate(x): validate(v,s['items'],path+f'[{i}]')

schemas=read('PRIVATE_CONTRACT_SCHEMAS.json'); binding_schema=read('C1_BINDING_SCHEMA.json')
for k,s in schemas.items():
 if k!='$comment': schema_check(s)
schema_check(binding_schema)

def model_module(source_id,name):
 e=next(e for e in lock if e['id']==source_id); path=OUT/e['locked_copy']
 mod=ModuleType(name); mod.__file__=str(path); sys.modules[name]=mod
 # These two locked modules contain only Pydantic schema classes/validators and imports.
 tree=ast.parse(path.read_bytes())
 assert all(isinstance(n,(ast.Import,ast.ImportFrom,ast.ClassDef)) for n in tree.body)
 exec(compile(tree,str(path),'exec'),mod.__dict__)
 return mod
OCR=model_module('M1:orchestrator/schemas/ocr.py','_offline_locked_ocr').OCRData
VLM=model_module('M1:orchestrator/schemas/vlm.py','_offline_locked_vlm').VLMData

# Run precisely the locked pure Gate.refs method, not the containing runtime.
gate_lock=next(e for e in lock if e['id']=='M1:orchestrator/services/vision_supervisor/gate.py')
gate_path=OUT/gate_lock['locked_copy']; gate_tree=ast.parse(gate_path.read_bytes())
gate_node=next(n for n in gate_tree.body if isinstance(n,ast.ClassDef) and n.name=='Gate')
refs_node=next(n for n in gate_node.body if isinstance(n,ast.FunctionDef) and n.name=='refs')
gate_subset=ast.Module(body=[ast.ClassDef(name='Gate',bases=[],keywords=[],body=[refs_node],decorator_list=[])],type_ignores=[])
ast.fix_missing_locations(gate_subset)
namespace={'asdict':asdict,'PurePosixPath':PurePosixPath,'math':math,'unique_json':strict_load}
exec(compile(gate_subset,str(gate_path),'exec'),namespace)
ActualRefs=namespace['Gate'].refs
I=make_dataclass('LockedIdentity',[(k,object) for k in ['job_id','page_id','generation_id','input_revision','epoch','attempt_id','fencing_token']],frozen=True)
OCR_REQ=read('OCR_REQUEST_EXAMPLE.json'); VLM_REQ=read('VLM_REQUEST_EXAMPLE.json'); BIND=read('C1_BINDING_EXAMPLE.json')
IDENT_KEYS=list(BIND['identity']); COMMON=IDENT_KEYS[:5]
REG=read('fixtures/EVIDENCE_REGISTRY.json')
C1_BYTES=(OUT/'fixtures/C1.json').read_bytes(); IMAGE=(OUT/'fixtures/IMAGE_HASH_FIXTURE.bin').read_bytes()
def pathclass(p): return PureWindowsPath(p) if re.match(r'^[A-Za-z]:',p) else PurePosixPath(p)
def within(p,root):
 q=pathclass(p); r=pathclass(root)
 assert q.is_absolute() and '..' not in q.parts and q.is_relative_to(r),'outside approved snapshot boundary'
 assert q.parent==r,'unexpected nested input path'
 return q
def request(x,root,expected_ocr=BIND['identity'],c1raw=C1_BYTES):
 validate(x,schemas['OCR_REQUEST' if x.get('stage')=='ocr' else 'VLM_REQUEST'])
 assert re.fullmatch('[a-z][a-z0-9]{3,11}_p[0-9]{2}',x['page_id'])
 assert x['outputs']=={'c1':f"json/{x['page_id']}_ocr.json",'c2':f"json/{x['page_id']}_vlm.json",'sidecar':f"json/{x['page_id']}_refs.json"}
 assert len(set(x['outputs'].values())|{x['result_path']})==4
 within(x['image_path'],root)
 assert sha(IMAGE)==x['image_sha256'],'raw image hash mismatch'
 if x['stage']=='vlm':
  p=within(x['inputs']['c1'],root); assert p.name=='c1.json'
  b=x['c1_binding']; assert b['identity']==expected_ocr,'not the trusted OCR snapshot identity'
  assert all(type(b['identity'][k]) is type(x[k]) and b['identity'][k]==x[k] for k in COMMON),'cross task identity'
  assert all(b['identity'][k]!=x[k] for k in ['attempt_id','fencing_token']),'OCR/VLM attempts not separate'
  assert sha(c1raw)==b['sha256'],'raw C1 hash mismatch'
  assert b['image_sha256']==x['image_sha256'],'bound image hash mismatch'
  c1=OCR.model_validate(strict_load(c1raw)); assert c1.page_id==x['page_id'] and c1.status!='failed'
def result(x,req,exitcode=0):
 validate(x,schemas['WORKER_RESULT'])
 assert x['identity']=={k:req[k] for k in IDENT_KEYS},'result identity mismatch'
 assert all(type(x['identity'][k]) is type(req[k]) for k in IDENT_KEYS)
 empty=x['code']==3001 and req['stage']=='ocr'
 if x['code']==0 or empty:
  if not empty: assert exitcode==0,'success with nonzero process exit'
  keys=['c1'] if req['stage']=='ocr' else ['c2','sidecar']
  assert x['artifacts']=={k:req['outputs'][k] for k in keys}
  if empty: assert OCR.model_validate_json(C1_BYTES).status=='empty'
 else: assert x['artifacts']=={},'error must not claim usable artifacts'
def sidecar(x,c2file,registry=REG):
 validate(x,schemas['SIDECAR'])
 assert all(type(x[k]) is type(VLM_REQ[k]) and x[k]==VLM_REQ[k] for k in IDENT_KEYS),'sidecar identity'
 raw=(OUT/c2file).read_bytes(); c2doc=strict_load(raw)
 assert type(c2doc['safety']['pass']) is bool and c2doc['safety']['pass'] is True and c2doc['safety']['flags']==[]
 c2=VLM.model_validate(c2doc)
 assert c2.page_id==x['page_id'] and (c2.image_width,c2.image_height)==(96,128)
 assert x['c2']['sha256']==sha(raw) and x['c2']['relative_path']==VLM_REQ['outputs']['c2']
 evidence=registry[x['source']['evidence_ref']]
 assert evidence['model_ref']==x['source']['model_ref'] and evidence['component_mode']==x['source']['component_mode']
 assert sha((OUT/evidence['prompt_file']).read_bytes())==x['source']['prompt_sha256']==evidence['prompt_sha256']
 observed=set(); objects={o.object_id for o in c2.objects}
 for o in x['observations']:
  assert o['observation_id'] not in observed; observed.add(o['observation_id']); assert o['object_id'] in objects
  assert o['source_ref'] in registry and o['visual_description'].strip()
  a=o['appearance']
  if 'clothing' in a: assert a['clothing'].strip() and evidence.get('clothing_observation'),'unobserved/empty clothing'
  c=o['confidence']
  if c['kind']=='unavailable': assert c.get('value') is None and c['calibrated'] is False
  else: assert type(c.get('value')) in (int,float) and math.isfinite(c['value']) and 0<=c['value']<=1
  if c['calibrated']:
   assert False, 'M5 independent calibration registry incomplete; calibrated=true not accepted'
   assert o['observation_id'] in evidence['authorized_calibrated_observation_ids']
   b=(OUT/evidence['calibration_file']).read_bytes(); assert sha(b)==evidence['calibration_sha256']
   cal=strict_load(b); assert cal['model_ref']==x['source']['model_ref'] and cal['scope'].startswith('synthetic fixture only')
   preds,labels=cal['evaluation_predictions'],cal['evaluation_labels']
   assert len(preds)==len(labels)>0
   assert sum((a-b)**2 for a,b in zip(preds,labels))/len(labels)==cal['brier_score']
   assert abs(sum(preds)/len(preds)-sum(labels)/len(labels))==cal['single_bin_ece']
 return c2

check('all generated JSON parses strictly',lambda:[read(str(p.relative_to(OUT))) for p in OUT.rglob('*.json')])
check('binding schema',lambda:validate(BIND,binding_schema))
check('OCR Request exact producer fields',lambda:request(OCR_REQ,'C:/m1-offline/attempt-ocr-001'))
check('VLM Request and C1 context',lambda:request(VLM_REQ,'C:/m1-offline/attempt-vlm-001'))
check('public frozen C1 Python validators',lambda:OCR.model_validate_json(C1_BYTES))
check('VLM success result',lambda:result(read('WORKER_RESULT_EXAMPLE.json'),VLM_REQ))
check('OCR success empty result',lambda:result(read('fixtures/OCR_RESULT.json'),OCR_REQ))
empty=read('fixtures/OCR_RESULT.json');empty['code']=3001
check('OCR 3001 valid empty nonzero-exit exception',lambda:result(empty,OCR_REQ,1))
failure={**read('WORKER_RESULT_EXAMPLE.json'),'code':2004,'transient':True,'artifacts':{}}
check('2004 error envelope is failure even with exit0',lambda:result(failure,VLM_REQ,0))
examples=read('SIDECAR_EXAMPLES.json')['examples']
for e in examples:
 check('proposed Sidecar '+e['name'],lambda e=e:sidecar(e['sidecar'],e['c2_fixture_file']))
 check('locked Gate.refs '+e['name'],lambda e=e:ActualRefs(json.dumps(e['sidecar'],ensure_ascii=False).encode(),I(**{k:VLM_REQ[k] for k in IDENT_KEYS}),VLM.model_validate_json((OUT/e['c2_fixture_file']).read_bytes()),sha((OUT/e['c2_fixture_file']).read_bytes())))

def bad_request(name,edit):
 x=copy.deepcopy(VLM_REQ);edit(x);check(name,lambda:request(x,'C:/m1-offline/attempt-vlm-001'),True)
bad_request('reject missing inputs',lambda x:x.pop('inputs'))
bad_request('reject null c1',lambda x:x['inputs'].__setitem__('c1',None))
bad_request('reject unknown request field',lambda x:x.__setitem__('extra',1))
bad_request('reject unknown binding field',lambda x:x['c1_binding'].__setitem__('extra',1))
bad_request('reject unknown identity field',lambda x:x['c1_binding']['identity'].__setitem__('extra',1))
bad_request('reject bool revision',lambda x:x.__setitem__('input_revision',True))
bad_request('reject float epoch',lambda x:x.__setitem__('epoch',1.0))
bad_request('reject unsupported protocol',lambda x:x.__setitem__('protocol','m1-vision-worker/2.0'))
for k in COMMON:
 bad_request('reject cross-'+k+' binding',lambda x,k=k:x['c1_binding']['identity'].__setitem__(k,2 if k in ['epoch','input_revision'] else 'other'))
for k in ['attempt_id','fencing_token']:
 bad_request('reject stale OCR '+k,lambda x,k=k:x['c1_binding']['identity'].__setitem__(k,'stale'))
 bad_request('reject conflated OCR/VLM '+k,lambda x,k=k:x.__setitem__(k,x['c1_binding']['identity'][k]))
bad_request('reject C1 hash mismatch',lambda x:x['c1_binding'].__setitem__('sha256','0'*64))
bad_request('reject image hash mismatch',lambda x:x.__setitem__('image_sha256','0'*64))
bad_request('reject bound image mismatch',lambda x:x['c1_binding'].__setitem__('image_sha256','0'*64))
bad_request('reject outside snapshot boundary',lambda x:x['inputs'].__setitem__('c1','C:/other/c1.json'))
bad_request('reject path traversal',lambda x:x['inputs'].__setitem__('c1','C:/m1-offline/attempt-vlm-001/../c1.json'))
bad_request('reject relative C1',lambda x:x['inputs'].__setitem__('c1','c1.json'))
bad_request('reject outputs collision',lambda x:x['outputs'].__setitem__('sidecar',x['outputs']['c2']))
x=copy.deepcopy(OCR_REQ);x['inputs']={'c1':'C:/x/c1.json'}
check('reject VLM fields on OCR',lambda:request(x,'C:/m1-offline/attempt-ocr-001'),True)
def bad_side(name,edit,idx=0,reg=REG):
 e=copy.deepcopy(examples[idx]);edit(e['sidecar']);check(name,lambda:sidecar(e['sidecar'],e['c2_fixture_file'],reg),True)
bad_side('reject unknown Sidecar root',lambda x:x.__setitem__('contract_status','candidate'))
bad_side('reject null clothing',lambda x:x['observations'][0]['appearance'].__setitem__('clothing',None))
bad_side('reject empty clothing',lambda x:x['observations'][0]['appearance'].__setitem__('clothing',''))
bad_side('reject whitespace clothing',lambda x:x['observations'][0]['appearance'].__setitem__('clothing',' '))
bad_side('reject integer calibrated',lambda x:x['observations'][0]['confidence'].__setitem__('calibrated',1))
bad_side('reject unavailable calibrated true',lambda x:x['observations'][0]['confidence'].__setitem__('calibrated',True))
bad_side('reject unavailable numeric value',lambda x:x['observations'][0]['confidence'].__setitem__('value',0.5))
bad_side('reject missing estimate value',lambda x:x['observations'][0]['confidence'].pop('value'),4)
bad_side('reject bool estimate',lambda x:x['observations'][0]['confidence'].__setitem__('value',True),4)
bad_side('reject out-of-range estimate',lambda x:x['observations'][0]['confidence'].__setitem__('value',1.1),4)
bad_side('reject unknown calibration evidence',lambda x:x['source'].__setitem__('evidence_ref','model-self-asserted'),5)
bad_side('reject model calibration mismatch',lambda x:x['source'].__setitem__('model_ref','self-declared'),5)
bad_side('reject real mode offline',lambda x:x['source'].__setitem__('component_mode','real'))
bad_side('reject prompt hash mismatch',lambda x:x['source'].__setitem__('prompt_sha256','0'*64))
bad_side('reject missing observations',lambda x:x.pop('observations'))
bad_side('reject null observations',lambda x:x.__setitem__('observations',None))
bad_side('reject foreign object',lambda x:x['observations'][0].__setitem__('object_id','book01_p04_o01'))
bad_side('reject nested private unknown',lambda x:x['observations'][0]['appearance'].__setitem__('hair','invented'))
bad_side('reject canonical identity',lambda x:x['observations'][0].__setitem__('canonical_id','person1'))
bad_side('reject C2 raw hash mismatch',lambda x:x['c2'].__setitem__('sha256','0'*64))
bad_side('reject old Sidecar generation',lambda x:x.__setitem__('generation_id','old'))
check('reject nonzero exit with success result',lambda:result(read('WORKER_RESULT_EXAMPLE.json'),VLM_REQ,1),True)
x=read('WORKER_RESULT_EXAMPLE.json');x['detail']={}
check('reject result unknown detail',lambda:result(x,VLM_REQ),True)
check('reject duplicate JSON key',lambda:strict_load('{"x":1,"x":2}'),True)
check('reject nonfinite JSON',lambda:strict_load('{"x":NaN}'),True)

# AST evidence verifies retry scope without executing the Supervisor.
s=next(e for e in lock if e['id']=='M1:orchestrator/services/vision_supervisor/supervisor.py')
tree=ast.parse((OUT/s['locked_copy']).read_bytes())
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Supervisor')
run=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_run')
check('source stage run loop is exactly (1,2)',lambda:next(ast.literal_eval(n.iter) for n in ast.walk(run) if isinstance(n,ast.For) and isinstance(n.iter,ast.Tuple))==(1,2) or (_ for _ in ()).throw(AssertionError('retry limit')))
def normalize(items):
 items=copy.deepcopy(items)
 for item in items:
  if Path(item['path']).name=='space-m1-m2-v12-supervisor':
   item['status']['out']='\n'.join(line for line in item['status']['out'].splitlines() if not line.startswith('?? reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/'))
 return items
# Only new files under this exact authorized output prefix are excluded.
after=snapshot(); before=read('audit/CHECKOUT_BEFORE.json')
check('nine checkout Git states and diffs preserved',lambda:normalize(after)==normalize(before) or (_ for _ in ()).throw(AssertionError('checkout drift')))
(OUT/'audit/CHECKOUT_AFTER.json').write_text(json.dumps(after,ensure_ascii=False,indent=2),encoding='utf-8')
report={'scope':'static contracts and side-effect-free frozen-model/Gate.refs checks; not Worker integration or provider execution','validator':'standard-library strict subset validator; full emitted keyword subset checked; not an independent complete JSON Schema engine','filesystem_scope':'synthetic paths checked lexically only; link/junction/hardlink, TOCTOU and OS confinement remain later behavioral checks','freshness_scope':'trusted expected OCR identity supplied as test context; not independently authenticated by wire JSON','passed':sum(r['pass'] for r in results),'failed':sum(not r['pass'] for r in results),'results':results,'examples':len(examples),'provider_calls':0,'worker_launches':0}
(OUT/'audit/VALIDATION_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('TOTAL',report['passed'],'passed;',report['failed'],'failed')
assert report['failed']==0
