# 成员3 v1.1.6 集成层 R01/R02 修复报告

日期：2026-11-09（Asia/Hong_Kong）。

## 1. 最终结论

**A：两个问题均已修复，回归测试通过，可以重新申请 PR 审查。**

只修复集成层；成员3原交付、公共契约、公共 Schema、默认 Mock、成员2均未修改。原定所有测试组通过，上次失败的两项审查探针原样重放也已通过；新增生命周期回归 10 项通过。没有提交、推送、创建 PR 或合并，等待队长审核。

## 2. 现场与范围

- shell 初始目录：`C:/Users/16173/Documents/ChatGPT/人工智能+`；经 Git 确认的目标仓库目录：`C:/Users/16173/Documents/ChatGPT/人工智能+/space-member3-v116-integration`。
- 当前分支：`integration/member3-v1.1.6`。两个目标文件均存在，并与上次审查定位一致；未猜测或修改其他代码目录。
- 工作区原已有未提交集成成果，开始时对全部已有文件做 SHA 快照，保留这些成果，未 reset/stash/清理/覆盖。
- 本轮修改已有文件仅 `orchestrator/services/member3_jobs.py`、`orchestrator/services/member3_adapter.py`。
- 新增 `orchestrator/tests/test_member3_lifecycle.py` 和本报告。
- 成员3原 ZIP 保持独立，SHA-256 仍为 `d2e9b02963ded6df40e6e09e7dd0819d4bdf0b65bf197c28ec16ece569ac7fb6`；vendor 的全部 91 文件与 provenance 记录一致。
- API_v1.0.md、所有公共 Schema、原 Mock Jobs/Storage、main/dev 和成员2模块没有本轮改动。这里的 main.py 是既有应用入口，也未在本轮修改。

## 3. R01 根因与修复

### 根因

原 work 首次取消时转去等待未受保护的 gather(worker)。force 后 shutdown 再次取消控制任务，会打断该等待，asyncio 包装 Task 取消并不代表线程结束；finally 因此可能过早删除 session 目录。

### 新实现

1. Member3Jobs 管理专用 ThreadPoolExecutor，登记其返回的真实 concurrent.futures.Future；不以 asyncio Task.cancelled/done 代替线程完成判断。
2. 每个控制任务持有 threading.Event 协作取消标志。取消时只请求停止后续调度，未开始的调用可直接跳过；已进入原生成代码的线程允许自然完成，不强杀，也不改 vendor。
3. 每次提交只创建一个 asyncio.wrap_future 作为该工作的 drain；所有等待用 shield。重复取消时设置同一标志，并继续等待同一个 drain，不重新创建 gather。
4. 真实 Future 完成后才处理取消传播和移除登记；取消与工作异常同时发生时也取回异常，避免遗失后台错误。
5. close 共享唯一 `_shutdown_task`，一开始即关闭新任务/worker 注册入口。多个调用者及被反复取消的 close 调用者都等待同一个 shutdown；其内部 job drain/worker drain 各仅创建一次。
6. shutdown 不再对已经取消中的控制任务重复 cancel；先等控制任务与实际工作排空，最后关闭 executor。调用者自身被取消时，仍等共享 shutdown 完成后再传播 CancelledError。
7. session.close 仅在该页工作的真实 Future 已排空后调用，不在 shutdown 中另注册清理 worker；session 自身清理也幂等。
8. force/shutdown 后 job 保持现有 cancelled 语义。公开 cancelled 表示取消请求已生效，不宣称线程已物理停止；真实线程状态由登记 Future 判断，共享 shutdown 完成才代表排空。没有增加公共枚举。

没有通过 sleep 延迟删除来规避竞争。不能被协作打断的 vendor/FFmpeg 步骤仍需要等待自然返回；本轮没有承诺强制立即终止或修改其内部执行流程。

## 4. R02 根因与修复

### 根因

mkdtemp 成功后，配置或 ensure_dirs 构造失败，调用方还未获得 session，finally 无法清理新目录。

### 新实现

- 用局部 workdir 保存本次新建的唯一目录，初始化过程处于异常保护中。
- 任意初始化异常都尝试清理这一个 workdir，不删除 `.member3` base 或别的 session。
- 清理失败（包括 OSError 与其他普通异常）记录含 workdir 的内部日志，再重新抛原始初始化异常，不能让清理异常覆盖它。
- 成功完成所有初始化后才进入可交付 Session 生命周期；close 的 `_closed` 标志防止成功清理重复发生。
- 恢复失败时的 preserve 逻辑保持，不能把人工恢复备份当普通临时文件删除。

## 5. 新增回归及事件同步

文件：`orchestrator/tests/test_member3_lifecycle.py`，共 **10 项**：

| 场景 | 数量 | 核对内容 |
|---|---:|---|
| force、重复取消、共享 shutdown | 2 | 后台线程由 Event 保持运行；force 后再次取消；close 多调用共享同一任务；close 等待再被取消；拒绝新注册；真实 Future 不被取消；释放线程后仅清理一次；任务 cancelled |
| 初始化阶段 × 清理结果 | 6 | Settings 构造/ensure_dirs 失败；正常清理、PermissionError、RuntimeError 三种清理结果；原异常对象保持；其他 session 的标记文件及 base 目录不受影响；失败日志存在 |
| 取消中工作异常 | 1 | 线程结束并抛工作异常时仍正确 drain，再传播取消，不误判线程已停止 |
| Session 清理幂等 | 1 | close 两次只删除本 session，保留公共 base |

