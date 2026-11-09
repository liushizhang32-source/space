# 成员3 v1.1.6 PR 前最终审查

日期：2026-11-09（Asia/Hong_Kong）。本轮为只读审查与复测，仅新增本报告，不修业务代码。

## 1. 最终结论

**B：存在局部问题，修复后重新审查。**

原定六组回归全部通过，默认 Mock、模板 Story、静音 TTS、实际 Video 和真实 HTTP 闭环保持正常；Windows 锁定依赖环境安装及关键回归也通过。但本轮补充生命周期故障检查有 **2 项失败**：

- R01：force 后关闭服务引发重复取消，私有会话清理可能先于工作线程结束。
- R02：会话构造阶段失败，刚创建的私有目录没有清理所有者。

两处问题均位于本项目新增的集成 Adapter/调度层，不是成员3 v1.1.6 原交付源码的新失败。

此外两次远程 fetch 均失败，**无法确认最新 dev**。因此不能据缓存引用和原有绿灯放行 PR。本轮没有创建 PR、提交、推送、合并或改业务源码。

上一轮隔离集成 A 是当时覆盖范围的结果；本轮新增边界覆盖后，PR 建议更新为 B，不把新失败隐藏在原 21 项通过中。

## 2. Git 现场和远程核对

工作区：`C:/Users/16173/Documents/ChatGPT/人工智能+/space-member3-v116-integration`。

| 项目 | 实际值 |
|---|---|
| 当前分支 | integration/member3-v1.1.6 |
| origin fetch/push | https://github.com/liushizhang32-source/space.git |
| 当前 HEAD | b946bc9e6618231481448692d055c029e073b7ee |
| HEAD 说明 | Merge pull request #1 from liushizhang32-source/feat/generation |
| 本地缓存 origin/dev | 同一 SHA |
| 相对缓存 origin/dev 的领先/落后提交 | 0 / 0 |
| 本轮前待审修改 | 2 个已有文件修改、98 个未跟踪新文件 |
| 暂存的新修改 | 无 |

集成成果仍在工作区，**尚未形成分支提交差异**。`git diff origin/dev` 只能显示两个已跟踪文件，另外 98 个新文件必须单列；不能把它们遗漏，也不能把本地未提交成果误认为 GitHub 已有可创建的 PR 差异。

本轮新增报告后，新文件为 99 个。本轮没有切换、reset、stash、清理或覆盖其他工作区，原 `space` 的 dev 及既有成员2修改保持不动。没有修改 main/dev 引用，也没有改全局 Git 配置；Git ownership 检查使用单次命令 safe.directory 参数。

### 远程更新失败

两次均使用 HTTP/1.1、有限低速超时、禁止交互式凭证输入，执行 `fetch --no-tags origin dev`：

1. 退出 1：`Recv failure: Connection was reset`。
2. 退出 1：`Failed to connect to github.com:443 after 21069 ms: Could not connect to server`。

没有权限/凭证绕过，没有要求 Token。只能对缓存 `b946bc9` 做本地差异审查，不能宣称“远程没有队友新提交”。恢复网络后须重新获取、检查最新 dev；本轮不自动同步、变基或合并。

## 3. 待审文件清单与差异分析

### 两个已跟踪文件

| 文件 | 差异与审查 |
|---|---|
| orchestrator/core/config.py | 增加 generation_backend（默认 mock）、媒体工具路径、词表配置和后端枚举检查；没有新增 HTTP 字段 |
| orchestrator/main.py | create_app 按配置选择原 Jobs 或 Member3Jobs；现有路由、响应处理和静态挂载复用 |

### 98 个未跟踪交付文件（本轮前）

| 组 | 文件/数量 |
|---|---|
| Adapter/调度 | member3_adapter.py、member3_jobs.py，共 2 |
| 集成回归/配置 | test_member3_integration.py、pytest.ini，共 2 |
| 说明 | docs/MEMBER3_V116_INTEGRATION.md，共 1 |
| 上轮集成报告 | reports/MEMBER3_V1.1.6_ISOLATED_INTEGRATION_REPORT.md，共 1 |
| 溯源 | orchestrator/vendor/MEMBER3_V116_PROVENANCE.json，共 1 |
| 完整原交付 | orchestrator/vendor/member3_v116/，共 91 |

