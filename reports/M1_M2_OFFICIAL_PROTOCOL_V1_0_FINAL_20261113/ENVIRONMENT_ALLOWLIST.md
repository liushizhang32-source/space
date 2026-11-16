# 环境变量逐项规则

协议：M1_M2_OFFLINE_PROTOCOL_V1.0 · FROZEN · OWNER_APPROVED · 2026-11-13

仅限 Fake/Stub 离线接口。协议冻结不等于代码符合性验收；禁止本任务改核心源码、联调或发布 dev。


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


## 规范性授权与实现证据

[APPROVAL](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/OWNER_EXECUTION_ORDER.txt:1) — 已粘贴的文本.txt L1–884；SHA256 `a83d0b03e66c95279bdf11d511723c2eb1d710b4f5873f68c81365e651aa079f`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F01,F02,F03,F04,F05,F06,F07,F08

[REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:263) — orchestrator/services/vision_supervisor/supervisor.py L263–415；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03,F07,F08

[SPEC](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:133) — orchestrator/services/vision_supervisor/supervisor.py L133–148；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07

[LEASE_RUN](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/mock_core_round2/lease_supervisor.py.txt:75) — orchestrator/services/mock_core_round2/lease_supervisor.py L75–99；SHA256 `71dc02888c253407db7cbebad157f506ffb47d090c5925c893205a0a9a644958`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F07,F08

[M2_FACTORY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/backends/__init__.py.txt:1) — src/vision/backends/__init__.py L1–43；SHA256 `7279b853be2b66b6ba26aa4d5bd049ff7c0c43eb6cfdd735868b9fd280063e07`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F07

[M2_HISTORY](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/docs/WORKER_INTERFACE.md.txt:1) — docs/WORKER_INTERFACE.md L1–214；SHA256 `4da67591707ffb2049c0f413bbf38377f544f18d1c7af53827d9e891351327ea`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F01,F07,F08
