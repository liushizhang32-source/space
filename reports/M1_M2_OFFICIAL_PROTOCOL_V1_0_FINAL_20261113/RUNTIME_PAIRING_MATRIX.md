# Profile A 优先、Profile B 独立

协议：M1_M2_OFFLINE_PROTOCOL_V1.0 · FROZEN · OWNER_APPROVED · 2026-11-13

仅限 Fake/Stub 离线接口。协议冻结不等于代码符合性验收；禁止本任务改核心源码、联调或发布 dev。


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

当前已有解释器路径 `C:\Users\16173\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`，M1 fixture 路径 `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor\orchestrator\tests\fixtures\m1_vision_worker.py`。M2 仍为 archive-only，未获准解包/安装或选择实际隔离根，因此不存在可诚实列出的已验证完整 M2 argv；占位项是规范参数，不是已执行命令。M2 CLI 实际精确一个 request 参数，不能传新参数强行接线。Profile A 执行接入 BLOCKED，协议和输入已有规范但代码不符合。B 独立保留，不与 A 拼成生产链。

超时来自 Supervisor 构造参数 deadline (0,30]，backoff=1；所有 retry 权威在 M1。新的跨进程 Stage attempt ledger 尚未满足；本包只定义。发布须先退出/排空、所有原字节 hash/Gate/fences 合法、可信 verify 后 atomic pointer；完整 M2+LEASE 生产链 NOT_CERTIFIED。


## 规范性授权与实现证据

[APPROVAL](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/OWNER_EXECUTION_ORDER.txt:1) — 已粘贴的文本.txt L1–884；SHA256 `a83d0b03e66c95279bdf11d511723c2eb1d710b4f5873f68c81365e651aa079f`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F01,F02,F03,F04,F05,F06,F07,F08

[SPEC](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:133) — orchestrator/services/vision_supervisor/supervisor.py L133–148；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07

[REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:263) — orchestrator/services/vision_supervisor/supervisor.py L263–415；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03,F07,F08

[PIPELINE](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/pipeline.py.txt:118) — orchestrator/services/vision_supervisor/pipeline.py L118–145；SHA256 `92b8736d8847ea572e94d6eeda903abc17c330ba865b8af7fe881d616aa96fa1`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07,F08

[PUBLISH](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/pipeline.py.txt:19) — orchestrator/services/vision_supervisor/pipeline.py L19–111；SHA256 `92b8736d8847ea572e94d6eeda903abc17c330ba865b8af7fe881d616aa96fa1`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F03,F08

[LEASE_ENTRY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/lease_runner.py.txt:7) — orchestrator/services/mock_core_round2/lease_runner.py L7–10；SHA256 `0afc31f65d4262e4bb6cc4c7a4f4b88ba697b0b37a32e839fd3123927350c799`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07

[LEASE_RUN](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/lease_supervisor.py.txt:75) — orchestrator/services/mock_core_round2/lease_supervisor.py L75–99；SHA256 `71dc02888c253407db7cbebad157f506ffb47d090c5925c893205a0a9a644958`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07,F08

[RUNNER](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/runner.py.txt:9) — orchestrator/services/mock_core_round2/runner.py L9–73；SHA256 `10f5e25117904d93d5994b868a6386bbd5c22d8031410576353585e1c03fbf10`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07,F08

[M2_ENTRY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/scripts/m2_vision_worker.py.txt:1) — scripts/m2_vision_worker.py L1–23；SHA256 `77766ae66df5ac0e617d3a6d8c1da9d7c45ba7bdb5ec16e46ff811e0bcb8890c`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F07

[M2_FACTORY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/backends/__init__.py.txt:1) — src/vision/backends/__init__.py L1–43；SHA256 `7279b853be2b66b6ba26aa4d5bd049ff7c0c43eb6cfdd735868b9fd280063e07`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F07

[FIXTURE_ARGV](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/tests/test_m1_vision_supervisor.py.txt:145) — orchestrator/tests/test_m1_vision_supervisor.py L145–151；SHA256 `53d7315f4fbc859a289c5e953d96d2370a7df519f6598e88d19ee6e796a18e3b`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07
