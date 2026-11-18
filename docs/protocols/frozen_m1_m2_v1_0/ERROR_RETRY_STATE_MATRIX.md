# 错误状态与持久化两次 Attempt

协议：M1_M2_OFFLINE_PROTOCOL_V1.0 · FROZEN · OWNER_APPROVED · 2026-11-13

仅限 Fake/Stub 离线接口。协议冻结不等于代码符合性验收；禁止本任务改核心源码、联调或发布 dev。


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


## 规范性授权与实现证据

[APPROVAL](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/OWNER_EXECUTION_ORDER.txt:1) — 已粘贴的文本.txt L1–884；SHA256 `a83d0b03e66c95279bdf11d511723c2eb1d710b4f5873f68c81365e651aa079f`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F01,F02,F03,F04,F05,F06,F07,F08

[RETRY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:243) — orchestrator/services/vision_supervisor/supervisor.py L243–261；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07,F08

[RETRY_PREDICATE](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:36) — orchestrator/services/vision_supervisor/supervisor.py L36–39；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F08,P2-DOC-01

[CANCEL](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:31) — orchestrator/services/vision_supervisor/supervisor.py L31–33；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F08,P2-DOC-01

[REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:263) — orchestrator/services/vision_supervisor/supervisor.py L263–415；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03,F07,F08

[LIMIT](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:197) — orchestrator/services/vision_supervisor/supervisor.py L197–208；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07,F08

[UNKNOWN](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/lease_core.py.txt:266) — orchestrator/services/mock_core_round2/lease_core.py L266–316；SHA256 `bd957221e2ea61003d7b6601a210691b81dd93b52114620eee1bd80e860d2081`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F08

[LOOKUP](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/lease_core.py.txt:210) — orchestrator/services/mock_core_round2/lease_core.py L210–225；SHA256 `bd957221e2ea61003d7b6601a210691b81dd93b52114620eee1bd80e860d2081`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F08

[JOB_STATE](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/core.py.txt:112) — orchestrator/services/mock_core_round2/core.py L112–145；SHA256 `d82cbddcb9417a5d7f92be9b6da14da14c4c4386377b7d259cf19b6f1eb4b24f`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F08

[PIPELINE](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/pipeline.py.txt:118) — orchestrator/services/vision_supervisor/pipeline.py L118–145；SHA256 `92b8736d8847ea572e94d6eeda903abc17c330ba865b8af7fe881d616aa96fa1`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07,F08
