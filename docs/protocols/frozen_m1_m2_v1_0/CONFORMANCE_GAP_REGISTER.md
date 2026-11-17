# 代码符合性差异登记册

协议：M1_M2_OFFLINE_PROTOCOL_V1.0 · FROZEN · OWNER_APPROVED · 2026-11-13

仅限 Fake/Stub 离线接口。协议冻结不等于代码符合性验收；禁止本任务改核心源码、联调或发布 dev。

严重度表示接口准入差异，不是已证明生产事故。P0：本静态范围未确认；P1：阻断实际Profile A准入；P2：来源/范围限制。证据缺失与代码已证实差异分别明述；不把未审范围判通过。

## G01 M1 Request Producer

|字段|记录|
|---|---|
|Protocol Rule|私有严格键集/type/default|
|Current M1|生成固定正常结构；不证明 wire消费者严格|
|Current M2|process_request未全局拒绝额外键；顶层revision/epoch允许0|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|Joint|
|Required Change|M2增加严格输入验证；M1保留规范生成|
|Test|缺键/null/unknown/bool/0/版本|

[REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:263) — orchestrator/services/vision_supervisor/supervisor.py L263–415；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03,F07,F08

[M2_REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:906) — src/vision/worker.py L906–996；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F07

[M2_IDENTITY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:241) — src/vision/worker.py L241–254；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F03

## G02 M1 C1 Snapshot

|字段|记录|
|---|---|
|Protocol Rule|授权根/真实组件/同句柄/替换TOCTOU|
|Current M1|快照bytes与图片hash存在；读取链无完整句柄证明|
|Current M2|C1 path函数拒绝末端link但未证明受信根/祖先reparse/同句柄|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|Joint|
|Required Change|实现或证明OS属性，不能支持则拒绝|
|Test|reparse祖先/替换竞态/硬链接/逃逸|

[BOUND_C1](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/gate.py.txt:29) — orchestrator/services/vision_supervisor/gate.py L29–44；SHA256 `c041a06a1b5529c31ce9dd537a917472c74d2622c865b3e305b77b2d56f4e6cc`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F03

[PATH](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:175) — orchestrator/services/vision_supervisor/supervisor.py L175–193；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03

[REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:263) — orchestrator/services/vision_supervisor/supervisor.py L263–415；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03,F07,F08

[M2_C1_PATH](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:470) — src/vision/worker.py L470–493；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F03

## G03 M1 c1_binding

|字段|记录|
|---|---|
|Protocol Rule|OCR七元+原C1/image hash+五元一致|
|Current M1|producer字段形状匹配；无wire独立解析器|
|Current M2|支持native亦保留扁平旧绑定/大小写宽松|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|Joint|
|Required Change|严格唯一binding格式和新鲜度责任|
|Test|跨page/revision/generation/epoch/旧attempt|

[REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:263) — orchestrator/services/vision_supervisor/supervisor.py L263–415；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03,F07,F08

[BOUND_C1](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/gate.py.txt:29) — orchestrator/services/vision_supervisor/gate.py L29–44；SHA256 `c041a06a1b5529c31ce9dd537a917472c74d2622c865b3e305b77b2d56f4e6cc`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F03

[M2_BINDING](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:496) — src/vision/worker.py L496–565；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F03

## G04 M1 Identity

|字段|记录|
|---|---|
|Protocol Rule|正整数revision/epoch、M1唯一attempt|
|Current M1|分配新attempt/token，Fences revision严格；dataclass不独立验证|
|Current M2|顶层身份校验允许0，native binding另要求>=1|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|M2|
|Required Change|统一严格消费者约束；M1证实权威分配|
|Test|0/bool/float/旧token|

[IDENTITY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:42) — orchestrator/services/vision_supervisor/supervisor.py L42–50；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03

[FENCES](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:69) — orchestrator/services/vision_supervisor/supervisor.py L69–130；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F03,F08

[M2_IDENTITY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:241) — src/vision/worker.py L241–254；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F03

## G05 M1 Gate

|字段|记录|
|---|---|
|Protocol Rule|未知字段拒绝、非空服装、证据真实|
|Current M1|多数额外键允许、空服装允许、校准不验依据|
|Current M2|build_refs有根扩展键与可配置null服装|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|Joint|
|Required Change|按正式协议适配Gate/producer及独立证据校验|
|Test|unknown/null/empty/true无证据|

