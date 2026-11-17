"""One-shot formal document authoring. No M1/M2 runtime imports or Git writes."""
from pathlib import Path
import ast,copy,hashlib,importlib.util,json,re,shutil,sys,zipfile
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
OLD=ROOT/'reports/M1_M2_PROTOCOL_V1_0_DECISION_PACKAGE'
M1=ROOT/'space-m1-m2-v12-supervisor'
ORDER=Path(r'C:\Users\16173\.codex\attachments\93133bfa-ad9f-49b5-9312-32f67a1c37a7\已粘贴的文本.txt')
def sha(b):return hashlib.sha256(b).hexdigest()
def dump(n,x):write(n,json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def write(n,s):
 p=OUT/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(s,encoding='utf-8',newline='\n')
def load(n):return json.loads((OLD/n).read_text(encoding='utf-8'))
spec=importlib.util.spec_from_file_location('_prior_readonly_support',OLD/'build_support.py');support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
assert not (OUT/'SOURCE_LOCK.json').exists(),'Never overwrite a delivered protocol'
before=support.snapshot();dump('audit/CHECKOUT_BEFORE.json',before)
inputs={}
for label,p,expected in [('DECISION',OLD.with_suffix('.zip'),'cb92be5dd6e1151ba5372d592ddd0f727a0ec1f14e8b062fa8a09b6666b6f61c'),('M1',support.M1ZIP,'8d79406711b4619e5c2dcd2e0917f6c6668e58cb5f8e08c626d9590ae5a61bcf'),('M2',support.M2ZIP,'3446b03bae8993a21e5cbff5f2ae639d8a4c43bfb08ca003f35b2957d6c1e505')]:
 raw=p.read_bytes();assert sha(raw)==expected
 with zipfile.ZipFile(p) as z:
  assert z.testzip() is None;names=z.namelist();seen=set()
  for n in names:
   assert not n.startswith('/') and '..' not in Path(n).parts and ':' not in n and '\\' not in n and n.casefold() not in seen;seen.add(n.casefold())
  manifest=next(n for n in names if n.endswith('MANIFEST.sha256'));prefix=manifest[:-len('MANIFEST.sha256')];count=0;listed=set()
  for l in z.read(manifest).decode('utf-8-sig').splitlines():
   if not l.strip() or l.startswith('#'):continue
   m=re.fullmatch(r'([0-9a-f]{64})\s+(?:(\d+)\s+)?(.+)',l);assert m
   h,size,n=m.groups();b=z.read(prefix+n);assert sha(b)==h and (size is None or len(b)==int(size));count+=1;listed.add(prefix+n)
  assert set(n for n in names if not n.endswith('/'))==listed|{manifest}
  if label=='DECISION':
   for n in names:assert (OLD/n).read_bytes()==z.read(n),n
  inputs[label]={'path':str(p),'sha256':sha(raw),'CRC':'PASS','manifest_entries':count,'files':len(names),'paths':'PASS'}
dump('audit/INPUT_VERIFICATION.json',inputs)
locks=load('SOURCE_LOCK.json')
for e in locks:
 raw=(OLD/e['locked_copy']).read_bytes();assert sha(raw)==e['sha256']
 if e['source_checkout']:assert sha((Path(e['source_checkout'])/e['source_relative_path']).read_bytes())==e['sha256']
 p=OUT/e['locked_copy'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
 e['formal_sections']=e.pop('protocol_sections')
(OUT/'OWNER_EXECUTION_ORDER.txt').write_bytes(ORDER.read_bytes())
locks.append({'id':'OWNER_ORDER','source_relative_path':ORDER.name,'source_checkout':None,'branch':None,'HEAD':None,'tracking_status':'USER_AUTHORIZATION_ATTACHMENT','tracked':None,'sha256':sha(ORDER.read_bytes()),'locked_copy':'OWNER_EXECUTION_ORDER.txt','formal_sections':['F01','F02','F03','F04','F05','F06','F07','F08'],'source_attachment':str(ORDER)})
dump('SOURCE_LOCK.json',locks)
evidence={}
def ev(k,symbol,source_id,sections):
 e=next(e for e in locks if e['id']==source_id);b=(OUT/e['locked_copy']).read_bytes();lines=b.decode('utf-8-sig').splitlines()
 if symbol=='MODULE':lo,hi=1,len(lines)
 elif isinstance(symbol,tuple):lo=next(i for i,l in enumerate(lines,1) if symbol[0] in l);hi=next(i for i,l in enumerate(lines,1) if i>=lo and symbol[1] in l)
 else:
  nodes={}
  def visit(node,prefix=''):
   for c in ast.iter_child_nodes(node):
    if isinstance(c,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
     name=prefix+c.name;nodes[name]=c;visit(c,name+'.')
  visit(ast.parse(b));n=nodes[symbol];lo=min([n.lineno]+[d.lineno for d in getattr(n,'decorator_list',[])]);hi=n.end_lineno
 evidence[k]={'source_id':source_id,'file':e['source_relative_path'],'line_start':lo,'line_end':hi,'sha256':e['sha256'],'source_checkout':e['source_checkout'],'branch':e['branch'],'HEAD':e['HEAD'],'locked_copy':e['locked_copy'],'sections':sections}
# Recompute all prior AST ranges from exact source bytes; no inherited line offsets.
for k,e in load('audit/LINE_EVIDENCE.json').items():
 p=OUT/e['locked_copy'];b=p.read_bytes();tree=None
 if p.name.endswith('.py.txt'):
  nodes=[]
  def walk(node):
   for c in ast.iter_child_nodes(node):
    if isinstance(c,(ast.FunctionDef,ast.ClassDef,ast.AsyncFunctionDef)):
     nodes.append(c)
    walk(c)
  tree=ast.parse(b);walk(tree)
  matched=[n for n in nodes if n.end_lineno==e['line_end'] and min([n.lineno]+[d.lineno for d in getattr(n,'decorator_list',[])])==e['line_start']]
  if matched:
   n=matched[0];lo=min([n.lineno]+[d.lineno for d in getattr(n,'decorator_list',[])]);hi=n.end_lineno
  else:lo,hi=1,len(b.decode('utf-8-sig').splitlines());assert e['line_start']==lo and e['line_end']==hi
 else:
  # Re-resolve public document anchors explicitly.
  lines=b.decode('utf-8-sig').splitlines()
  if k=='API_OVERVIEW':lo=hi=next(i for i,l in enumerate(lines,1) if '| 9001 |' in l)
  elif k=='API_RETRY':lo=next(i for i,l in enumerate(lines,1) if '## 1.13' in l);hi=next(i for i,l in enumerate(lines,1) if '**重试白名单**' in l)
  else:lo,hi=1,len(lines)
 evidence[k]={**e,'line_start':lo,'line_end':hi}
ev('M2_ENVELOPE','WorkerOutcome.envelope','M2:src/vision/worker.py',['F02','F08'])
ev('M2_IDENTITY','_validate_identity','M2:src/vision/worker.py',['F02','F03'])
ev('M2_OUTPUTS','_outputs_for','M2:src/vision/worker.py',['F02'])
ev('M2_FINISH','_finish','M2:src/vision/worker.py',['F08'])
ev('APPROVAL','MODULE','OWNER_ORDER',['F01','F02','F03','F04','F05','F06','F07','F08'])
dump('audit/LINE_EVIDENCE.json',evidence)
def cite(*ids):
 return '\n\n'.join(f"[{k}]({(OUT/evidence[k]['locked_copy']).as_posix()}:{evidence[k]['line_start']}) — {evidence[k]['file']} L{evidence[k]['line_start']}–{evidence[k]['line_end']}；SHA256 `{evidence[k]['sha256']}`；checkout `{evidence[k]['source_checkout'] or 'UNKNOWN / archive or user attachment'}`；branch `{evidence[k]['branch'] or 'UNKNOWN'}`；HEAD `{evidence[k]['HEAD'] or 'UNKNOWN'}`；章节 {','.join(evidence[k]['sections'])}" for k in ids)
def doc(n,title,body,refs):write(n,f'# {title}\n\n协议：M1_M2_OFFLINE_PROTOCOL_V1.0 · FROZEN · OWNER_APPROVED · 2026-11-13\n\n仅限 Fake/Stub 离线接口。协议冻结不等于代码符合性验收；禁止本任务改核心源码、联调或发布 dev。\n\n{body}\n\n## 规范性授权与实现证据\n\n'+cite('APPROVAL',*refs)+'\n')

# Preserve approved existing wire names; add no retry/authentication/prompt wire field.
schemas=load('PRIVATE_CONTRACT_SCHEMAS.json');schemas.pop('$comment',None)
binding=load('C1_BINDING_SCHEMA.json');binding['$id']='urn:m1-m2:offline:1.0:c1-binding';binding['$comment']='FROZEN/OWNER_APPROVED. Structural schema only; file handle, freshness, hashes and cross-document rules require contextual verification.'
schemas['VLM_REQUEST']['properties']['c1_binding']=copy.deepcopy(binding)
def official_schema(body,id):return {'$schema':'https://json-schema.org/draft/2020-12/schema','$id':id,'$comment':'M1_M2_OFFLINE_PROTOCOL_V1.0 FROZEN OWNER_APPROVED; context requirements are normative in FIELD_CONTRACT and protocol documents.',**body}
dump('C1_BINDING_SCHEMA.json',binding)
dump('REQUEST_SCHEMA.json',official_schema({'oneOf':[schemas['OCR_REQUEST'],schemas['VLM_REQUEST']]},'urn:m1-m2:offline:1.0:request'))
dump('WORKER_RESULT_SCHEMA.json',official_schema(schemas['WORKER_RESULT'],'urn:m1-m2:offline:1.0:result'))
dump('SIDECAR_SCHEMA.json',official_schema(schemas['SIDECAR'],'urn:m1-m2:offline:1.0:sidecar'))
dump('PRIVATE_CONTRACT_SCHEMAS.json',{'$comment':'Frozen internal validation views, equivalent to the standalone schemas.',**schemas})
for n in ['C1_BINDING_EXAMPLE.json','OCR_REQUEST_EXAMPLE.json','VLM_REQUEST_EXAMPLE.json','WORKER_RESULT_EXAMPLE.json']:(OUT/n).write_bytes((OLD/n).read_bytes())
shutil.copytree(OLD/'fixtures',OUT/'fixtures')
# Replace the obsolete single-string prompt and synthetic calibration acceptance.
for n in ['FINAL_PROMPT_UTF8.txt','CALIBRATION_EVIDENCE.json']:(OUT/'fixtures'/n).unlink()
messages=[{'role':'system','content':'Offline synthetic fixture only.\nDo not trim. '},{'role':'user','content':'合成消息：已替换文本参数 page=book01_p03。\n保留空格  '}]
canonical=json.dumps(messages,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
(OUT/'fixtures/FINAL_MESSAGES_CANONICAL.bin').write_bytes(canonical)
dump('fixtures/FINAL_MESSAGES.json',messages)
prompt_hash=sha(canonical)
registry=load('fixtures/EVIDENCE_REGISTRY.json')
for r in registry.values():
 for k in ['calibration_file','calibration_sha256','authorized_calibrated_observation_ids','prompt_file']:r.pop(k,None)
 r.update(prompt_file='fixtures/FINAL_MESSAGES_CANONICAL.bin',prompt_sha256=prompt_hash,calibration_registry_status='NOT_IMPLEMENTED_NO_VERIFIED_CALIBRATION',dispatch_status='NOT_EXECUTED; canonical Adapter-boundary bytes only')
dump('fixtures/EVIDENCE_REGISTRY.json',registry)
examples=load('SIDECAR_EXAMPLES.json')
examples['container_note']='Test fixture wrapper only; each sidecar is the wire example. No accepted calibrated=true example until an independent M5 registry is operational.'
for e in examples['examples']:
 e['sidecar']['source']['prompt_sha256']=prompt_hash
 for o in e['sidecar']['observations']:o['confidence']['calibrated']=False
 if 'calibrated synthetic' in e['name']:e['name']='Uncalibrated estimate pending independent M5 evidence'
dump('SIDECAR_EXAMPLES.json',examples)
dump('PROMPT_HASH_EXAMPLE.json',{'fixture_only':True,'adapter_invoked':False,'messages_file':'fixtures/FINAL_MESSAGES.json','canonical_file':'fixtures/FINAL_MESSAGES_CANONICAL.bin','prompt_sha256':prompt_hash,'attachments':[{'message_index':1,'fixture_file':'fixtures/IMAGE_HASH_FIXTURE.bin','raw_sha256':sha((OUT/'fixtures/IMAGE_HASH_FIXTURE.bin').read_bytes()),'kind':'synthetic_binary_hash_fixture_not_decoded_image'}]})

doc('OWNER_APPROVAL_RECORD.md','负责人批准记录','批准方：项目负责人。批准日期：2026-11-13。批准依据为随包保存的 OWNER_EXECUTION_ORDER.txt 原字节及其 SHA256。F01–F08 全部 OWNER_APPROVED；F03 文件安全、F05 确定性有序消息 JSON、F08 每 Stage 两次总 Attempt 跨进程持久化三项补充一并批准。范围仅离线 Fake/Stub 协议定义。不是个人数字签名或供应商认证；不包含真实模型、收费 POC、生产、dev，也未授权改核心代码。',['REQUEST','RETRY'])
decisions=[('F01','唯一标识、优先级、协议变更必须升版重新签认',['PUBLIC_OCR','PUBLIC_VLM']),('F02','五种结构严格类型/键集/版本/重复键/非有限数；仅管理私有对象',['REQUEST','IDENTITY','JSON','M2_ENVELOPE']),('F03','不可变快照、分离 OCR/VLM attempt；组件/真实路径/句柄/文件身份/硬链接/替换/TOCTOU',['BOUND_C1','PATH','M2_C1_PATH','M2_BINDING']),('F04','服装不编造；calibrated=true 须独立模型版本/数据集/方法证据，登记未完成前不得接受',['SIDECAR','M2_REFS']),('F05','最终有序 role/content 消息固定字段顺序 JSON UTF-8 无 BOM/空白/trim，二进制独立关联',['M2_PROMPT','M2_RENDER','FIXTURE']),('F06','observations 必需数组，成功可空；失败/不完整不能冒充空成功；M5 准确率',['SIDECAR','PUBLIC_VLM']),('F07','Profile A 优先、B 独立；不得拼为已认证统一链；只实际 allowlist',['LEASE_ENTRY','LEASE_RUN','SPEC','M2_ENTRY']),('F08','每 job/page/generation/revision/epoch/stage 最多两次总 Attempt，原子持久化且跨重启；2004 精确标识而非仅数值',['RETRY','UNKNOWN','LOOKUP','JOB_STATE'])]
write('PROTOCOL_DECISION_REGISTER.md','# 正式决策登记册\n\n全部 OWNER_APPROVED，协议 FROZEN；代码符合性独立登记，不从批准推导实现完成。\n\n'+'\n\n'.join(f'## {f} — OWNER_APPROVED\n\n正式决定：{t}。当前实现证据：见下方；差异与责任/整改/测试见 CONFORMANCE_GAP_REGISTER。验证为本包静态规则案例；执行验收 BLOCKED。\n\n'+cite('APPROVAL',*refs) for f,t,refs in decisions))
doc('M1_M2_OFFLINE_PROTOCOL_V1.0.md','M1/M2 正式离线协议 V1.0','''
F01 身份 M1_M2_OFFLINE_PROTOCOL_V1.0，FROZEN / OWNER_APPROVED。规范优先级：冻结公共 API/C1/C2 > 本正式协议 > 锁定 M1 实现证据 > 历史 M1 Handoff > 历史 M2 Worker Interface。实现不符合时登记 Gap，不反改规范。任何 wire 字段/语义/枚举/状态变更须升版、重新签认。wire 常量仍 m1-vision-worker/0.1、vision_refs/0.1；本批准身份不添加为 wire 字段。

F02 全部私有结构定义在 REQUEST_SCHEMA、WORKER_RESULT_SCHEMA、C1_BINDING_SCHEMA、SIDECAR_SCHEMA 和 FIELD_CONTRACT；Schema 管结构，原字节/hash/文件安全/证据/跨文档规则由规范文本约束。必需字段缺失、非法 null/类型/未知键/版本/重复键/NaN/Infinity/无效 Unicode 一律拒绝。不得对 public C1/C2 擅自增加 extra=forbid 或改变冻结模型。

F03 M1 分配可信快照和 attempt；M2 只消费给定 stage。五元相同；OCR/VLM attempt/token 分离，来自 M1，不要求相等。路径、句柄、Hash、TOCTOU 的全部正式要求见 FILE_SECURITY_BOUNDARY，不把词法演示当 OS 实现。

F04 appearance={} 合法，clothing 可缺、不可 null/空白或编造。unavailable.value 可缺/null，calibrated=false；估计值有限 [0,1]，calibrated 原生 bool。true 需独立可复核的实际模型版本/数据集/方法注册证据；当前 M5 机制未完成，故本轮不得接受 true 为已验证。禁止用模型自述或合成玩具证据冒充真实校准。

F05 prompt_sha256 是确定性序列化的最终有序消息列表 Hash，详见 PROMPT_HASH_SPECIFICATION。本次明确替换旧草案 system+LF+user 的做法，不改变字段名；模板/请求 Hash 不得混同。

F06 observations 必需数组；执行成功可为 []，缺字段、失败、不完整、损坏皆不是成功空结果。C2.objects=[] 须 status=empty；有 C2 objects 可以没有参考观察，Schema 不承诺检测全覆盖。M5 负责真实准确率。

F07 A 优先准备，B 独立；实际链未认证不冒称具备接口准入。环境只来源锁定 allowlist；现有 M2 入口/依赖/Stub 安全与严格协议仍待单独验收。F08 见 ERROR_RETRY_STATE_MATRIX：每逻辑 Stage 两次总尝试且跨重启持久化是正式要求，当前内存 loop 不满足。

本协议只冻结定义。后续代码整改、Fake/Stub 联调、生产或 dev 必须经过各自准入。本次不修改核心源码，不创建提交/PR，不启动联调，不推 dev。
''',['REQUEST','SIDECAR','PUBLIC_OCR','PUBLIC_VLM','RETRY','LEASE_ENTRY'])

# Generate exhaustive field documentation from the precise approved schema properties.
table=['|对象/字段|类型/枚举|必需|null/默认|语义/责任/失败|','|---|---|---|---|---|']
def fields(s,path,owner):
 for k,v in s.get('properties',{}).items():
  typ=v.get('type','const '+str(v['const']) if 'const' in v else str(v.get('enum','object')))
  required=k in s.get('required',[])
  nullable='null' in (v.get('type') if isinstance(v.get('type'),list) else [])
  default='缺省 false' if k=='transient' else ('可省略；无自动填值' if not required else '无默认')
  table.append(f'|{path}.{k}|{typ}|{required}|'+('可 null' if nullable else '不可 null')+f'；{default}|{owner}；错则拒绝，不自动 coercion|')
  fields(v,path+'.'+k,owner)
  if 'items' in v:fields(v['items'],path+'.'+k+'[*]',owner)
for k,s in schemas.items():fields(s,k,'M2 验 Request/Binding；M1 验 Result/Sidecar')
doc('FIELD_CONTRACT.md','逐字段完整契约','\n'.join(table)+'''

附加语义：Request.outputs 两个 stage 都恰 c1/c2/sidecar，精确 json/{page}_ocr.json、json/{page}_vlm.json、json/{page}_refs.json；result_path=result.json。OCR 无 inputs/binding，VLM 必有 inputs.c1 和 binding。身份字符串非空且不透明，revision/epoch 原生 int>=1，bool/1.0 拒绝。binding.identity 为 OCR 身份，五元与 VLM 相同，token 非认证密钥。image_path 和 c1 绝对且属于授权 attempt 根；产物相对且受 M1 分配，不能碰撞。

Result.code 原生 int；msg 原生 str 可空；identity 恰七键并同 type/value。成功 artifacts：OCR 恰 c1，VLM 恰 c2/sidecar；错误 artifacts={}，3001 OCR合法 empty 例外恰 c1。transient 缺省 false，其存在不授予 retry。Result 顶层 detail 未声明，必须拒绝。缺 result/结构/identity/path/Hash/Gate 错，M1 拒绝成功；M2 无法验证可信请求时只能拒绝并尽力写已批准错误 envelope，不回显秘密。

Sidecar 根 identity 七元扁平；禁止 identity 镜像、contract_status/c1_sha256 扩展。source.component_mode 离线 fixture/stub（全来源词汇 real 本范围禁用）；c2.raw SHA/path 及 object 归属必须匹配。appearance{} 不是 null。confidence.kind=unavailable 时 value 缺/null且 calibrated=false；model_estimate 时 value 必需有限原生数 [0,1]，bool拒绝。clothing 不能空白，不得虚构；calibrated=true 当前证据机制未完成而不接受。观测 ID 唯一，object_id 属于本 C2，禁止 canonical 身份。引用真实有效性是外部证据校验，不能只靠非空字符串。

所有 optional 只限表列字段，未声明者不是 optional 而是 unknown。PUBLIC 模型默认值仍依冻结实现。语义/上下文失败不等于 JSON Schema 已证明 OS 安全；不能凭 envelope 模拟旧 binding 认证。
''',['REQUEST','IDENTITY','SIDECAR','BOUND_C1','M2_ENVELOPE'])
doc('FILE_SECURITY_BOUNDARY.md','文件安全与 TOCTOU 边界','''
F03 正式要求。M1 授权的根来源于受信 attempt 分配，不从 M2 自报路径推导。M2 输入 c1 必须是绝对的本次根/c1.json；图像也来自该根。先做词法校验（拒绝 ..、非法盘符/ADS、分配外路径），然后解析真实路径并按路径组件边界确认位于根；不可使用字符串前缀。

检查根及每一级组件，拒绝 symlink；Windows 拒绝未经授权 Reparse Point/Junction。本离线 profile 没有授权 Reparse allowlist，故所有遇到的 Reparse Point 均拒绝。不可把最终文件 is_symlink 检查替代祖先组件检查。输出不允许逃逸、路径碰撞或复用别的 attempt。

通过 OS no-follow/open-relative 或具有等效保证的受信句柄流程打开文件；验证句柄对应的普通文件身份（Windows volume/file ID 或 Unix device/inode）、授权根和组件，记录链接计数。硬链接必须证明单一受授权文件身份且 nlink=1；无法证明则拒绝/明确不支持平台。尽量同一已验证句柄读取与计算原始字节 SHA256；本 profile 必须消费这次读取的 bytes，禁止验证后重新按路径打开另一个文件。

读取前后核对句柄身份、大小/元数据及必要的父目录/路径映射，检测验证后替换；采用锁定、共享模式或等效机制防止写入与替换，证明 bytes 对应受信不可变快照。若属性不可靠或无法给出等效安全证明，fail closed，不声称 TOCTOU 已防护。路径验证、真实路径、句柄验证、原字节 Hash、TOCTOU 分为五层分别记录验收；Hash 只证明所读 bytes，不证明路径/来源可信。

C1/image Hash 与 snapshot/binding 相等，C1 五元与当前任务相同，OCR attempt/token 与 M1 快照台账相同；OCR/VLM 分别由 M1 创建新 identity，不强行要求相等。拒绝跨 page/revision/generation/epoch 或旧 OCR attempt。M2 单凭可整体伪造 JSON 无法自行认证新鲜度，依赖 M1 可信通道和台账。禁止扫描更新 C1、跨 attempt 取文件及 VLM 隐式补 OCR。

当前 M1 confined_file 有 resolve/链接/硬链接检查，但 stat 后 read_bytes 重新按路径读取，没有完整同句柄替换防护证据；M2 _resolve_c1_path 未证明授权根约束和祖先所有 Reparse/句柄/TOCTOU。均为 P1 实现差异。本文定义规范；本轮仅词法/静态案例，没有真实 OS 安全验收。
''',['PATH','REQUEST','BOUND_C1','M2_C1_PATH','M2_BINDING'])
doc('PROMPT_HASH_SPECIFICATION.md','确定性 Final Prompt Hash','''
F05 正式输入是实际提交给 Provider Adapter 的最终有序消息列表，而非模板或 HTTP 请求。每项精确 {role, content}，两个字段按 role 后 content 固定顺序；本 V1.0 记录文本消息，role/content 都为有效 Unicode 原生字符串，role 是实际非空角色，不擅自改写或限制成不真实的角色。content 包含全部模板替换结果和实际文本参数，可空且不 trim、不做 NFC/NFD 规范化、不改变 CR/LF或消息顺序。

固定序列化：UTF-8，无 BOM；ensure_ascii=false，separators=(',',':')，allow_nan=false；数组顺序原样，字段顺序固定 role,content；采用 JSON 标准必要转义；拒绝未配对 surrogate、重复键、额外字段、非字符串、NaN/Infinity。输入列表非空。禁止用 system+LF+user 拼接替代列表（旧草案已被本批准补充取代）。对这些精确 bytes 做 SHA256 得小写64 hex，与 Sidecar.source.prompt_sha256 相同。

本 V1.0 附件通过独立受信 evidence manifest 记录 message_index、原始二进制 SHA256、媒体类型/引用和消息关联，不把二进制放入 prompt hash，也不添加 public C1/C2 或 Sidecar wire 字段。多模态非文本 content 形状当前未定义，不能静默转成字符串；如需新的 content 类型必须升版和重新签认。附件示例是合成 Hash bytes，不是真实绘本/可解码图片。

Prompt Template Hash 只哈希模板；Final Prompt Hash 只哈希上述最终消息；Provider Request Hash 若另记则哈希最终请求 envelope 并单独命名，不能代用。API Key/Token/Secret 不进入消息、证据或日志；测试不读取实际秘密。不得声称算法能识别任意自由文本中的秘密，调用方负责在提交前阻止秘密进入 prompt。

Hash 证明范围止于应用交给 Adapter 的精确有序消息。SDK 后续不可观察转换、Provider 内部处理和真实调用都不由此证明。fixture/stub 没有调用时标记 adapter_invoked=false；不得把保存消息示例当提交回执。prompt fixture 可复算，含尾部空格和换行以证明无 trim。现 M1 fixture hash(no model)、Gate 只验格式，M2 _prompt_sha256 哈希模板或 b'stub'，皆不满足正式语义，记 P1。
''',['SIDECAR','M2_PROMPT','M2_RENDER','FIXTURE'])
doc('RUNTIME_PAIRING_MATRIX.md','Profile A 优先、Profile B 独立',f'''
|项|Profile A 接口准备|Profile B 资源测试|
|---|---|---|
|Core|无 SQLite Core；vision_supervisor.supervisor.Fences 是内存 Page registry|mock_core_round2.lease_core.Core|
|Supervisor|vision_supervisor.supervisor.Supervisor|mock_core_round2.lease_supervisor.Supervisor|
|Runner|Supervisor.run；完整接口编排候选 VisionPipeline.run，downstream/verify 需受审 Fake|mock_core_round2.lease_runner.run_mock；类型必须精确配对|
|Worker|锁定 ZIP scripts/m2_vision_worker.py -> vision.worker.main，非当前 M1 fixture 冒充|已存在本地 m1_vision_worker fixture，不等于 M2 接入|
|Provider|M2 factory 默认 Stub；只 process_tree、backend=None；实际兼容和 SDK retry 仍待审|精确 FakeProvider，不接受真实 provider|
|cwd|本次私有 attempt 根|本次私有 attempt 根；SQLite 新建独立测试库|
|argv|[受审 Python 绝对路径, 隔离解包根/paperbook-ai/scripts/m2_vision_worker.py, 本次 request.json绝对路径]|[Python,-I,锁定 M1 fixture绝对路径,--mode,ok,--code,2002,--message,transient,本次 request.json]|
|产物|result.json；OCR c1；VLM c2+sidecar；Gate 接受后 Handoff 原字节，禁止目录扫描|视觉 Snapshot+Mock 下游；不是生产媒体|

当前已有解释器路径 `{sys.executable}`，M1 fixture 路径 `{M1/'orchestrator/tests/fixtures/m1_vision_worker.py'}`。M2 仍为 archive-only，未获准解包/安装或选择实际隔离根，因此不存在可诚实列出的已验证完整 M2 argv；占位项是规范参数，不是已执行命令。M2 CLI 实际精确一个 request 参数，不能传新参数强行接线。Profile A 执行接入 BLOCKED，协议和输入已有规范但代码不符合。B 独立保留，不与 A 拼成生产链。

超时来自 Supervisor 构造参数 deadline (0,30]，backoff=1；所有 retry 权威在 M1。新的跨进程 Stage attempt ledger 尚未满足；本包只定义。发布须先退出/排空、所有原字节 hash/Gate/fences 合法、可信 verify 后 atomic pointer；完整 M2+LEASE 生产链 NOT_CERTIFIED。
''',['SPEC','REQUEST','PIPELINE','PUBLISH','LEASE_ENTRY','LEASE_RUN','RUNNER','M2_ENTRY','M2_FACTORY','FIXTURE_ARGV'])
doc('ENVIRONMENT_ALLOWLIST.md','环境变量逐项规则','''
|名称|来源/默认|继承|业务注入|敏感|Profile|
|---|---|---|---|---|---|
|SystemRoot,WINDIR,COMSPEC,SYSTEMDRIVE|父环境存在才复制|是，仅这些键|不作为业务自由注入|系统配置|A/B|
|PATH|argv[0]目录 + os.defpath|不继承父 PATH|否|非秘密|A/B|
|PYTHONDONTWRITEBYTECODE|固定1|否|否|否|A/B|
|PYTHONIOENCODING|固定utf-8|否|否|否|A/B|
|TEMP,TMP,TMPDIR|当前 attempt 根|否|否|路径不输出秘密|A/B|
|HOME,USERPROFILE,XDG_CACHE_HOME,HF_HOME,PADDLE_HOME|固定 work/cache|否|否|用户路径|A/B|
|VISION_BACKEND|通用代码无默认，仅 WorkerSpec 显式配置|否|通用A allowlist可用，正式离线参考配置为空|配置|A；B禁|
|VISION_MODEL|同上|否|同上|模型路径配置|A；B禁|
|VISION_BASE_URL|同上|否|同上，离线不注入真实端点|端点可能敏感|A；B禁|
|VISION_API_KEY|同上|否|通用代码有能力；本次离线不使用/不读取|是，禁止输出值|A；B禁|

B 入口要求 environment=()，四个业务键也拒绝。A 的本次离线注册同样空 environment；表中的能力不授权真实服务。未知键/重复键启动前拒绝；不添加 VISION_OCR_BACKEND/VISION_VLM_BACKEND/QWEN_VL_*/M2_*/PADDLE_* 等新放行项。PADDLE_HOME 是固定缓存键而非自由注入。M2 工厂依赖自己的环境名且默认 stub，不得用此扩张 M1 allowlist；依赖导入/Stub安全门禁仍待真实离线兼容审查。stdout/stderr 不应泄露秘密。环境目录隔离不等于网络或全文件系统沙箱。
''',['REQUEST','SPEC','LEASE_RUN','M2_FACTORY','M2_HISTORY'])
doc('ERROR_RETRY_STATE_MATRIX.md','错误状态与持久化两次 Attempt','''
F08 正式计数键为 job_id/page_id/generation_id/input_revision/epoch/stage。OCR、VLM 分别最多两个总 Attempt：序号1首次，序号2唯一 retry。M1 原子预留、分配唯一 attempt/token，并在提交前持久化；计数跨 Worker/Supervisor/进程崩溃重启保持。第三次、重复入口、并发争用必须在 dispatch 前拒绝。未知提交、预留后崩溃保守计为已消耗，不回收名额、不重置 loop。相同 attempt 的幂等查询不能造成新 dispatch。内部 ledger 是规范职责，不增加 wire retry_count 等字段。

持久化至少保证计数键唯一、ordinal唯一、attempt/token全局唯一、owner和dispatch状态原子提交；SQLite/其他存储细节不强制，但必须能证明跨进程互斥和恢复。unknown 保留 attempt 与资源，原 owner/key 对账，不重复投递。取消不恢复额度；新 generation 的合法授权不是给旧单元重置次数。现通用 Supervisor 每次 run 的内存 (1,2) 不满足此要求；LEASE 有执行/提交台账不等于已实现此 logical stage 原子总计数，登记 P1。

|条件|正式结果/重试|
|---|---|
|exit0/code0+有效 Result+Identity+完整产物/Hash+Gate|才可判正常成功，发布另须 fences/verify|
|缺 result、错身份/字段/Hash/路径|拒绝成功，1002 校验失败，无自动 retry|
|非零 exit但 code0|拒绝成功；现 M1 报2001且非transient|
|非零 error envelope，即使 exit0|仍为失败；错误 artifacts={}；不得解释为成功|
|3001 OCR合法 C1(empty)|保留明确非 retry empty 特例，可以非零 exit；缺合法 C1则1002；不是普通 code0成功|
|3004|Page blocked；SQLite Job failed/error='3004'；无 retry|
|9001|无 retry；精确白名单优先于公共概览|
|typed Cancelled(2004)/用户取消/旧fences|不自动 retry，不复活新代|
|transient 2004 envelope|必须有精确子类型/错误标识已在 M1 受审 allowlist；仅数值2004+transient不足|
|2001/2002/2003|transient=true、live fences、仍有剩余额度、可信终止/cleanup成功且退避1秒才可考虑；2001 msg含safety不重试|
|timeout|先有可信终止确认；失败隔离，禁止靠客户端超时推断终止|
|submission unknown|保留 lease，等待原 key/owner 对账，不自动重投|

当前锁定 retryable 对2004只有数值+transient，没有精确 subtype registry。因此本正式 V1.0 的2004可重试标识集合为空，fail closed；不发明新的 wire 字段或用自由 msg 子串伪装已批准子类型。以后新增标识须按协议变更流程明确签认。当前 M1 的更宽2004重试为差异，不能反向放宽正式规则。

状态分层：Worker idle/starting/running/draining/reaped/quarantined；Attempt 是身份及监管/ledger记录，非新增公开状态字段；Page queued/running/cancelled/blocked/failed/done；A 无SQLite Job，B失败为Job failed/error，pending stage skipped，cancel为cancelled，unknown可保持running待对账。不能把 Page blocked 当作已有 Job blocked 字段。

持久化验收计划：首次、唯一合法retry、拒绝第三次、Supervisor重启、进程崩溃、重复入口、并发重投、unknown、timeout/终止确认、typed cancellation、2004精确标识、9001、3004、3001。此包只跑独立静态参考状态演算，不启动 M1、不建立持久化库；不把演算通过当成真实跨进程实现。
''',['RETRY','RETRY_PREDICATE','CANCEL','REQUEST','LIMIT','UNKNOWN','LOOKUP','JOB_STATE','PIPELINE'])
doc('PUBLIC_API_RETRY_ERRATA.md','公共 API Retry 独立勘误','原件 docs/API_v1.0.md 的9001概览为“是”，§1.13精确白名单未含9001；本正式离线协议明确9001不重试，严格白名单优先。2004 typed cancellation无retry；transient envelope仍需精确受审子类型 allowlist，当前无此机制，正式集合为空。建议后续单独修订公开概览并说明分层，但本轮未编辑冻结公共 API，也不将协议解释升级为公共 Schema 变更。',['API_OVERVIEW','API_RETRY','RETRY_PREDICATE','CANCEL'])
doc('SIDECAR_GATE_MATRIX.md','完整 Gate 对照矩阵',(OLD/'SIDECAR_GATE_MATRIX.md').read_text(encoding='utf-8').split('## 锁定源码证据')[0].split('\n\n',2)[-1].replace('草案','正式协议').replace('true 需外部受审注册证据','true 需独立实际模型/数据集/方法证据；机制未完成前拒绝')+'\n\n未知私有字段禁止，真实来源/校准/文件安全/持久化计数不是当前 Gate.refs 已验证能力；单纯 Gate.refs 接受不代表正式协议合格。',['SIDECAR','GATE'])
doc('M1_M2_RESPONSIBILITY_BOUNDARY.md','M1/M2 责任边界','M1 创建可信 Request/Binding/快照、权威身份、文件授权根、持久化 Stage计数和所有 retry/fencing/取消/lease/对账；独立验证 Result、原字节产物、来源证据和 Gate，决定发布。M2 仅一次 assigned stage，严格消费输入，不生成新 attempt，不扫描目录/隐式OCR/SDK retry，不创建 canonical身份、不编造属性或校准证据。M5 独立评估真实绘本准确率/覆盖率与校准证据。负责人已批准协议，不等于批准核心整改、真实模型、生产或dev。',['REQUEST','BOUND_C1','SIDECAR','RETRY','UNKNOWN','PIPELINE'])

gaps=[
('G01','M1 Request Producer','私有严格键集/type/default','生成固定正常结构；不证明 wire消费者严格','process_request未全局拒绝额外键；顶层revision/epoch允许0','P1','Joint','M2增加严格输入验证；M1保留规范生成','REQUEST,M2_REQUEST,M2_IDENTITY','缺键/null/unknown/bool/0/版本'),
('G02','M1 C1 Snapshot','授权根/真实组件/同句柄/替换TOCTOU','快照bytes与图片hash存在；读取链无完整句柄证明','C1 path函数拒绝末端link但未证明受信根/祖先reparse/同句柄','P1','Joint','实现或证明OS属性，不能支持则拒绝','BOUND_C1,PATH,REQUEST,M2_C1_PATH','reparse祖先/替换竞态/硬链接/逃逸'),
('G03','M1 c1_binding','OCR七元+原C1/image hash+五元一致','producer字段形状匹配；无wire独立解析器','支持native亦保留扁平旧绑定/大小写宽松','P1','Joint','严格唯一binding格式和新鲜度责任','REQUEST,BOUND_C1,M2_BINDING','跨page/revision/generation/epoch/旧attempt'),
('G04','M1 Identity','正整数revision/epoch、M1唯一attempt','分配新attempt/token，Fences revision严格；dataclass不独立验证','顶层身份校验允许0，native binding另要求>=1','P1','M2','统一严格消费者约束；M1证实权威分配','IDENTITY,FENCES,M2_IDENTITY','0/bool/float/旧token'),
('G05','M1 Gate','未知字段拒绝、非空服装、证据真实','多数额外键允许、空服装允许、校准不验依据','build_refs有根扩展键与可配置null服装','P1','Joint','按正式协议适配Gate/producer及独立证据校验','SIDECAR,M2_REFS','unknown/null/empty/true无证据'),
('G06','M1 Sidecar','规范字段、来源/原字节C2 hash','Gate验hash/固定路径/类型，未验来源真实性','多写contract_status/identity/c1_sha256；raw hash正常构造','P1','M2','仅保留正式字段，保持原字节hash','SIDECAR,M2_REFS','根额外键、格式化后hash'),
('G07','M1 Supervisor','符合性安全/计数门禁齐备','进程监管/drain存在；无统一新增门禁证明','worker入口存在不等于整链验收','P1','M1','在新授权任务中补证明或适配','REQUEST,RETRY,M2_ENTRY','未终止禁止retry/lease不释放'),
('G08','M1 Runtime','Profile A确切消费者链、B独立','A与B各自候选路径；无已认证统一链','archive-only入口；依赖/默认stub安全/SDK retry未全审','P1','Joint','后续隔离兼容审查，禁止任意拼接','LEASE_ENTRY,LEASE_RUN,RUNNER,M2_FACTORY','固定argv/env/零真实网络'),
('G09','M1 Retry','每逻辑stage最多2次总attempt跨进程持久化','_run每次调用内存(1,2)，重入可重新计数；无原子总ledger','不应权威管理重试；SDK实际路径未全面认证','P1','M1','提交前持久预留、唯一约束、恢复及并发屏障','RETRY,FENCES,UNKNOWN','第三次/重启/崩溃/重复入口/并发'),
('G10','M1 Lease','unknown留资源、精确原key对账','LEASE有对应实现证据，仅离线Fake','不把客户端退出当后端停止；M2实际链未审','P2','Joint','保持B独立验证；不得借此声称A已具资源证明','UNKNOWN,LOOKUP,LEASE_ENTRY','unknown/旧owner/终态重复回执'),
('G11','M2 OCR Consumer','OCR输出分配三键，严格Request/文件安全','producer实际分配三键','_outputs_for仅取本stage必需键，额外键未整体拒绝','P1','M2','对完整request规范验证，不静默采用历史子集','REQUEST,M2_OUTPUTS,M2_REQUEST','OCR额外inputs/outputs未知键'),
('G12','M2 VLM Consumer','只assigned VLM，给定C1，严格边界','M1提前bound_c1','native消费给定C1，但旧格式/路径边界待适配；不是本轮全代码验收','P1','M2','严格格式和授权根/句柄流程，维持无隐式OCR','M2_BINDING,M2_C1_PATH,M2_REQUEST','缺C1即拒绝/不重做OCR'),
('G13','M2 C1 Binding Consumer','同F03，不允许旧绑定绕过','M1生产正常native结构','扁平兼容/hex大小写宽松、输入root缺证据','P1','M2','去掉未声明兼容，可信绑定台账和路径验证','M2_BINDING,M2_C1_PATH','旧OCR attempt/非绝对/原字节重排'),
('G14','M2 Sidecar Producer','只冻结字段、无无据calibrated true','Gate当前宽松','build_refs额外根键；null模式不兼容；无实际校准机制','P1','M2','严格输出、默认calibrated=false，M5机制前不接受true','M2_REFS,SIDECAR','unknown根/服装null/无校准证据'),
('G15','M2 Prompt Hash','最终消息列表确定性JSON hash','M1 Gate仅hex；fixture no model','模板SYSTEM+LF+USER或stub占位，不含最终替换有序消息','P1','Joint','在Adapter边界生成正式bytes/hash和附件关联','M2_PROMPT,M2_RENDER,FIXTURE','role/content/order/尾空格/附件关联'),
('G16','M2 Result','精确根字段、原生身份类型、产物一致','M1 result根宽松、identity严格','WorkerOutcome.envelope失败时可额外detail','P1','Joint','去未声明字段并独立验Result和产物','REQUEST,M2_ENVELOPE,M2_FINISH','detail/非零exit+code0/缺result'),
('G17','M2 错误处理','2004须精确subtype allowlist；9001/3004禁retry','retryable仅数值+transient可放2004','backend初始化映射2004 transient，未见独立受审subtype','P1','Joint','严格2004策略，保持typed cancel分离','RETRY_PREDICATE,CANCEL,M2_REQUEST','typed cancel/transient2004/9001/3004/3001'),
('G18','来源与评测','M2来源UNKNOWN不得伪造，M5证据独立','M1 current checkout哈希可追溯','仅ZIP来源，无可信branch/HEAD；全量SDK路径和M5未验','P2','Joint','保留UNKNOWN，后续补真实来源/准确率验收','M2_HISTORY,M2_ENTRY','不以历史仓库替代归档')]
body=['严重度表示接口准入差异，不是已证明生产事故。P0：本静态范围未确认；P1：阻断实际Profile A准入；P2：来源/范围限制。证据缺失与代码已证实差异分别明述；不把未审范围判通过。']
for gid,area,rule,m1,m2,sev,owner,change,refs,test in gaps:
 body.append(f'## {gid} {area}\n\n|字段|记录|\n|---|---|\n|Protocol Rule|{rule}|\n|Current M1|{m1}|\n|Current M2|{m2}|\n|Gap|未满足或未证明正式规则；以上具体行为为据|\n|Severity|{sev}|\n|Owner|{owner}|\n|Required Change|{change}|\n|Test|{test}|\n\n'+cite(*refs.split(',')))
doc('CONFORMANCE_GAP_REGISTER.md','代码符合性差异登记册','\n\n'.join(body),[])
trace=['# 正式协议来源追溯\n\n行段重新由锁定源码 AST/文本锚生成。协议规则依据 OWNER_ORDER；现实现证据不反向改规范。每项含文件、行段、SHA、checkout、branch、HEAD、协议章节。\n']
for k in evidence:trace.append('## '+k+'\n\n'+cite(k))
write('SOURCE_TRACEABILITY.md','\n\n'.join(trace))
doc('PROTOCOL_CHANGELOG.md','正式协议变更记录','2026-11-13：负责人明确批准F01–F08，状态从候选升级FROZEN/OWNER_APPROVED。F03补充OS组件/真实路径/句柄/替换/硬链接/TOCTOU安全；F05用最终有序role/content消息确定性JSON替换旧草案的字符串拼接；F08两次总Attempt扩为跨进程持久化的逻辑stage原子计数。校准登记机制未完成前不接受true为已验证，移除旧合成校准正例。2004数值+transient不再足够，当前无精确子类型机制而fail closed。原包/草案/公共API/源码均保留，后续wire语义变更须升版与重新签认。',['RETRY','M2_PROMPT','SIDECAR'])

# Reuse the reviewed static validator as package-local authoring tooling, adjusting approved semantics.
helper=(OLD/'build_support.py').read_text(encoding='utf-8').replace('ROOT=OUT.parent.parent','ROOT=OUT.parents[2]')
write('build_support.py',helper)
validator=(OLD/'validate_package.py').read_text(encoding='utf-8')
validator=validator.replace("assert o['observation_id'] in evidence['authorized_calibrated_observation_ids']","assert False, 'M5 independent calibration registry incomplete; calibrated=true not accepted'\n   assert o['observation_id'] in evidence['authorized_calibrated_observation_ids']")
validator=validator.replace("if e['source_checkout']: assert", "if e['source_checkout']: assert")
# Official SOURCE_LOCK also includes the authorization attachment (not a runtime source).
write('validate_package.py',validator)
dump('audit/BUILD_CONTEXT.json',{'task':'M1-M2-PROTOCOL-FINAL-001','python':sys.executable,'version':sys.version,'integration':False,'providers_called':0,'core_changes':0,'decision_files_read':[p.name for p in OLD.glob('*.md')],'protected_prior_files':{p.relative_to(OLD).as_posix():sha(p.read_bytes()) for p in OLD.rglob('*') if p.is_file()}})
print('Formal artifacts authored; validation and final packaging still pending.')
