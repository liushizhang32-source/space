# 成员3 v1.1.6 最终 PR 审查

日期：2026-11-09（Asia/Hong_Kong）。

## 1. 结论与审批边界

**A：通过最终审查，可以提交 Commit、Push 并创建 PR，等待队长批准合并。**

此代码审查结论以队长已确认的 dev 基准 **b946bc9** 为准：本地分支包含该基准，R01/R02 修复及整体回归均通过。本轮没有提交、推送、创建 PR 或合并。

**远程实时限制：**本次两次安全 fetch 失败，不能证明远程在已确认基准之后没有新提交。正式提交推送前需恢复连接并重新获取 dev；若发现新的 dev 未被本分支包含，应暂停后续操作，先向队长报告差异，不自动 merge/rebase。本结论不等于实时远程同步已经成功，也不是自动执行 Git 操作的授权。

## 2. Git 分支、基准和全部差异

工作区：`C:/Users/16173/Documents/ChatGPT/人工智能+/space-member3-v116-integration`。

| 检查 | 结果 |
|---|---|
| 当前分支 | integration/member3-v1.1.6 |
| origin fetch/push | https://github.com/liushizhang32-source/space.git |
| HEAD | b946bc9e6618231481448692d055c029e073b7ee |
| origin/dev 本地跟踪引用 | 同一 SHA |
| merge-base(HEAD, origin/dev) | 同一 SHA |
| origin/dev 是否为 HEAD 祖先 | 是，二者当前相等 |
| 相对缓存 dev 提交差异 | 领先 0、落后 0，无新增 Commit |
| 暂存差异 | 空 |
| 未暂存已跟踪差异 | core/config.py、main.py |
| 本轮前未跟踪文件 | 101 个，属于既有集成成果、原交付、测试及报告 |

本轮新增最终报告后，未跟踪文件为 102 个。Git diff 不显示未跟踪内容，故审查另核对了新文件清单、来源及 SHA；不能把它们遗漏，或误认为这些成果已提交到 GitHub。当前远程尚无本轮非空 PR 提交差异，需要队长另行批准后准备提交与推送。

### 远程查询

HTTP/1.1、有限低速超时、禁止交互凭证输入的 fetch 两次分别退出 1：

1. Empty reply from server。
2. Recv failure: Connection was reset。

上一修复轮 fetch 成功、确认 b946bc9 的记录保留；本轮只能验证本地引用与队长指定版本一致，不能代替本次实时查询。没有要求 Token、强制同步、切换分支或覆盖工作区。

### 其他成员工作

本隔离目录的待审集合与之前集成/修复清单及来源一致，未发现混入成员2代码。Git 不记录未提交文件的作者，因此不虚构作者身份保证。原 `space` 工作区的成员2未提交改动仍在原位，没有复制到本分支，也没有清理或覆盖。未发现适用 AGENTS.md。

## 3. 相对 dev 的代码修改清单

| 类型 | 路径 | 用途 |
|---|---|---|
| 修改既有文件 | orchestrator/core/config.py | 默认 mock、后端选择、媒体工具路径及本地安全词表 |
| 修改既有文件 | orchestrator/main.py | 配置选择原 Jobs 或 Member3Jobs；不改 routes/响应结构 |
| 新增 | orchestrator/services/member3_adapter.py | 固定视觉输入、原成员3调用、公共模型/媒体验证、私有工作目录和发布 |
| 新增 | orchestrator/services/member3_jobs.py | executor 生命周期、分阶段调度、取消/关闭与错误映射 |
| 新增 | orchestrator/tests/test_member3_integration.py | 原 21 项集成回归 |
| 新增 | orchestrator/tests/test_member3_lifecycle.py | 新 10 项 R01/R02 回归 |
| 新增 | orchestrator/tests/pytest.ini | 独立测试配置，不继承旧根配置禁用 tmpdir 的行为 |
| 新增 | orchestrator/vendor/member3_v116/ | 原交付完整 91 文件，不改原代码或原测试 |
| 新增 | orchestrator/vendor/MEMBER3_V116_PROVENANCE.json | ZIP 版本、SHA、逐文件 SHA |
| 新增 | docs/MEMBER3_V116_INTEGRATION.md | 后端切换、Windows 启动及回归说明 |
| 新增 | reports/MEMBER3_V1.1.6_ISOLATED_INTEGRATION_REPORT.md | 历史隔离集成记录 |
| 新增 | reports/MEMBER3_V1.1.6_PR_REVIEW.md | 上轮失败审查记录，未改写历史结果 |
| 新增 | reports/MEMBER3_V1.1.6_INTEGRATION_FIX_REPORT.md | R01/R02 修复与验证记录 |
| 本轮新增 | reports/MEMBER3_V1.1.6_FINAL_PR_REVIEW.md | 本最终审查 |