[SIDECAR](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/gate.py.txt:96) — orchestrator/services/vision_supervisor/gate.py L96–154；SHA256 `c041a06a1b5529c31ce9dd537a917472c74d2622c865b3e305b77b2d56f4e6cc`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F04,F05,F06

[M2_REFS](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/refs.py.txt:71) — src/vision/refs.py L71–139；SHA256 `d6b5b985ab489bee9d6eb01e04826af10983bdbf6f4b772f79db81ce6595c145`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F04,F06

## G06 M1 Sidecar

|字段|记录|
|---|---|
|Protocol Rule|规范字段、来源/原字节C2 hash|
|Current M1|Gate验hash/固定路径/类型，未验来源真实性|
|Current M2|多写contract_status/identity/c1_sha256；raw hash正常构造|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|M2|
|Required Change|仅保留正式字段，保持原字节hash|
|Test|根额外键、格式化后hash|

[SIDECAR](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/gate.py.txt:96) — orchestrator/services/vision_supervisor/gate.py L96–154；SHA256 `c041a06a1b5529c31ce9dd537a917472c74d2622c865b3e305b77b2d56f4e6cc`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F04,F05,F06

[M2_REFS](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/refs.py.txt:71) — src/vision/refs.py L71–139；SHA256 `d6b5b985ab489bee9d6eb01e04826af10983bdbf6f4b772f79db81ce6595c145`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F04,F06

## G07 M1 Supervisor

|字段|记录|
|---|---|
|Protocol Rule|符合性安全/计数门禁齐备|
|Current M1|进程监管/drain存在；无统一新增门禁证明|
|Current M2|worker入口存在不等于整链验收|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|M1|
|Required Change|在新授权任务中补证明或适配|
|Test|未终止禁止retry/lease不释放|

[REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:263) — orchestrator/services/vision_supervisor/supervisor.py L263–415；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03,F07,F08

[RETRY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:243) — orchestrator/services/vision_supervisor/supervisor.py L243–261；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07,F08

[M2_ENTRY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/scripts/m2_vision_worker.py.txt:1) — scripts/m2_vision_worker.py L1–23；SHA256 `77766ae66df5ac0e617d3a6d8c1da9d7c45ba7bdb5ec16e46ff811e0bcb8890c`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F07

## G08 M1 Runtime

|字段|记录|
|---|---|
|Protocol Rule|Profile A确切消费者链、B独立|
|Current M1|A与B各自候选路径；无已认证统一链|
|Current M2|archive-only入口；依赖/默认stub安全/SDK retry未全审|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|Joint|
|Required Change|后续隔离兼容审查，禁止任意拼接|
|Test|固定argv/env/零真实网络|

[LEASE_ENTRY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/lease_runner.py.txt:7) — orchestrator/services/mock_core_round2/lease_runner.py L7–10；SHA256 `0afc31f65d4262e4bb6cc4c7a4f4b88ba697b0b37a32e839fd3123927350c799`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07

[LEASE_RUN](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/lease_supervisor.py.txt:75) — orchestrator/services/mock_core_round2/lease_supervisor.py L75–99；SHA256 `71dc02888c253407db7cbebad157f506ffb47d090c5925c893205a0a9a644958`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07,F08

[RUNNER](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/runner.py.txt:9) — orchestrator/services/mock_core_round2/runner.py L9–73；SHA256 `10f5e25117904d93d5994b868a6386bbd5c22d8031410576353585e1c03fbf10`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07,F08

[M2_FACTORY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/backends/__init__.py.txt:1) — src/vision/backends/__init__.py L1–43；SHA256 `7279b853be2b66b6ba26aa4d5bd049ff7c0c43eb6cfdd735868b9fd280063e07`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F07

## G09 M1 Retry

|字段|记录|
|---|---|
|Protocol Rule|每逻辑stage最多2次总attempt跨进程持久化|
|Current M1|_run每次调用内存(1,2)，重入可重新计数；无原子总ledger|
|Current M2|不应权威管理重试；SDK实际路径未全面认证|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|M1|
|Required Change|提交前持久预留、唯一约束、恢复及并发屏障|
|Test|第三次/重启/崩溃/重复入口/并发|