新增时序测试使用 threading.Event/asyncio.Event 确认开始、取消标志和释放，不靠随机 sleep。sleep(0) 只让调度器交付取消请求，不作为工作完成或目录可删除的依据；测试 finally 释放、等待工作并关闭服务，避免测试自身遗留线程。

另外把上轮仓库外 `test_pr_boundaries.py` 两项失败用例原样重放，**2/2 通过**，不删除或弱化原断言。

## 6. 分组复测结果

解释器：`C:/Users/16173/Documents/ChatGPT/人工智能+/.venv-schema-tests/Scripts/python.exe`。
Python 3.12.14、Pydantic 2.14.2、pytest 9.2.0；FFmpeg/FFprobe 9.0.2。未安装或升级本轮依赖。

| 测试组 | 数量 | 通过 | 失败/error/skip/xfail | 子进程退出码 |
|---|---:|---:|---|---:|
| Schema | 409 | 409 | 0/0/0/0 | 0 |
| 原 FastAPI API | 42 | 42 | 0/0/0/0 | 0 |
| 成员3原完整测试 | 134 | 134 | 0/0/0/0 | 0 |
| 成员3增强检查 | 12 | 12 | 0/0/0/0 | 0 |
| 原集成回归 | 21 | 21 | 0/0/0/0 | 0 |
| 新生命周期回归 | 10 | 10 | 0/0/0/0 | 0 |
| 上轮原失败探针重放 | 2 | 2 | 0/0/0/0 | 0 |
| 真实本机 HTTP 集成 | 12 | 12 | 0（非 pytest） | 全部断言通过 |

各组分别列示；重复复跑的结果不累加，不把作者新增子测试再次算入 134，不把 HTTP 算成 pytest。未修改原测试或公共模型来使其通过。

Schema/API/原集成/新生命周期使用 -W error。主驱动与作者套件保留既有受控执行方式：最小环境、无真实模型凭证、禁止外部 Python 网络及真实模型 SDK、仅许可本地媒体工具和回环。属于进程级控制，不是虚拟机强隔离承诺。

## 7. HTTP、线程与目录结果

- 实际 Uvicorn 在本机端口 53391 完成上传→固定 OCR/VLM→Story→静音 TTS→真实 FFmpeg Video→Jobs done。
- 统一响应/trace、幂等、公共 OCR/VLM/Story 模型、静态产物访问与音视频完整解码通过。
- 整个过程没有调用真实模型或供应商，没有额度消耗；默认 Mock 的 42 项原 API 行为保持通过。
- 正常结束、失败、安全拦截、force 的私有目录清理保持原集成测试通过。恢复备份保留路径仍通过原测试。
- 本轮构造清理故障特意留下的证据在审查临时目录，不能宣称故障注入下所有文件都必然能删除；清理失败会被记录且原异常保持。
- 原重复取消探针已不再观察到线程结束前调用 cleanup；初始化失败探针不再遗留无所有者目录。
- HTTP PID 33756 正常退出码 0，端口关闭；没有对局域网/公网公开服务，测试线程已按事件释放并排空。

## 8. 远程同步

本轮安全 fetch 成功，输出为 GitHub origin/dev 更新查询成功，远程跟踪引用为：

```text
b946bc9e6618231481448692d055c029e073b7ee
```

与隔离分支当前 HEAD 相同。这个结论是本轮 fetch 时点的快照，不保证之后远程不会变化。没有 reset、强制同步、rebase 或合并；当前全部成果仍未提交，未来提交/推送和申请 PR 需队长另行批准。

## 9. 变更保护与证据

仓库本轮仅：

1. 修改 member3_jobs.py。
2. 修改 member3_adapter.py。
3. 新增 test_member3_lifecycle.py。
4. 新增本报告。

相对于本轮开始的文件 SHA 快照，其他已有文件不变。旧 PR 审查报告保留历史，不改写之前失败记录；本报告记录修复后结果。git diff --check 通过。

证据目录 R：

```text
C:/Users/16173/Documents/ChatGPT/人工智能+/module-review-20261109/member3-integration-fix/
```

- `before.json`、`FIX_SUMMARY.json`：范围快照、vendor 校验与分组 XML 统计。
- `run-results.json`、`orchestrator-results.json`、`additional-results.json`、`review-boundaries-command.json`：完整命令、cwd 配置、退出码与耗时。
- `logs/schema.xml`、`api.xml`、`member134.xml`、`additional.xml`、`integration.xml`、`lifecycle.xml`、`review-boundaries.xml`：独立分组结果。
- `http-integration-results.json`、`logs/http_integration_server.log`、`downloads/`：实际 HTTP、服务退出及解码证据。
- `run_baseline.py`、`run_orchestrator.py`、`run_additional.py`、`run_review_probes.py`、`run_http_integration.py`：复现驱动。审核脚本/数据/日志没有加入业务交付清单。

## 10. 未解决问题与下一步

本轮 R01/R02 没有未通过的回归或已知未修复的同类失败。保留此前范围限制：真实模型/外部审核质量、成员2真实 OCR/VLM、多进程写同页、跨文件一致性、强杀恢复等尚未验收；协作取消不等于即时终止不可中断的步骤。

建议负责人核对本轮两个集成文件及新测试，再重新申请 PR 前审查。**不自动提交、推送或创建 PR。**

**A：两个问题均已修复，回归测试通过，可以重新申请 PR 审查。**