91 文件完整列表见 provenance；其余均已逐项列出。作者参考 artifacts/样本随原交付保存，不把它们冒充本轮模型结果；本轮运行 XML、媒体、日志、工具和虚拟环境位于仓库外，不加入本次提交清单。

## 4. R01 最终复核

**通过。**

- close 共享唯一 `_shutdown_task`，开始后即置 `_shutting_down`，create/work 均拒绝新注册。
- 登记真实 concurrent.futures.Future，工作线程与 asyncio 控制任务的取消状态分离。
- 每次提交只有一个 drain 包装，shield 等待；重复取消设置同一协作标志并继续等待原 drain，不重新创建 gather。
- 已进入原生成代码的线程等待自然返回；不将 asyncio Task 取消当作物理停止，也不修改 vendor 增加危险强杀。
- shutdown 避免再次取消已经取消中的控制任务；共享的 job/worker drain 完成后才关闭 executor。
- session 清理在实际工作排空之后执行，不在 shutdown 中注册新清理 worker。成功清理幂等，恢复备份 preserve 逻辑保留。
- 取消与工作异常同时出现时取回异常；不能把后台异常遗漏成未检索 Future 错误。
- cancelled 沿用既有“取消请求生效”语义；实际线程结束以 Future/drain 为准，不新增公共状态枚举。

原 force→shutdown 失败探针已原样重跑通过。新增事件测试覆盖后台执行时 force、多次取消、多 close 共享任务、close 等待期间取消、新 worker 拒绝、线程完成后仅清理一次及取消任务状态。

本轮未发现支持范围内的新死锁/线程提前清理问题。不保证不可返回的任意第三方函数能立刻停下：协作取消仍须等待本地调用返回。私有 shutdown task 的外部直接篡改、进程强杀、全部操作系统故障不在公开生命周期保证中。

## 5. R02 最终复核

**通过。**

- 用本次 mkdtemp 返回的局部 workdir 明确目录范围。
- 配置构造、ensure_dirs、其余初始化在异常保护中；成功返回构造器后才向调用方移交完整 Session。
- 初始化失败只清理唯一 workdir，不删除 `.member3` base 或其他 session。
- 清理的 OSError/普通异常记内部日志，重新抛原始初始化异常，不被清理异常替换。
- Session close 幂等，保留恢复备份时不误删。

配置构造失败、ensure_dirs 失败与三种清理结果（成功/权限错误/RuntimeError）的交叉检查全部通过；原异常对象保持，另一 session 的标记文件和 base 目录仍存在。上轮初始化失败遗留目录探针通过。

mkdtemp 前父目录创建失败或 mkdtemp 自身失败时尚无本次成功分配的 workdir；不据此删除公共父目录。清理因系统权限失败时可能有已记录的故障证据残留，不能承诺磁盘在不可写状态下一定清空。

## 6. 整体 Adapter、API、Schema 与安全

- 默认仍为 Mock；42 项原 API 测试在未设置后端环境变量时运行并通过。member3 必须显式选择，非法后端拒绝。
- 新代码仅导入 `orchestrator.vendor.member3_v116`，不误用根目录旧 agents；91 文件 SHA 与批准版本一致。
- 固定 OCR/VLM 夹具用公共模型校验，ID/边界来自 Capture；没有成员2真实模型。
- Story 使用原 builder 和 DeferredTTS 分阶段适配，公共 StoryData 检查 scene、ID/高亮当前页归属、时长/audio_url 等要求。
- TTS 采用静音引擎，Video 实际合成；配置显式构造，不读取真实 LLM/供应商凭证。
- 生成前后、TTS、Video、发布前有安全关卡；3004 不降级成成功，blocked 不公开本任务 URL。
- 音视频深度解码通过才收录，并核对验证时、发布前与发布副本 SHA。丢失、损坏或变更不会以成功媒体 URL 返回。
- 原 Mock 的 Jobs/Storage、API routes/models、公共 Schema、冻结 API 文档对指定 dev 差异均为空。
- 任务成功、明确失败、partial_failed 降级、幂等、批量错误、force、统一错误及 trace 均有回归覆盖，没有引入额外 HTTP 路由或必填请求字段。

未发现密钥/真实 `.env`/依赖二进制被加入交付。新集成代码没有个人绝对路径硬编码；原包 Windows 字体候选是系统回退路径。保留原 Mock 和 vendor 版本有意隔离，存在维护成本，但不以覆盖旧服务解决。

## 7. 依赖与 Windows 兼容性

原 dev 和当前集成的既有依赖清单没有差异，vendor 的范围与其交集兼容，没有新增必要 Python 运行库。