[RETRY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:243) — orchestrator/services/vision_supervisor/supervisor.py L243–261；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07,F08

[FENCES](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:69) — orchestrator/services/vision_supervisor/supervisor.py L69–130；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F03,F08

[UNKNOWN](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/lease_core.py.txt:266) — orchestrator/services/mock_core_round2/lease_core.py L266–316；SHA256 `bd957221e2ea61003d7b6601a210691b81dd93b52114620eee1bd80e860d2081`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F08

## G10 M1 Lease

|字段|记录|
|---|---|
|Protocol Rule|unknown留资源、精确原key对账|
|Current M1|LEASE有对应实现证据，仅离线Fake|
|Current M2|不把客户端退出当后端停止；M2实际链未审|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P2|
|Owner|Joint|
|Required Change|保持B独立验证；不得借此声称A已具资源证明|
|Test|unknown/旧owner/终态重复回执|

[UNKNOWN](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/lease_core.py.txt:266) — orchestrator/services/mock_core_round2/lease_core.py L266–316；SHA256 `bd957221e2ea61003d7b6601a210691b81dd93b52114620eee1bd80e860d2081`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F08

[LOOKUP](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/lease_core.py.txt:210) — orchestrator/services/mock_core_round2/lease_core.py L210–225；SHA256 `bd957221e2ea61003d7b6601a210691b81dd93b52114620eee1bd80e860d2081`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F08

[LEASE_ENTRY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/lease_runner.py.txt:7) — orchestrator/services/mock_core_round2/lease_runner.py L7–10；SHA256 `0afc31f65d4262e4bb6cc4c7a4f4b88ba697b0b37a32e839fd3123927350c799`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07

## G11 M2 OCR Consumer

|字段|记录|
|---|---|
|Protocol Rule|OCR输出分配三键，严格Request/文件安全|
|Current M1|producer实际分配三键|
|Current M2|_outputs_for仅取本stage必需键，额外键未整体拒绝|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|M2|
|Required Change|对完整request规范验证，不静默采用历史子集|
|Test|OCR额外inputs/outputs未知键|

[REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:263) — orchestrator/services/vision_supervisor/supervisor.py L263–415；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03,F07,F08

[M2_OUTPUTS](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:172) — src/vision/worker.py L172–209；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02

[M2_REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:906) — src/vision/worker.py L906–996；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F07

## G12 M2 VLM Consumer

|字段|记录|
|---|---|
|Protocol Rule|只assigned VLM，给定C1，严格边界|
|Current M1|M1提前bound_c1|
|Current M2|native消费给定C1，但旧格式/路径边界待适配；不是本轮全代码验收|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|M2|
|Required Change|严格格式和授权根/句柄流程，维持无隐式OCR|
|Test|缺C1即拒绝/不重做OCR|

[M2_BINDING](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:496) — src/vision/worker.py L496–565；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F03

[M2_C1_PATH](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:470) — src/vision/worker.py L470–493；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F03

[M2_REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:906) — src/vision/worker.py L906–996；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F07

## G13 M2 C1 Binding Consumer

|字段|记录|
|---|---|
|Protocol Rule|同F03，不允许旧绑定绕过|
|Current M1|M1生产正常native结构|
|Current M2|扁平兼容/hex大小写宽松、输入root缺证据|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|M2|
|Required Change|去掉未声明兼容，可信绑定台账和路径验证|
|Test|旧OCR attempt/非绝对/原字节重排|

[M2_BINDING](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:496) — src/vision/worker.py L496–565；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F03

[M2_C1_PATH](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:470) — src/vision/worker.py L470–493；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F03

## G14 M2 Sidecar Producer

|字段|记录|
|---|---|
|Protocol Rule|只冻结字段、无无据calibrated true|
|Current M1|Gate当前宽松|
|Current M2|build_refs额外根键；null模式不兼容；无实际校准机制|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|M2|
|Required Change|严格输出、默认calibrated=false，M5机制前不接受true|
|Test|unknown根/服装null/无校准证据|

[M2_REFS](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/refs.py.txt:71) — src/vision/refs.py L71–139；SHA256 `d6b5b985ab489bee9d6eb01e04826af10983bdbf6f4b772f79db81ce6595c145`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F04,F06

