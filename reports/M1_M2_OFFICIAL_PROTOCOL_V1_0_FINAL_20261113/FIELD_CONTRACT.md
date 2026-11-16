# 逐字段完整契约

协议：M1_M2_OFFLINE_PROTOCOL_V1.0 · FROZEN · OWNER_APPROVED · 2026-11-13

仅限 Fake/Stub 离线接口。协议冻结不等于代码符合性验收；禁止本任务改核心源码、联调或发布 dev。

|对象/字段|类型/枚举|必需|null/默认|语义/责任/失败|
|---|---|---|---|---|
|OCR_REQUEST.protocol|const m1-vision-worker/0.1|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.job_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.page_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.generation_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.input_revision|integer|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.epoch|integer|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.attempt_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.fencing_token|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.stage|const ocr|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.image_path|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.image_sha256|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.result_path|const result.json|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.outputs|object|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.outputs.c1|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.outputs.c2|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|OCR_REQUEST.outputs.sidecar|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.protocol|const m1-vision-worker/0.1|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.job_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.page_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.generation_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.input_revision|integer|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.epoch|integer|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.attempt_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.fencing_token|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.stage|const vlm|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.image_path|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.image_sha256|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.result_path|const result.json|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.outputs|object|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.outputs.c1|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.outputs.c2|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.outputs.sidecar|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.inputs|object|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.inputs.c1|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.c1_binding|object|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.c1_binding.identity|object|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.c1_binding.identity.job_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.c1_binding.identity.page_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.c1_binding.identity.generation_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.c1_binding.identity.input_revision|integer|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.c1_binding.identity.epoch|integer|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.c1_binding.identity.attempt_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.c1_binding.identity.fencing_token|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.c1_binding.sha256|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|VLM_REQUEST.c1_binding.image_sha256|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.protocol|const m1-vision-worker/0.1|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.identity|object|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.identity.job_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.identity.page_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.identity.generation_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.identity.input_revision|integer|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.identity.epoch|integer|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.identity.attempt_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.identity.fencing_token|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.code|integer|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.msg|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.artifacts|object|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.artifacts.c1|string|False|不可 null；可省略；无自动填值|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.artifacts.c2|string|False|不可 null；可省略；无自动填值|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.artifacts.sidecar|string|False|不可 null；可省略；无自动填值|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|WORKER_RESULT.transient|boolean|False|不可 null；缺省 false|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.schema_version|const vision_refs/0.1|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.job_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.page_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.generation_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.input_revision|integer|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.epoch|integer|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.attempt_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.fencing_token|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.c2|object|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.c2.asset_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.c2.schema_version|const 1.0|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.c2.relative_path|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.c2.sha256|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.source|object|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.source.component_mode|['fixture', 'stub']|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.source.model_ref|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.source.prompt_sha256|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.source.evidence_ref|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.observations|array|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.observations[*].observation_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.observations[*].object_id|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.observations[*].identity_status|['unknown', 'ambiguous']|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.observations[*].visual_description|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.observations[*].source_ref|string|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.observations[*].appearance|object|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.observations[*].appearance.clothing|string|False|不可 null；可省略；无自动填值|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.observations[*].appearance.visible_features|array|False|不可 null；可省略；无自动填值|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.observations[*].confidence|object|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.observations[*].confidence.kind|['unavailable', 'model_estimate']|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.observations[*].confidence.calibrated|boolean|True|不可 null；无默认|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|
|SIDECAR.observations[*].confidence.value|['number', 'null']|False|可 null；可省略；无自动填值|M2 验 Request/Binding；M1 验 Result/Sidecar；错则拒绝，不自动 coercion|

附加语义：Request.outputs 两个 stage 都恰 c1/c2/sidecar，精确 json/{page}_ocr.json、json/{page}_vlm.json、json/{page}_refs.json；result_path=result.json。OCR 无 inputs/binding，VLM 必有 inputs.c1 和 binding。身份字符串非空且不透明，revision/epoch 原生 int>=1，bool/1.0 拒绝。binding.identity 为 OCR 身份，五元与 VLM 相同，token 非认证密钥。image_path 和 c1 绝对且属于授权 attempt 根；产物相对且受 M1 分配，不能碰撞。

Result.code 原生 int；msg 原生 str 可空；identity 恰七键并同 type/value。成功 artifacts：OCR 恰 c1，VLM 恰 c2/sidecar；错误 artifacts={}，3001 OCR合法 empty 例外恰 c1。transient 缺省 false，其存在不授予 retry。Result 顶层 detail 未声明，必须拒绝。缺 result/结构/identity/path/Hash/Gate 错，M1 拒绝成功；M2 无法验证可信请求时只能拒绝并尽力写已批准错误 envelope，不回显秘密。

Sidecar 根 identity 七元扁平；禁止 identity 镜像、contract_status/c1_sha256 扩展。source.component_mode 离线 fixture/stub（全来源词汇 real 本范围禁用）；c2.raw SHA/path 及 object 归属必须匹配。appearance{} 不是 null。confidence.kind=unavailable 时 value 缺/null且 calibrated=false；model_estimate 时 value 必需有限原生数 [0,1]，bool拒绝。clothing 不能空白，不得虚构；calibrated=true 当前证据机制未完成而不接受。观测 ID 唯一，object_id 属于本 C2，禁止 canonical 身份。引用真实有效性是外部证据校验，不能只靠非空字符串。

所有 optional 只限表列字段，未声明者不是 optional 而是 unknown。PUBLIC 模型默认值仍依冻结实现。语义/上下文失败不等于 JSON Schema 已证明 OS 安全；不能凭 envelope 模拟旧 binding 认证。


## 规范性授权与实现证据

[APPROVAL](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/OWNER_EXECUTION_ORDER.txt:1) — 已粘贴的文本.txt L1–884；SHA256 `a83d0b03e66c95279bdf11d511723c2eb1d710b4f5873f68c81365e651aa079f`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F01,F02,F03,F04,F05,F06,F07,F08

[REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:263) — orchestrator/services/vision_supervisor/supervisor.py L263–415；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03,F07,F08

[IDENTITY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:42) — orchestrator/services/vision_supervisor/supervisor.py L42–50；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03

[SIDECAR](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/gate.py.txt:96) — orchestrator/services/vision_supervisor/gate.py L96–154；SHA256 `c041a06a1b5529c31ce9dd537a917472c74d2622c865b3e305b77b2d56f4e6cc`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F04,F05,F06

[BOUND_C1](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/gate.py.txt:29) — orchestrator/services/vision_supervisor/gate.py L29–44；SHA256 `c041a06a1b5529c31ce9dd537a917472c74d2622c865b3e305b77b2d56f4e6cc`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F03

[M2_ENVELOPE](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:75) — src/vision/worker.py L75–87；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F08