完整相对路径见附录；本轮报告另列，不重复算入待审原成果。

### 公共契约和已有服务

对缓存 origin/dev 核对，下列差异为空：

- docs/API_v1.0.md。
- orchestrator/schemas/ 全部公共 Schema。
- orchestrator/api/ 的 routes/models 及请求响应声明。
- 原 orchestrator/services/jobs.py、storage.py。
- 既有依赖清单。

Capture、Generate、Jobs 的路径、请求格式、统一 code/msg/data/trace_id 结构未改；默认后端 API 的 42 项原断言全部通过。member3 模式的实际生成、错误/降级是配置选择后的行为，不能将其解释为默认 Mock 也改成新模块。

## 4. Adapter 设计审查

### 符合预期的设计

- 默认 `GENERATION_BACKEND=mock`；显式 member3 才加载新实现，非法值拒绝。
- 使用 `orchestrator.vendor.member3_v116` 独立命名空间，避免误用 dev 根目录已有的旧 agents。完整 91 文件 SHA 与批准的 v1.1.6 来源一致，没有修改 vendor 源码。
- 配置显式构造为模板 Story + silent TTS，LLM/HTTP TTS/密钥字段不从真实环境加载；OCR/VLM 固定数据通过公共 Schema，不接成员2真实模型。
- Story 使用原 builder 的安全与规范化，通过 DeferredTTS 将真实合成留给 Jobs 的 tts 阶段；属于阶段适配，没有复制 Story 生成算法。
- TTS/Video 深度解码验证；发布前与发布副本检查验证时 SHA，丢失/变更媒体不作为成功 URL 返回。
- 普通 TTS、Render 失败按 no_audio/no_video 降级；安全错误保持 3004/blocked，停止后续阶段，不发布本任务产物。
- 耗时步骤放在线程中，每任务页使用唯一私有目录；同页 force 不让旧工作线程直接写公开产物。
- 恢复失败保留备份并在内部日志记录，不泄漏恢复路径到公共 Jobs 数据。

### 重复和边界

原 Jobs 的创建/幂等/get/close 被继承；运行状态循环单独实现，属于新后端所需差异。根目录旧成员3和 vendor 副本确实并存，但为避免覆盖旧服务的有意隔离；应保持命名空间明确，后续统一版本另行审查。

不是所有生命周期分支都已安全：下节 R01/R02 为实际复现的问题。逐文件 os.replace 也不是跨文件事务；并发读者、多进程同页写、硬终止等没有因此自动获得保证。

## 5. 新发现的问题

### R01：重复取消会打断 worker drain，清理早于线程完成

- 严重程度：**P1，PR 前应修复**。
- 路径/行：`orchestrator/services/member3_jobs.py:19–26`，尤其第 25 行；`member3_jobs.py:87–90`；触发链包括原 `jobs.py:41` 的 force cancel 和 `jobs.py:100–103` 的 shutdown cancel。
- 原因：首次取消在 shield(worker) 被捕获后，直接 await gather(worker)。第二次取消可传播进这个未受保护的 gather，使 asyncio 的 worker Task 取消，但底层 to_thread 线程仍在运行。run 的 finally 随后调用 session.close。
- 复现：审查方以 Event 阻塞实际 Member3Jobs 所调度的工作函数，真实调用 create(force=True)，随后调用 Jobs.close；使用会话清理钩子观测顺序。观察到 `cleanup_before_worker_finished=true`，原任务为 cancelled，确实创建了替代任务。
- 用例：仓库外 `test_pr_boundaries.py:18–67`，`test_force_then_shutdown_does_not_cleanup_a_running_worker`，失败。
- 影响：真实 session.close 会删除私有目录，可能与仍在写入该目录的生成线程竞争，破坏临时文件收尾或恢复过程。当前私有目录设计仍限制公开目录写入；本次没有证明旧线程覆盖公开产物或视频已经损坏。
- 证据边界：探针证明清理钩子调用早于线程结束；未证明 shutdown 已经返回。该观察时 `shutdown_returned_before_worker_finished=false`，不夸大为提前结束服务的已证实事实。
- 建议：优先在 Member3Jobs 生命周期内处理已在取消/清理中的任务，防止 close 再次打断 drain；对每次取消后的等待都保护实际工作完成，维护真实工作完成状态，等线程完成后再删除目录。不要只依赖被取消的 asyncio Task 的 done 状态，也不要通过忽略取消或删断言掩盖问题。
- 验收：加入 force→立即 shutdown、多次取消与清理顺序回归，保证线程真实结束后才 cleanup；保留原 21 项。

