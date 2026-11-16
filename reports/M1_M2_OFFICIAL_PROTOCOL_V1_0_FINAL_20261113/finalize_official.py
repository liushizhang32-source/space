"""Create final acceptance report, manifest and exclusive ZIP; no runtime writes."""
from pathlib import Path
import copy,hashlib,json,sys,zipfile,stat
from build_support import OUT,ROOT,M1ZIP,M2ZIP,snapshot
def sha(b):return hashlib.sha256(b).hexdigest()
def read(n):return json.loads((OUT/n).read_text(encoding='utf-8'))
def dump(n,x):(OUT/n).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def link(n,label=None):return '['+(label or n)+']('+(OUT/n).as_posix()+')'
base=read('audit/VALIDATION_RESULTS.json');official=read('audit/OFFICIAL_STATIC_RESULTS.json')
assert base['failed']==official['failed']==0
after=snapshot();before=read('audit/CHECKOUT_BEFORE.json')
prefix='?? reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/'
def normalize(xs):
 xs=copy.deepcopy(xs)
 for x in xs:
  if Path(x['path']).name=='space-m1-m2-v12-supervisor':x['status']['out']='\n'.join(l for l in x['status']['out'].splitlines() if not l.startswith(prefix) and l!='?? reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL.zip')
 return xs
assert normalize(before)==normalize(after),'Unauthorized checkout drift'
dump('audit/CHECKOUT_FINAL.json',after)
context=read('audit/BUILD_CONTEXT.json');old=ROOT/'reports/M1_M2_PROTOCOL_V1_0_DECISION_PACKAGE'
for n,h in context['protected_prior_files'].items():assert sha((old/n).read_bytes())==h,n
for e in read('SOURCE_LOCK.json'):
 assert sha((OUT/e['locked_copy']).read_bytes())==e['sha256']
 if e['source_checkout']:assert sha((Path(e['source_checkout'])/e['source_relative_path']).read_bytes())==e['sha256']
inputs=read('audit/INPUT_VERIFICATION.json')
for p,key in [(M1ZIP,'M1'),(M2ZIP,'M2'),(old.with_suffix('.zip'),'DECISION')]:assert sha(p.read_bytes())==inputs[key]['sha256']
negative=[]
req=read('VLM_REQUEST_EXAMPLE.json');side=read('SIDECAR_EXAMPLES.json')['examples'][0]['sidecar']
def neg(n,kind,original,edit):
 obj=copy.deepcopy(original);edit(obj);negative.append({'name':n,'contract':kind,'expected':'REJECT','payload':obj})