- 主测试环境：Python 3.12.14、Pydantic 2.14.2、FastAPI 0.162.0、Starlette 0.50.0、pytest 9.2.0、Pillow 13.0.0。
- 原 requirements 固定 Pydantic 2.14.1，补丁差异明确保留，不擅自改 pin。
- 已核对上轮 PR 审查的独立 Windows pinned-env 安装记录：组合 requirements 从官方 PyPI 安装成功，版本实际为 Pydantic 2.14.1；pip check 通过。
- 上轮该锁定环境的 Schema 409/API 42/集成 21 均通过；此次核对其版本、命令与 XML，未把这些历史补丁矩阵重算为本轮新测试。
- 本轮重新运行完整指定组使用现有 2.14.2 环境；R01/R02 主要变化在 Python 生命周期而非模型字段。
- FFmpeg/FFprobe 9.0.2 的本地 Windows 执行与真实媒体解码通过。未安装/升级现有依赖，未宣称覆盖全部 Python/OS/架构组合。

## 8. 本轮重新执行的完整结果

所有下列结果为本轮新日志/XML，不是只引用旧报告。

| 组 | 通过/总数 | 失败/error/skip/xfail | 子进程退出码 |
|---|---|---|---:|
| Schema | 409/409 | 0/0/0/0 | 0 |
| 原 API | 42/42 | 0/0/0/0 | 0 |
| 成员3原测试 | 134/134 | 0/0/0/0 | 0 |
| 成员3增强 | 12/12 | 0/0/0/0 | 0 |
| 原集成 | 21/21 | 0/0/0/0 | 0 |
| 生命周期回归 | 10/10 | 0/0/0/0 | 0 |
| 上轮原失败探针 | 2/2 | 0/0/0/0 | 0 |
| 真实 HTTP | 12/12 | 0（独立检查组） | 全部断言通过 |

不汇总重复环境/重复执行数量；134 已包含作者版本新增回归，2 项探针独立列示，不充作原 21 项新增数。没有删除、skip、xfail 或弱化旧测试；Schema/API/集成/生命周期采用 -W error。

本轮 HTTP 在本机端口 54613 实际运行 Capture→Generate→Jobs done→静态产物读取；MP3/MP4 完整解码、公共模型、trace 和错误响应通过。驱动耗时约 6.262 秒，PID 30100 正常退出 0，端口关闭。没有调用真实模型、消耗模型额度或公开服务。

## 9. 未解决问题与 PR 建议

R01/R02 在本轮覆盖范围内已关闭，未发现新的局部代码阻塞。保留如下范围限制：

1. 本次实时 fetch 失败；后续提交推送前必须核对实际最新 dev。若不再是已确认的 b946bc9，应先报告差异，等待队长决定。
2. 仍未验证真实 LLM/TTS/外部安全服务与真实内容质量；固定 MOCK/静音不能当真实模型验收。
3. 多进程同页写、跨文件读者原子一致性、强杀恢复、严格墙钟预算和压力负载未完整验收。首次部署仍应按现有隔离/单进程前提。
4. 全部成果未提交、未推送；创建非空 PR 前必须另行完成经批准的提交与推送。本轮仅给出建议，未执行。

建议队长批准后准备 Commit、Push 和指向 dev 的 PR，由队长审批合并；同时保留远程复核步骤。不要因本报告 A 而跳过同步检查或自动合并。

## 10. 证据和本轮保护审计

仓库外证据目录 R：

```text
C:/Users/16173/Documents/ChatGPT/人工智能+/module-review-20261109/member3-final-pr/
```

- before.json：本轮前 182 个项目文件的 SHA 快照。
- status.txt、commits.txt、unstaged.txt、staged.txt、new-files.txt、origin.txt：Git 现场。
- FINAL_SUMMARY.json：分组结果、原文件不变、vendor 不变、保护范围差异及 fetch 错误。
- logs/schema.xml、api.xml、member134.xml、additional.xml、integration.xml、lifecycle.xml、review-boundaries.xml：本轮分组结果，均在 logs/ 下。
- run-results.json、orchestrator-results.json、additional-results.json、review-boundaries-command.json：完整命令/退出码。
- http-integration-results.json、logs/http_integration_server.log、downloads/：实际 HTTP、服务退出与媒体证据。
- 上轮补丁矩阵来源：`module-review-20261109/member3-pr-review/` 的 pinned 安装/测试记录。

测试使用已核实解释器、最小环境、空模型凭证和进程级 guard；仅许可本地媒体工具与回环，未调用真实模型。运行数据、日志、工具和审查驱动全部在 R，不加入 PR。

收尾再次核对：除本报告外，本轮开始时的已有项目文件 SHA 不变；没有修改业务、公共契约、公共 Schema、原 ZIP、原始交付、原测试或其他成员工作。git diff --check 通过，无新增暂存/Commit/Push/PR/合并。

**A：通过最终审查，可以提交 Commit、Push 并创建 PR，等待队长批准合并。**