### R02：会话构造失败后，私有目录泄漏

- 严重程度：**P2，PR 前应修复**。
- 路径/行：`orchestrator/services/member3_adapter.py:69–83`，尤其 mkdtemp 第 76 行与 ensure_dirs 第 83 行；调用方 `member3_jobs.py:42、87–90`。
- 原因：构造器先创建目录，再初始化子目录。ensure_dirs 失败时，调用方尚未拿到 session，finally 看到 session=None，无法清理新目录。
- 复现：只将 MemberSettings.ensure_dirs 注入为 PermissionError；构造器抛出预期异常后，`.member3` 留有 1 个新目录。
- 用例：仓库外 `test_pr_boundaries.py:70–81`，`test_session_initialization_failure_cleans_its_new_directory`，失败。
- 影响：权限或磁盘故障反复出现时可积累无所有者的工作目录。此用例证明目录泄漏，不声称已泄漏音频、密钥或隐私内容。
- 建议：构造/工厂用异常安全的目录所有权管理；初始化失败时清理本次创建目录并保留原异常，成功后再移交 session 生命周期。不要删除别的任务或恢复备份目录。
- 验收：补目录创建后初始化失败的清理回归，检查原错误仍正确映射、没有遗留目录。

两项探针均在仓库外，只做内存故障注入；没有修改业务文件。探针 finally 释放并等待线程完成，没有将测试留下的线程当作已关闭服务。故障证据目录保留供复核。

## 6. 默认 Mock、API 和 Schema 验证

- 主回归子进程没有设置 GENERATION_BACKEND，原 API 测试仍选择默认 Mock；原视频/音频固定素材、queued/running、幂等、force、异常响应的断言保持通过。
- member3 回归显式设置后端：StoryData、scene、高亮当前页归属、audio_url、媒体解码和任务终态正常。
- 安全拒绝、损坏音视频、输入不合规、素材缺失、发布前音频丢失、最终安全拒绝均有原 21 项覆盖且通过。
- 新增 R01/R02 揭示原范围之外的失败路径；“原 21 项通过”不等于这些生命周期路径通过。
- API/schema 文件和公共请求/响应没有变更。OCR/VLM 是固定 MOCK 数据，confidence=1 只是固定夹具值，不表示真实识别可信度。

## 7. 依赖差异与 Windows 安装

### 约束比较

dev 和集成工作区原有 requirements 无差异。新增 vendor requirements 只是原交付声明，与已有依赖交集兼容：

| 依赖 | 原 Orchestrator | vendor | 本轮主环境 |
|---|---|---|---|
| Pydantic | ==2.14.1 | >=2.9,<3 | 2.14.2 |
| FastAPI | ==0.162.0 | >=0.115,<1 | 0.162.0 |
| Starlette | ==0.50.0 | 未额外指定 | 0.50.0 |
| Uvicorn | ==0.54.0 | >=0.30 | 0.54.0 |
| Pillow | ==13.0.0 | >=10 | 13.0.0 |
| pytest（测试） | ==9.2.0 | >=8 | 9.2.0 |

没有新增必须引入的 Python 第三方运行库；FFmpeg/FFprobe 是既有已核实便携系统工具，不是自动安装的模型或 Python 依赖。依赖范围不存在本轮发现的冲突，不要求为让测试通过改 pin。