neg('cross-page binding','VLM_REQUEST',req,lambda x:x['c1_binding']['identity'].__setitem__('page_id','book01_p04'))
neg('cross-revision binding','VLM_REQUEST',req,lambda x:x['c1_binding']['identity'].__setitem__('input_revision',2))
neg('cross-generation binding','VLM_REQUEST',req,lambda x:x['c1_binding']['identity'].__setitem__('generation_id','old'))
neg('cross-epoch binding','VLM_REQUEST',req,lambda x:x['c1_binding']['identity'].__setitem__('epoch',2))
neg('stale OCR attempt','VLM_REQUEST',req,lambda x:x['c1_binding']['identity'].__setitem__('attempt_id','stale'))
neg('clothing null','SIDECAR',side,lambda x:x['observations'][0]['appearance'].__setitem__('clothing',None))
neg('clothing fabricated empty','SIDECAR',side,lambda x:x['observations'][0]['appearance'].__setitem__('clothing',''))
neg('unavailable calibrated self-assertion','SIDECAR',side,lambda x:x['observations'][0]['confidence'].__setitem__('calibrated',True))
dump('NEGATIVE_EXAMPLES.json',{'note':'Negative wire examples deliberately rejected; wrapper metadata is not a wire object. Their mutation classes are exercised in VALIDATION_LOG.','cases':negative})
for p in OUT.rglob('*.json'):json.loads(p.read_text(encoding='utf-8'))
summary={'task':'M1-M2-PROTOCOL-FINAL-001','protocol':'M1_M2_OFFLINE_PROTOCOL_V1.0','protocol_status':'FROZEN','approval':'OWNER_APPROVED','date':'2026-11-13','F01_F08':{f'F{i:02d}':'OWNER_APPROVED' for i in range(1,9)},'three_supplements':'NORMATIVELY_INCORPORATED_NOT_IMPLEMENTATION_ACCEPTED','passed':base['passed']+official['passed'],'failed':0,'static_contract_checks':base['passed'],'official_static_cases':official['passed'],'validation_scope':'Static protocol and side-effect-free validator checks. Reference retry ledger uses only in-memory serialized state; not real M1 persistence/restart/concurrency/crash tests. Paths tested lexically only.','code_conformance':'BLOCKED','Profile_A':'NOT_READY_FOR_ACTUAL_INTEGRATION','Profile_B':'INDEPENDENT','OS_TOCTOU':'NORMATIVE_ONLY_NOT_VERIFIED_IMPLEMENTATION','persistent_two_attempts':'NORMATIVE_ONLY_CURRENT_IMPLEMENTATION_GAP','provider_calls':0,'core_modifications':0,'commits':0,'PRs':0,'dev_pushes':0,'prior_decision_preserved':True,'source_hashes_match':True,'nine_checkouts_preserved_excluding_exact_authorized_new_output':True}
dump('VALIDATION_RESULTS.json',summary)
report=f'''# 最终验收报告 — M1-M2-PROTOCOL-FINAL-001

2026-11-13（Asia/Hong_Kong）。**M1_M2_OFFLINE_PROTOCOL_V1.0 已按项目负责人本次明确授权形成唯一正式协议，FROZEN / OWNER_APPROVED。代码符合性：BLOCKED，未开展实际联调。**

|验收项|结果|
|---|---|
|A F01–F08|全部 OWNER_APPROVED，依据随包原始执行令及 Hash；不是伪造个人数字签名。|
|B 三项补充|文件安全/TOCTOU、确定性最终消息JSON、跨进程持久化两次Attempt已全部进入正式规范和Gap/静态测试。|
|C 协议冻结|FROZEN；原草案/决策包保持原样，正式目录是唯一新规范位置。|
|D 范围|只限Fake/Stub离线接口；真实模型/收费POC/生产/dev均不授权。|
|E M1差异|见Gap G01–G10及G15/G16/G17：strict Gate/Result、同句柄TOCTOU、持久Stage总计数、精确2004子类型等仍需整改/证据。|
|F M2差异|见G11–G18：输入严格性、旧binding/path边界、Sidecar额外键、模板hash、detail、错误策略、SDK路径/来源范围待验。|
|G Profile A后续条件|协议/整改基准已齐备；当前存在P1差异，尚不具备直接进入实际接口联调的准入条件。|
|H Profile B|独立保留，精确LEASE配对和FakeProvider，未拼接成统一链。|
|I 文件安全/TOCTOU|仅规范定义和静态案例；未证明真实OS属性实现，不冒称字符串/resolve检查已防竞态。|
|J 两次Attempt持久化|仅规范与纯参考状态演算；现M1每次run内存loop不满足跨进程总计数；LEASE台账也不等于该保证。|
|K JSON/静态验证|{summary['passed']}项通过、0失败（{base['passed']}项契约/纯校验 + {official['passed']}项正式补充/追溯检查）。正例接受、反例拒绝；不等于M2兼容或持久化行为测试。|
|L ZIP/Manifest|封包阶段检查CRC、路径、文件数、Manifest、内外原字节一致；精确结果由封包stdout返回。MANIFEST覆盖本目录全部文件，排除其自身，ZIP位于本目录外以避免自引用。|
|M 九个checkout|branch/HEAD/staged/unstaged/untracked快照保全；只排除本次精确新目录的新增untracked项。42份来源+批准附件Hash核对，旧决策包所有文件与三原ZIP保留。未声称逐字节扫描九个checkout所有其他未跟踪内容。|
|N 阻断|协议交付无阻断；代码符合性/文件OS安全/持久化计数/M5证据登记/实际M2入口兼容仍阻断执行准入。|

{link('CONFORMANCE_GAP_REGISTER.md','完整Gap Register')} 含18项（16项P1接口准入差异、2项P2范围/来源限制）；不是发现16个已复现生产漏洞。P0事故在本静态范围未确认。每项区分源码事实与未验证能力，附责任方、后续整改、锁定证据及验收案例。

{link('SOURCE_LOCK.json')} 含43条（36份M1来源、6份M2归档源码/文档、1份用户批准令）；M2仍archive-only，checkout/branch/HEAD/tracked无证据则UNKNOWN/null，未冒用其他仓库。{link('SOURCE_TRACEABILITY.md')} 的42组行段根据锁定源码AST/文本锚重新生成。

输入完整性：决策ZIP `{inputs['DECISION']['sha256']}`；M1 ZIP `{inputs['M1']['sha256']}`；M2 ZIP `{inputs['M2']['sha256']}`。三包CRC、90/90/179 Manifest匹配，决策ZIP内外文件一致。没有同名旧包替代。

F05正式冻结输入是有序role/content列表，固定字段顺序无空白JSON、UTF-8无BOM、拒绝无效Unicode，不trim；不再沿用草案system+LF+user拼接。Hash只证明应用交给Adapter的消息，示例adapter_invoked=false。附件独立Hash及message_index关联；不声称provider/SDK内部未改变消息。

F04当前M5独立登记机制未完成，因此没有calibrated=true已验证正例，旧玩具校准示例未沿用。所有本轮估计示例calibrated=false；true自述/玩具证明被负例拒绝，未伪造M5评测。

2004规则：typed cancellation无retry；仅数值+transient不够。当前锁定M1没有精确子类型登记，本V1.0允许的2004标识集合为空，fail closed；后续增列须按签认变更流程。9001不重试的公共原文冲突保存在独立ERRATA，公共冻结原件未改。

验证限制：标准库校验器只支持实际生成Schema使用的keyword子集，并用上下文规则补充Hash/身份/路径/证据。不是独立完整JSON Schema引擎。Pydantic模型及Gate.refs仅纯校验，不导入/启动Supervisor、Worker、Core、供应商。新Schema与实际被验证的内部contract视图一致。持久化/并发/崩溃案例仅纯参考状态序列，未创建运行库或模拟真实M1重启。

输出仅本次新目录及同名最终ZIP。未安装依赖、未调用模型/供应商、未处理真实儿童绘本、未修改核心业务/公共Schema/API、未stage/commit/merge/push/创建PR。dev推送：无。到此停止，不自动开展后续接入。
'''
(OUT/'FINAL_ACCEPTANCE_REPORT.md').write_text(report,encoding='utf-8')
commands=f'''# Static reproduction

Interpreter: {sys.executable}
Working directory: {ROOT}

Run validate_package.py then validate_official.py with this interpreter and -B; neither is an integration runner. Authoring build_official.py is one-shot and aborts if SOURCE_LOCK exists. Original directory creation used New-Item -ErrorAction Stop after absence check. Build and validation use only standard library plus already installed Pydantic; no dependency installation. validate_package raw stdout and validate_official appended stdout are retained in VALIDATION_LOG.txt. Supplementary reference-state tests do not exercise actual DB persistence, threads or processes.

```powershell
& '{sys.executable}' -B '{OUT/'validate_package.py'}'
& '{sys.executable}' -B '{OUT/'validate_official.py'}'
```

Finalizer is exclusive: do not rerun over this delivered ZIP. It recomputes input/source hashes and preservation, emits the report/Manifest, creates the ZIP using mode x, and verifies every archived byte and path. Its stdout supplies final file count, Manifest SHA256 and archive SHA256. Do not redirect finalizer stdout into the directory after its manifest is sealed.
'''
(OUT/'audit/COMMANDS.md').write_text(commands,encoding='utf-8')
required=['M1_M2_OFFLINE_PROTOCOL_V1.0.md','OWNER_APPROVAL_RECORD.md','PROTOCOL_DECISION_REGISTER.md','REQUEST_SCHEMA.json','C1_BINDING_SCHEMA.json','C1_BINDING_EXAMPLE.json','OCR_REQUEST_EXAMPLE.json','VLM_REQUEST_EXAMPLE.json','WORKER_RESULT_SCHEMA.json','WORKER_RESULT_EXAMPLE.json','SIDECAR_SCHEMA.json','SIDECAR_EXAMPLES.json','SIDECAR_GATE_MATRIX.md','PROMPT_HASH_SPECIFICATION.md','FILE_SECURITY_BOUNDARY.md','RUNTIME_PAIRING_MATRIX.md','ENVIRONMENT_ALLOWLIST.md','ERROR_RETRY_STATE_MATRIX.md','M1_M2_RESPONSIBILITY_BOUNDARY.md','CONFORMANCE_GAP_REGISTER.md','PUBLIC_API_RETRY_ERRATA.md','SOURCE_TRACEABILITY.md','SOURCE_LOCK.json','PROTOCOL_CHANGELOG.md','VALIDATION_RESULTS.json','VALIDATION_LOG.txt','FINAL_ACCEPTANCE_REPORT.md']
assert all((OUT/n).is_file() for n in required)
files=sorted(p for p in OUT.rglob('*') if p.is_file() and p.name!='MANIFEST.sha256')
manifest='# all delivery files except this manifest; ZIP outside directory\n'+''.join(sha(p.read_bytes())+'  '+p.relative_to(OUT).as_posix()+'\n' for p in files)
(OUT/'MANIFEST.sha256').write_text(manifest,encoding='utf-8')
archive=OUT.parent/'M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL.zip';assert not archive.exists(),'Do not overwrite prior delivery ZIP'
with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
 for p in [*files,OUT/'MANIFEST.sha256']:z.write(p,OUT.name+'/'+p.relative_to(OUT).as_posix())
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None;seen=set()
 for info in z.infolist():
  n=info.filename;assert not n.startswith('/') and '..' not in Path(n).parts and ':' not in n and '\\' not in n and n.casefold() not in seen and not stat.S_ISLNK(info.external_attr>>16);seen.add(n.casefold())
  assert z.read(n)==(OUT/Path(n).relative_to(OUT.name)).read_bytes()
 assert set(z.namelist())=={OUT.name+'/'+p.relative_to(OUT).as_posix() for p in [*files,OUT/'MANIFEST.sha256']}
 for l in manifest.splitlines():
  if l.startswith('#'):continue
  h,n=l.split('  ',1);assert sha(z.read(OUT.name+'/'+n))==h
assert normalize(before)==normalize(snapshot()),'Checkout drift after ZIP creation'
print(json.dumps({'post_ZIP_nine_checkout_preservation':'PASS','protocol':'M1_M2_OFFLINE_PROTOCOL_V1.0','state':'FROZEN','approval':'OWNER_APPROVED','report':str(OUT/'FINAL_ACCEPTANCE_REPORT.md'),'ZIP':str(archive),'ZIP_SHA256':sha(archive.read_bytes()),'ZIP_files':len(files)+1,'manifest_entries':len(files),'Manifest_SHA256':sha((OUT/'MANIFEST.sha256').read_bytes()),'static_passed':summary['passed'],'failed':0,'CRC':'PASS','paths':'PASS','zip_disk_identity':'PASS','code_conformance':'BLOCKED','dev':'NOT_PUSHED'},ensure_ascii=False,indent=2))
