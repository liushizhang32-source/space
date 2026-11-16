# 完整 Gate 对照矩阵

协议：M1_M2_OFFLINE_PROTOCOL_V1.0 · FROZEN · OWNER_APPROVED · 2026-11-13

仅限 Fake/Stub 离线接口。协议冻结不等于代码符合性验收；禁止本任务改核心源码、联调或发布 dev。

所有行证据为下方 SIDECAR/GATE 原字节 AST 行段；此表替代历史偏移引用，不修改原交接包。

|规则|当前 Gate|正式协议决定|差异|
|---|---|---|---|
|根键/子对象 extra|多数未全局禁|一律按显式白名单拒绝|收紧|
|identity|Sidecar 顶层七元精确 type/value|保持；禁嵌套镜像扩展|收紧 extra|
|clothing|可缺/空串合法/null拒绝|可缺；非空非空白实观测字符串|收紧空串和证据语义|
|unavailable.value|缺省或 null|保持|一致|
|calibrated|原生 bool；model_estimate true 不验依据|true 需独立实际模型/数据集/方法证据；机制未完成前拒绝|收紧|
|source.component_mode|fixture/stub/real|离线 fixture/stub|收紧范围|
|prompt_sha256|只验小写 64 hex|最终渲染后 prompt byte hash + 外部证据|新增语义约束|
|observations|必需 array，可空，不强制覆盖|保持；失败不冒充空成功|新增业务区分|
|appearance|可空，键仅 clothing/visible_features|保持，服装非空政策另述|大体一致|
|canonical identity|键存在即拒绝|保持|一致|
|C2 hash/path|raw hash，固定分配路径|保持|一致|
|source/model/evidence refs|非空字符串，未核引用真实性|本地受审注册表，非空白，匹配 mode/model/prompt|收紧|
|公开 C2 safety|原生 true + []，信任依赖 Snapshot.source_id|保持；Sidecar 不授信|一致|



未知私有字段禁止，真实来源/校准/文件安全/持久化计数不是当前 Gate.refs 已验证能力；单纯 Gate.refs 接受不代表正式协议合格。

## 规范性授权与实现证据

[APPROVAL](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/OWNER_EXECUTION_ORDER.txt:1) — 已粘贴的文本.txt L1–884；SHA256 `a83d0b03e66c95279bdf11d511723c2eb1d710b4f5873f68c81365e651aa079f`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F01,F02,F03,F04,F05,F06,F07,F08

[SIDECAR](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/gate.py.txt:96) — orchestrator/services/vision_supervisor/gate.py L96–154；SHA256 `c041a06a1b5529c31ce9dd537a917472c74d2622c865b3e305b77b2d56f4e6cc`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F04,F05,F06

[GATE](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/gate.py.txt:60) — orchestrator/services/vision_supervisor/gate.py L60–94；SHA256 `c041a06a1b5529c31ce9dd537a917472c74d2622c865b3e305b77b2d56f4e6cc`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F03,F04,F06,F08


## 锁定 Gate 的逐字段现实现明细

下表仅描述现实现边界，不授予正式协议更宽权限。原历史G行号列已移除，逐字段统一引用本文件上方新生成的 SIDECAR/GATE/BOUND_C1 真实AST行段、SHA和来源。正式差异以本文件差异表与FIELD_CONTRACT、FILE_SECURITY_BOUNDARY、ERROR_RETRY_STATE_MATRIX为准。