### 实际 Windows x64 / Python 3.12.14 检查

1. 官方 PyPI、仅二进制 wheel、ignore-installed 的 pip dry-run：退出 0，能解析组合 requirements，包含 Windows CP312 wheel。
2. 在审查目录独立创建 pinned-env，将原 API 测试 requirements 和 vendor requirements 组合安装：退出 0，实际安装 Pydantic 2.14.1。
3. 新环境导入版本确认：Pydantic 2.14.1 / FastAPI 0.162.0 / Starlette 0.50.0 / pytest 9.2.0；pip check 退出 0，无 broken requirements。
4. 锁定环境重复验证 Schema 409/409、原 API 42/42、集成 21/21，均退出 0。没有把这些相同用例再加进主测试总数。

主环境依旧为 2.14.2，未升级/降级既有解释器。临时环境、wheel 安装元数据和解析日志均在仓库外，不加入 PR。真实依赖安装只访问官方 PyPI，不调用模型 API。

因此此前 Pydantic 补丁差异已完成 Windows 安装及上述关键回归验证，不作为本轮未解决阻塞。没有在新环境重复运行成员3 134/增强12/真实HTTP，也没有验证所有 Python/OS/架构组合；不作全平台保证。

## 8. 本轮实际回归结果

主解释器：`C:/Users/16173/Documents/ChatGPT/人工智能+/.venv-schema-tests/Scripts/python.exe`，Python 3.12.14、Pydantic 2.14.2、pytest 9.2.0；FFmpeg/FFprobe 9.0.2。

| 主测试组 | 数量 | 通过 | 失败 | error / skip / xfail | 子进程退出码 | pytest 自身耗时 |
|---|---:|---:|---:|---:|---:|---:|
| Schema | 409 | 409 | 0 | 0 / 0 / 0 | 0 | 0.679 秒 |
| 原 FastAPI API | 42 | 42 | 0 | 0 / 0 / 0 | 0 | 4.104 秒 |
| 成员3原完整测试 | 134 | 134 | 0 | 0 / 0 / 0 | 0 | 28.259 秒 |
| 成员3增强检查 | 12 | 12 | 0 | 0 / 0 / 0 | 0 | 1.076 秒 |
| 原新增集成测试 | 21 | 21 | 0 | 0 / 0 / 0 | 0 | 14.461 秒 |
| 本轮审查补充生命周期检查 | 2 | 0 | 2 | 0 / 0 / 0 | 1 | 0.551 秒 |

真实 HTTP 集成另计 **12/12**，不是 pytest 数，也不加到作者 134 中。补丁环境是相同用例的环境复测，不累计为新增覆盖。

原定六组均通过，但本轮 PR 审查总体未通过，因为附加检查有两项失败且远程基准未验证。未删除、skip、xfail、放宽任何原测试，也未通过修改代码将故障变绿。

### Windows 锁定补丁环境（重复用例，独立矩阵）

| 组 | Pydantic 2.14.1 结果 | 退出码 |
|---|---|---:|
| Schema | 409/409 | 0 |
| API | 42/42 | 0 |
| 集成 | 21/21 | 0 |

### 真实 HTTP / 媒体验证

实际新 DATA_DIR、member3 Uvicorn，监听本机 `127.0.0.1:63929`。Capture、Preview、Generate、活动幂等、Jobs 轮询、固定 OCR/VLM 公共模型、StoryData、音频下载解码、MP4 下载解码、不存在 job 的统一错误和私有目录正常清理 12 项全部通过。

观察状态 queued→running→done，进度 0→80→100；按 2 秒轮询，不编造未观察到的逐阶段瞬时状态。终态阶段均 ok，Story 与媒体从同一 Orchestrator 静态挂载读取，无额外资源网关。

真实 HTTP MP3/MP4 下载后 FFmpeg 完整解码退出 0；FFprobe 确认视频 H.264+AAC、720×1280、25fps，Story 通过公共 Schema。全部是 MOCK 模板与静音，不是实际模型产物。

