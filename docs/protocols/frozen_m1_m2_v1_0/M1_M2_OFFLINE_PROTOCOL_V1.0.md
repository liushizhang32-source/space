# M1/M2 正式离线协议 V1.0

协议：M1_M2_OFFLINE_PROTOCOL_V1.0 · FROZEN · OWNER_APPROVED · 2026-11-13

仅限 Fake/Stub 离线接口。协议冻结不等于代码符合性验收；禁止本任务改核心源码、联调或发布 dev。


F01 身份 M1_M2_OFFLINE_PROTOCOL_V1.0，FROZEN / OWNER_APPROVED。规范优先级：冻结公共 API/C1/C2 > 本正式协议 > 锁定 M1 实现证据 > 历史 M1 Handoff > 历史 M2 Worker Interface。实现不符合时登记 Gap，不反改规范。任何 wire 字段/语义/枚举/状态变更须升版、重新签认。wire 常量仍 m1-vision-worker/0.1、vision_refs/0.1；本批准身份不添加为 wire 字段。

F02 全部私有结构定义在 REQUEST_SCHEMA、WORKER_RESULT_SCHEMA、C1_BINDING_SCHEMA、SIDECAR_SCHEMA 和 FIELD_CONTRACT；Schema 管结构，原字节/hash/文件安全/证据/跨文档规则由规范文本约束。必需字段缺失、非法 null/类型/未知键/版本/重复键/NaN/Infinity/无效 Unicode 一律拒绝。不得对 public C1/C2 擅自增加 extra=forbid 或改变冻结模型。

F03 M1 分配可信快照和 attempt；M2 只消费给定 stage。五元相同；OCR/VLM attempt/token 分离，来自 M1，不要求相等。路径、句柄、Hash、TOCTOU 的全部正式要求见 FILE_SECURITY_BOUNDARY，不把词法演示当 OS 实现。

F04 appearance={} 合法，clothing 可缺、不可 null/空白或编造。unavailable.value 可缺/null，calibrated=false；估计值有限 [0,1]，calibrated 原生 bool。true 需独立可复核的实际模型版本/数据集/方法注册证据；当前 M5 机制未完成，故本轮不得接受 true 为已验证。禁止用模型自述或合成玩具证据冒充真实校准。

F05 prompt_sha256 是确定性序列化的最终有序消息列表 Hash，详见 PROMPT_HASH_SPECIFICATION。本次明确替换旧草案 system+LF+user 的做法，不改变字段名；模板/请求 Hash 不得混同。

F06 observations 必需数组；执行成功可为 []，缺字段、失败、不完整、损坏皆不是成功空结果。C2.objects=[] 须 status=empty；有 C2 objects 可以没有参考观察，Schema 不承诺检测全覆盖。M5 负责真实准确率。

F07 A 优先准备，B 独立；实际链未认证不冒称具备接口准入。环境只来源锁定 allowlist；现有 M2 入口/依赖/Stub 安全与严格协议仍待单独验收。F08 见 ERROR_RETRY_STATE_MATRIX：每逻辑 Stage 两次总尝试且跨重启持久化是正式要求，当前内存 loop 不满足。

本协议只冻结定义。后续代码整改、Fake/Stub 联调、生产或 dev 必须经过各自准入。本次不修改核心源码，不创建提交/PR，不启动联调，不推 dev。


## 规范性授权与实现证据

[APPROVAL](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/OWNER_EXECUTION_ORDER.txt:1) — 已粘贴的文本.txt L1–884；SHA256 `a83d0b03e66c95279bdf11d511723c2eb1d710b4f5873f68c81365e651aa079f`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F01,F02,F03,F04,F05,F06,F07,F08

[REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:263) — orchestrator/services/vision_supervisor/supervisor.py L263–415；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03,F07,F08

[SIDECAR](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/gate.py.txt:96) — orchestrator/services/vision_supervisor/gate.py L96–154；SHA256 `c041a06a1b5529c31ce9dd537a917472c74d2622c865b3e305b77b2d56f4e6cc`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F04,F05,F06

[PUBLIC_OCR](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/schemas/ocr.py.txt:1) — orchestrator/schemas/ocr.py L1–139；SHA256 `3486276abc7a79837a61780e435a196f774a3d4af83f80fddd3ae6e6a95397fa`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F01,F03

[PUBLIC_VLM](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/schemas/vlm.py.txt:1) — orchestrator/schemas/vlm.py L1–168；SHA256 `a6d095ed82ba2f9f04186e80cbc32998a729772415dd23e999ccf959fdf8e2d4`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F01,F04,F06

[RETRY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:243) — orchestrator/services/vision_supervisor/supervisor.py L243–261；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07,F08

[LEASE_ENTRY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/lease_runner.py.txt:7) — orchestrator/services/mock_core_round2/lease_runner.py L7–10；SHA256 `0afc31f65d4262e4bb6cc4c7a4f4b88ba697b0b37a32e839fd3123927350c799`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07