|JSON路径|必填|数据类型|允许值/约束|null规则|失败行为|
|---|---|---|---|---|---|
|$|是|原生dict|合法JSON；重复键、NaN/Infinity拒绝；顶层额外字段未全局禁止|不允许|经accept为1002|
|$.schema_version|是|string|vision_refs/0.1|拒绝|1002|
|$.job_id|是|与受信任Identity字段精确同type|与当前VLM identity相等，不是Sidecar.identity内字段|拒绝正常str预期下null|1002|
|$.page_id|是|同上|string与当前页相等|同上|1002|
|$.generation_id|是|同上|string与当前代相等|同上|1002|
|$.input_revision|是|同上|正常为int；bool不等同int类型|拒绝|1002|
|$.epoch|是|同上|正常为int；bool不等同int类型|拒绝|1002|
|$.attempt_id|是|同上|与本次VLM attempt精确相等|拒绝|1002|
|$.fencing_token|是|同上|与本次VLM token精确相等|拒绝|1002|
|$.identity|否|未定义|嵌套identity不能替代顶层七元组；额外提供此对象当前不会因其名字单独拒绝|未单独校验|缺顶层时1002|
|$.c2|是|原生dict|包含下列引用字段；额外键未整体禁止|拒绝|1002|
|$.c2.asset_id|是|string|非空；未验证全局registry、格式或去空白|拒绝|1002|
|$.c2.schema_version|是|string|1.0|拒绝|1002|
|$.c2.sha256|是|string（通过与hexdigest相等约束）|必须等于当前C2原始字节SHA256；实际64位小写hex|拒绝|1002|
|$.c2.relative_path|是|string|精确json/{page_id}_vlm.json；禁反斜杠、冒号、绝对路径、..|拒绝|1002|
|$.source|是|原生dict|额外键未整体禁止|拒绝|1002|
|$.source.component_mode|是|string正常值|fixture / stub / real；不是source_mode；real标签不证明真实模型或授权|拒绝|1002|
|$.source.model_ref|是|string|非空，未解析或验证模型路径；空白字符串当前可通过|拒绝|1002|
|$.source.prompt_sha256|是|string|[0-9a-f]{64}完整匹配；是渲染prompt还是模板hash待联合确认|拒绝|1002|
|$.source.evidence_ref|是|string|非空；真实性、文件存在、引用格式未验证|拒绝|1002|
|$.observations|是|原生list|允许空列表；未要求覆盖所有C2.objects|拒绝|1002|
|$.observations[*]|每项是|原生dict|下列字段；额外键除明确禁止项外未整体拒绝|拒绝|1002|
|$.observations[*].canonical_id / character_id / canonical_identity|禁止|任何|只要键存在就拒绝，含null；M2不分配跨页身份|键存在即拒绝|1002|
|$.observations[*].observation_id|是|string|非空且本列表唯一；未规定其他格式|拒绝|1002|
|$.observations[*].object_id|是|正常string|必须属于已校验C2.objects的object_id集合；多个不同observation可指同一object|拒绝|1002|
|$.observations[*].identity_status|是|string|unknown / ambiguous|拒绝|1002|
|$.observations[*].visual_description|是|string|非空，未去空白|拒绝|1002|
|$.observations[*].source_ref|是|string|非空，未核实引用内容|拒绝|1002|
|$.observations[*].appearance|是|原生dict|只允许clothing、visible_features两个键；{}可通过|拒绝|1002|
|$.observations[*].appearance.clothing|否|原生str|允许空字符串；没有枚举；缺失可以，null不可以|存在则拒绝null|1002|
|$.observations[*].appearance.visible_features|否|原生list，所有元素原生str|允许[]或空字符串元素；无额外长度限制|存在则拒绝null|1002|
|$.observations[*].confidence|是|原生dict|额外键未整体禁止|拒绝|1002|
|$.observations[*].confidence.calibrated|是|原生bool|true/false；不可用置信必须false；model_estimate可true或false|拒绝|1002|
|$.observations[*].confidence.kind|是|string|unavailable / model_estimate|拒绝|1002|
|$.observations[*].confidence.value|model_estimate必填；unavailable可缺失|model_estimate为原生int/float（bool拒绝）；unavailable为null|估计值有限且0≤value≤1；unavailable缺失时get()也视None|仅unavailable允许null/缺失|1002|
|前置：C2.safety|是|原生dict|pass原生bool=true，flags原生list且为空；非空/空白flag均拒绝，不接受pass_替代|拒绝|3004，禁止下游|
|前置：Snapshot.source_id|是|原生str|来自M1部署注册并在Gate.trusted；不是Sidecar自报source|拒绝|3004|
|前置：Snapshot.identity|是|Identity|当前record.identity；fences.current仍有效|拒绝正常流null|3004或Cancelled(2004)|
|前置：C2冻结模型/页/尺寸|是|VLMData|见C2_FROZEN_MODEL_SCHEMA.json和vlm.py业务validator|拒绝不合法值|1002|
|前置：C1冻结模型/页/尺寸/五元绑定|是|OCRData和Snapshot|与C2的job/page/generation/input_revision/epoch相等；OCR/VLM attempt/token可以不同|拒绝缺失|1002|