本轮 HTTP 驱动耗时 6.303 秒，PID 28400 正常退出 0，端口结束后及收尾再次检查均已关闭。TestClient 和补充探针也已收尾。

## 9. 文件、安全与可精简项

- 对待审源码做 AST、文件清单及典型密钥模式检查，没有发现实际 `.env`、私钥、API Key/Token 串或新安装的依赖二进制进入待审文件；没有输出疑似凭证值。此检查不宣称穷尽所有秘密格式。
- 新 Adapter/调度中无个人绝对路径硬编码。vendor demo.py:32、video.py:40–42 的 Windows 绝对路径是系统字体候选，属于可配置/回退逻辑，不是用户机器专属目录。
- 本轮生成的 XML、日志、下载媒体、pinned-env、工具、缓存均在仓库外；作者 `_test_tmp` 仅是原夹具运行目录，源码 SHA 不变，没有列为提交内容。
- vendor/artifacts 的参考 MP3/MP4 和历史文档来自原交付，是有意保留的来源材料，不是本轮伪装的新模型输出。它们不是 Adapter 运行必需；PR 可选择精简历史参考材料，但需保持测试样本和溯源清晰，不能混入本轮运行数据。本轮只记录，不删除文件。
- 根旧 agents 与完整 vendor 副本并存有维护成本；不以覆盖旧 Mock/旧模块的方式处理此成本，后续版本整理另行批准。
- 仓库当前没有本轮新增的自动 CI 门禁；手动已记录测试不等于 GitHub Actions 已验证。PR 申请时应附本报告/日志并由队长决定 CI 范围，不在本轮添加工作流。

## 10. 尚未解决和 PR 建议

必须先处理：

1. 修复 R01 重复取消与清理顺序，添加原范围未覆盖的回归。
2. 修复 R02 构造失败的目录所有权与清理，保留原异常语义。
3. 网络恢复后重新 fetch，核对真正最新 dev 的提交和差异；不根据缓存宣称无冲突。
4. 在重新审查通过且队长另行批准后，才准备可审查的提交/推送。当前没有领先 dev 的提交，GitHub 上尚不存在本轮代码可直接创建的非空 PR 差异。

继续保留的范围限制：真实模型/真实语音/外部审核质量、成员2真实模块、多进程同页写、跨文件读者一致性、硬超时/强杀恢复和全平台安装没有因此获得验收。本轮补丁环境的通过不会解决 R01/R02。

建议为 **B：修复后重新审查**，而非创建 PR。所有修复建议均待后续授权；本轮不修改现有实现、公共契约或原测试。

## 11. 证据、执行命令与变更保护

审查证据目录 R：

```text
C:/Users/16173/Documents/ChatGPT/人工智能+/module-review-20261109/member3-pr-review/
```

| 内容 | 证据（相对 R） |
|---|---|
| 原文件快照/状态/差异 | workspace-before.json、status-before.txt、diff-before.txt、commits-before.txt、new-files-before.txt |
| 远程失败 | remote-fetch-attempts.json |
| 待审文件来源/大小/SHA/扫描 | static-review.json、vendor 的 PROVENANCE 文件 |
| 六组复测命令 | run-results.json、additional-results.json、orchestrator-results.json、http-integration-results.json |
| 原测试 XML | logs/schema.xml、api.xml、member134.xml、additional.xml、integration.xml |
| 新问题复现 | test_pr_boundaries.py、run_review_probes.py、review-boundaries-command.json、logs/review-boundaries.xml/log |
| 两项故障观测 | logs/repeated-cancel-observation.json、logs/initialization-observation.json |
| Windows dry-run/实际安装 | dependency-dry-run-command.json、dependency-resolution.json、pinned-install-command.json、pinned-install.json |
| 锁定环境复测 | run_pinned.py、pinned-results.json、logs/pinned-*.xml/log、logs/pinned-versions.txt、logs/pinned-pip-check.log |
| 汇总/代码未改/服务退出 | FINAL_REVIEW_SUMMARY.json |