[SIDECAR](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/gate.py.txt:96) — orchestrator/services/vision_supervisor/gate.py L96–154；SHA256 `c041a06a1b5529c31ce9dd537a917472c74d2622c865b3e305b77b2d56f4e6cc`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F04,F05,F06

## G15 M2 Prompt Hash

|字段|记录|
|---|---|
|Protocol Rule|最终消息列表确定性JSON hash|
|Current M1|M1 Gate仅hex；fixture no model|
|Current M2|模板SYSTEM+LF+USER或stub占位，不含最终替换有序消息|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|Joint|
|Required Change|在Adapter边界生成正式bytes/hash和附件关联|
|Test|role/content/order/尾空格/附件关联|

[M2_PROMPT](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:313) — src/vision/worker.py L313–318；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F05

[M2_RENDER](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/backends/qwen_vl.py.txt:244) — src/vision/backends/qwen_vl.py L244–250；SHA256 `a284b32db90843a70d9bdfc3927e0459cf6ffef1444551932a32964e9b71fa19`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F05

[FIXTURE](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/tests/fixtures/m1_vision_worker.py.txt:11) — orchestrator/tests/fixtures/m1_vision_worker.py L11–97；SHA256 `08532caad6169d0cbe2b66c1f0c6f4e3e04d19f64523a63973ff0518a267a084`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F03,F05,F07

## G16 M2 Result

|字段|记录|
|---|---|
|Protocol Rule|精确根字段、原生身份类型、产物一致|
|Current M1|M1 result根宽松、identity严格|
|Current M2|WorkerOutcome.envelope失败时可额外detail|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|Joint|
|Required Change|去未声明字段并独立验Result和产物|
|Test|detail/非零exit+code0/缺result|

[REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:263) — orchestrator/services/vision_supervisor/supervisor.py L263–415；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03,F07,F08

[M2_ENVELOPE](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:75) — src/vision/worker.py L75–87；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F08

[M2_FINISH](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:1020) — src/vision/worker.py L1020–1036；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F08

## G17 M2 错误处理

|字段|记录|
|---|---|
|Protocol Rule|2004须精确subtype allowlist；9001/3004禁retry|
|Current M1|retryable仅数值+transient可放2004|
|Current M2|backend初始化映射2004 transient，未见独立受审subtype|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P1|
|Owner|Joint|
|Required Change|严格2004策略，保持typed cancel分离|
|Test|typed cancel/transient2004/9001/3004/3001|

[RETRY_PREDICATE](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:36) — orchestrator/services/vision_supervisor/supervisor.py L36–39；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F08,P2-DOC-01

[CANCEL](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:31) — orchestrator/services/vision_supervisor/supervisor.py L31–33；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F08,P2-DOC-01

[M2_REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:906) — src/vision/worker.py L906–996；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F07

## G18 来源与评测

|字段|记录|
|---|---|
|Protocol Rule|M2来源UNKNOWN不得伪造，M5证据独立|
|Current M1|M1 current checkout哈希可追溯|
|Current M2|仅ZIP来源，无可信branch/HEAD；全量SDK路径和M5未验|
|Gap|未满足或未证明正式规则；以上具体行为为据|
|Severity|P2|
|Owner|Joint|
|Required Change|保留UNKNOWN，后续补真实来源/准确率验收|
|Test|不以历史仓库替代归档|

[M2_HISTORY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/docs/WORKER_INTERFACE.md.txt:1) — docs/WORKER_INTERFACE.md L1–214；SHA256 `4da67591707ffb2049c0f413bbf38377f544f18d1c7af53827d9e891351327ea`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F01,F07,F08

[M2_ENTRY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/scripts/m2_vision_worker.py.txt:1) — scripts/m2_vision_worker.py L1–23；SHA256 `77766ae66df5ac0e617d3a6d8c1da9d7c45ba7bdb5ec16e46ff811e0bcb8890c`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F07

## 规范性授权与实现证据

[APPROVAL](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/OWNER_EXECUTION_ORDER.txt:1) — 已粘贴的文本.txt L1–884；SHA256 `a83d0b03e66c95279bdf11d511723c2eb1d710b4f5873f68c81365e651aa079f`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F01,F02,F03,F04,F05,F06,F07,F08