各测试驱动记录完整绝对 argv、cwd、退出码和耗时。使用最小环境、空模型/供应商配置和进程级 guard；测试阶段禁止外部 Python 网络、真实模型 SDK 和非媒体白名单进程；仅允许证据目录及作者原 `_test_tmp` 写入。不是虚拟机强隔离承诺。

初次并行启动驱动时，API 驱动读 runtime.json 早于基线初始化，出现一次审查工具初始化错误；待初始化完成后重新运行，最终业务测试结果如上。该初始化失败不算业务用例，也没有改原测试使其通过。

本轮开始时对 179 个已存在项目文件做 SHA 快照，收尾比对均未改变；公共文件、业务文件、原测试、原报告都不改。**项目内只新增本报告**，其余审查脚本、探针、安装环境及运行证据在 R。最终 git diff --check 通过，未新增暂存/Commit/Push/PR/合并。

**最终结论：B：存在局部问题，修复后重新审查。**

## 附录：本轮前的 98 个未跟踪交付文件

本轮新增的 `reports/MEMBER3_V1.1.6_PR_REVIEW.md` 不在下列原成果清单中。

```text
docs/MEMBER3_V116_INTEGRATION.md
orchestrator/services/member3_adapter.py
orchestrator/services/member3_jobs.py
orchestrator/tests/pytest.ini
orchestrator/tests/test_member3_integration.py
orchestrator/vendor/MEMBER3_V116_PROVENANCE.json
orchestrator/vendor/member3_v116/.env.example
orchestrator/vendor/member3_v116/.gitignore
orchestrator/vendor/member3_v116/PACKAGE.md
orchestrator/vendor/member3_v116/README.md
orchestrator/vendor/member3_v116/agents/__init__.py
orchestrator/vendor/member3_v116/agents/generation/__init__.py
orchestrator/vendor/member3_v116/agents/generation/__main__.py
orchestrator/vendor/member3_v116/agents/generation/cli.py
orchestrator/vendor/member3_v116/agents/generation/config.py
orchestrator/vendor/member3_v116/agents/generation/demo.py
orchestrator/vendor/member3_v116/agents/generation/envelope.py
orchestrator/vendor/member3_v116/agents/generation/errors.py
orchestrator/vendor/member3_v116/agents/generation/ids.py
orchestrator/vendor/member3_v116/agents/generation/media.py
orchestrator/vendor/member3_v116/agents/generation/pipeline.py
orchestrator/vendor/member3_v116/agents/generation/proc.py
orchestrator/vendor/member3_v116/agents/generation/safety.py
orchestrator/vendor/member3_v116/agents/generation/schemas.py
orchestrator/vendor/member3_v116/agents/generation/storage.py
orchestrator/vendor/member3_v116/agents/generation/story/__init__.py
orchestrator/vendor/member3_v116/agents/generation/story/builder.py
orchestrator/vendor/member3_v116/agents/generation/story/draft.py
orchestrator/vendor/member3_v116/agents/generation/story/llm.py
orchestrator/vendor/member3_v116/agents/generation/story/template.py
orchestrator/vendor/member3_v116/agents/generation/story/text.py
orchestrator/vendor/member3_v116/agents/generation/tts/__init__.py
orchestrator/vendor/member3_v116/agents/generation/tts/api.py
orchestrator/vendor/member3_v116/agents/generation/tts/client.py
orchestrator/vendor/member3_v116/agents/generation/tts/engine.py
orchestrator/vendor/member3_v116/agents/generation/tts/service.py
orchestrator/vendor/member3_v116/agents/generation/video.py
orchestrator/vendor/member3_v116/artifacts/README.md
orchestrator/vendor/member3_v116/artifacts/manifest.json
orchestrator/vendor/member3_v116/artifacts/story/cli_stdout.json
orchestrator/vendor/member3_v116/artifacts/story/input_ocr.json
orchestrator/vendor/member3_v116/artifacts/story/input_page.png
orchestrator/vendor/member3_v116/artifacts/story/input_vlm.json
orchestrator/vendor/member3_v116/artifacts/story/output_story.json
orchestrator/vendor/member3_v116/artifacts/story/schema_check.txt
orchestrator/vendor/member3_v116/artifacts/tts/probe.json
orchestrator/vendor/member3_v116/artifacts/tts/probe.txt
orchestrator/vendor/member3_v116/artifacts/tts/request.json
orchestrator/vendor/member3_v116/artifacts/tts/response.json
orchestrator/vendor/member3_v116/artifacts/tts/tts_sample.mp3
orchestrator/vendor/member3_v116/artifacts/video/book01_p03_video.mp4
orchestrator/vendor/member3_v116/artifacts/video/cli_stdout.json
orchestrator/vendor/member3_v116/artifacts/video/input_story.json
orchestrator/vendor/member3_v116/artifacts/video/output_video.json
orchestrator/vendor/member3_v116/artifacts/video/probe.json
orchestrator/vendor/member3_v116/artifacts/video/probe.txt
orchestrator/vendor/member3_v116/artifacts/video/schema_check.txt
orchestrator/vendor/member3_v116/docs/CHANGELOG.md
orchestrator/vendor/member3_v116/docs/GENERATION.md
orchestrator/vendor/member3_v116/docs/IO_EXAMPLES.md
orchestrator/vendor/member3_v116/docs/REVIEW_RESPONSE.md
orchestrator/vendor/member3_v116/docs/TEST_REPORT-v1.1.0.md
orchestrator/vendor/member3_v116/docs/TEST_REPORT-v1.1.1.md
orchestrator/vendor/member3_v116/docs/TEST_REPORT-v1.1.2.md
orchestrator/vendor/member3_v116/docs/TEST_REPORT-v1.1.3.md
orchestrator/vendor/member3_v116/docs/TEST_REPORT-v1.1.4.md
orchestrator/vendor/member3_v116/docs/TEST_REPORT-v1.1.5.md
orchestrator/vendor/member3_v116/docs/TEST_REPORT.md
orchestrator/vendor/member3_v116/docs/images/story-frame.png
orchestrator/vendor/member3_v116/docs/schemas/story.schema.json
orchestrator/vendor/member3_v116/docs/schemas/video.schema.json
orchestrator/vendor/member3_v116/examples/README.md
orchestrator/vendor/member3_v116/examples/book01_p03/book01_p03_ocr.json
orchestrator/vendor/member3_v116/examples/book01_p03/book01_p03_orig.png
orchestrator/vendor/member3_v116/examples/book01_p03/book01_p03_vlm.json
orchestrator/vendor/member3_v116/examples/install_example.py
orchestrator/vendor/member3_v116/pytest.ini
orchestrator/vendor/member3_v116/requirements.txt
orchestrator/vendor/member3_v116/scripts/verify.ps1
orchestrator/vendor/member3_v116/scripts/verify.sh
orchestrator/vendor/member3_v116/tests/conftest.py
orchestrator/vendor/member3_v116/tests/test_http_audio.py
orchestrator/vendor/member3_v116/tests/test_ids.py
orchestrator/vendor/member3_v116/tests/test_media.py
orchestrator/vendor/member3_v116/tests/test_pipeline.py
orchestrator/vendor/member3_v116/tests/test_regressions_v112.py
orchestrator/vendor/member3_v116/tests/test_regressions_v113.py
orchestrator/vendor/member3_v116/tests/test_regressions_v114.py
orchestrator/vendor/member3_v116/tests/test_regressions_v115.py
orchestrator/vendor/member3_v116/tests/test_regressions_v116.py
orchestrator/vendor/member3_v116/tests/test_safety_entrypoints.py
orchestrator/vendor/member3_v116/tests/test_schemas.py
orchestrator/vendor/member3_v116/tests/test_story.py
orchestrator/vendor/member3_v116/tests/test_story_schema_contract.py
orchestrator/vendor/member3_v116/tests/test_tts.py
orchestrator/vendor/member3_v116/tests/test_tts_service.py
orchestrator/vendor/member3_v116/tests/test_video.py
reports/MEMBER3_V1.1.6_ISOLATED_INTEGRATION_REPORT.md
```
