# GitHub Actions CI 基础设施实现报告

时间：2026-11-09T22:42:56+08:00（Asia/Hong_Kong）。本轮仅在独立 CI 分支建设基础设施；未提交、推送、创建 PR、合并或改动业务分支。

## 1. 结论与边界

**A：CI 文件建设完成，可以申请 CI 基础设施 PR。**

工作流及八组测试入口已完成，本机按现有固定依赖 Pydantic 2.14.1 实际复现八组全部通过，所有组失败 / 跳过 / 未执行均为 0。另有 8 项基础设施自测通过；不与项目八组相加为唯一总数。

**GitHub Ubuntu CI 尚未运行，不能宣称 GitHub CI 已通过。**本机无可用 Linux / Docker 运行环境；尚未验证 apt 媒体工具及 GitHub 服务端工作流执行。当前 main 没有八组业务测试，对 main 的八组门禁会真实失败并列为未执行；这项现有代码分布问题已经明确记录，不以空测试、回退其他分支或 skip 变绿。

本结论仅允许申请基础设施 PR 的审查，不代表批准部署、合并 CI 或 PR #7。本轮已按要求停止 Git 发布。

## 2. 默认分支、远程与工作区

| 项目 | 实际结果 |
|---|---|
| 仓库 / origin | https://github.com/liushizhang32-source/space.git |
| GitHub 默认分支 | main（REST 实时查询） |
| origin/main | 009d9ed7875ef71b95a6582600ecea89cc98cfa8 |
| origin/dev | b946bc9e6618231481448692d055c029e073b7ee |
| 远程成员3分支 | 709155cb4eb146c298434a1c01c11de9c7e3e96d |
| 新工作区 | `C:/Users/16173/Documents/ChatGPT/人工智能+/space-ci-bootstrap` |
| 新分支 | ci/bootstrap-github-actions |
| CI 分支基准 / HEAD / merge-base(main) | 009d9ed7875ef71b95a6582600ecea89cc98cfa8 |
| CI 分支相对 main Commit | 0；本轮禁止 Commit，因此所有新增文件尚未暂存 |
| 远程 CI 分支 | 尚不存在；没有 Push |

先查询默认分支和远程 SHA，再安全 fetch 指定 refs（成功），确认目标分支和目录不存在后创建 worktree：

```text
git worktree add -b ci/bootstrap-github-actions <新独立目录> origin/main
```

没有从成员3分支创建 CI 分支，也没有切换或覆盖任何原工作区。原 space 保持 dev，Jobs / Storage 的既有未提交修改、前端资料和测试报告均原样保留；space-member3-v116-integration 保持原分支及 709155cb、工作区干净。未发现适用 AGENTS.md。最后 ls-remote 核对 main / dev / 成员3远程 SHA 与上表相同。

main 完整树仅有五份 orchestrator/schemas 源文件及 API/README，没有根 .github/workflows、依赖或测试。新 CI 的业务验证另对 709155cb 创建仓库外 detached 副本 `C:/Users/16173/Documents/ChatGPT/人工智能+/ci-bootstrap-20261109/target-member3`，不往 CI 分支复制业务代码，也不让测试改写原成员3工作区或 24 个 vendor 文件。该副本没有创建 Commit。

## 3. 新增文件（20 个）

全部属于根 workflow、CI 控制代码、必要回归入口、说明和本报告。没有修改任何原已跟踪文件。

| 文件 | 用途 |
|---|---|
| `.github/workflows/paperbook-ci.yml` | 工作流 |
| `docs/GITHUB_ACTIONS_CI.md` | CI 辅助 / 文档 |
| `tools/ci/.gitignore` | CI 辅助 / 文档 |
| `tools/ci/REVIEW_TEST_PROVENANCE.json` | CI 辅助 / 文档 |
| `tools/ci/groups.py` | CI 辅助 / 文档 |
| `tools/ci/guard.py` | CI 辅助 / 文档 |
| `tools/ci/http_check.py` | CI 辅助 / 文档 |
| `tools/ci/http_server.py` | CI 辅助 / 文档 |
| `tools/ci/member3/test_independent.py` | CI 辅助 / 文档 |
| `tools/ci/member3/test_pr_boundaries.py` | CI 辅助 / 文档 |
| `tools/ci/member3/test_v115_boundary.py` | CI 辅助 / 文档 |
| `tools/ci/member3/test_v116_boundary.py` | CI 辅助 / 文档 |
| `tools/ci/prepare_fixtures.py` | CI 辅助 / 文档 |
| `tools/ci/pytest-review.ini` | CI 辅助 / 文档 |
| `tools/ci/requirements-ci.txt` | CI 辅助 / 文档 |
| `tools/ci/run.py` | CI 辅助 / 文档 |
| `tools/ci/summarize.py` | CI 辅助 / 文档 |
| `tools/ci/tests/test_gate.py` | CI 辅助 / 文档 |
| `tools/ci/validate.py` | CI 辅助 / 文档 |
| `reports/GITHUB_ACTIONS_CI_IMPLEMENTATION_REPORT.md` | 本次实现报告 |

工作流唯一文件为 `.github/workflows/paperbook-ci.yml`。核心业务、公共 Schema、API_v1.0.md、成员2模块、成员3原交付和 24 个 vendor 文件均无修改。运行结果、XML、日志、媒体、PyYAML 工具依赖及 detached 测试副本均在仓库外，不作为待提交文件。

## 4. 工作流与安全机制

- 触发：pull_request 目标 main / dev；push main / dev；workflow_dispatch 必填 test_ref（默认 dev）。没有 pull_request_target。
- resolve：checkout 所选版本后只解析一次不可变 SHA，八组共用；避免分支在矩阵启动期间前进造成混合版本。
- infrastructure：真正解析 YAML，核对触发、权限、Job 依赖、8 组、超时及 Actions 完整 SHA，检查 CI Python AST / 空白 / git diff，并运行 8 项门禁自测。
- tests：Ubuntu 八组矩阵，fail-fast=false，分别预检文件、安装目标已声明依赖、pip check、必要媒体工具、执行及保存证据；没有 continue-on-error。
- summary：always 执行，检查上游 resolve / infrastructure / tests 均 success，要求同一 tested_sha、八组齐全、数量符合基线、失败 / skipped / 未执行为 0。即使测试全绿，基础设施 Job 失败也不放行。
- 最小权限 contents: read；checkout persist-credentials=false。没有 secrets 引用、部署步骤、PR 写入或合并动作。
- 三个普通 Job 超时 5 分钟，测试矩阵每组 12 分钟；子测试通常 240 秒、HTTP 150 秒，HTTP 内又有启动 / 任务 / 解码 / 关闭超时。
- 每次运行创建独立 attempt，顶层 result 仅指向本次目录，不读取历史 JUnit。超时终止本次测试进程树并保留日志，不提前删工作目录以掩盖后台线程问题。
- pytest 原失败不会被删除 / skip / xfail。额外 xfail_strict=true，XPASS 也是失败，任何 skip / XFAIL 也阻止门禁成功。
- 原 vendor pytest.ini 保留；其余用独立 CI 配置保持 tmpdir，避免旧根配置禁用该插件。原 Schema/API/集成/生命周期/重放继续 -W error。
- 结果分别上传 14 天，含命令、cwd、实际版本、SHA、JUnit、HTTP / 解码和 guard 日志。汇总不把重放 / 重叠检查加成唯一总数。

官方 Actions 已通过只读 GitHub tag API 核实，锁定实际 commit（不是声明最新 major）：

| 官方组件 | 已核实系列 | Commit |
|---|---|---|
| actions/checkout | v4 | 11d5960a326750d5838078e36cf38b85af677262 |
| actions/setup-python | v5 | a26af69be951a213d495a4c3e4e4022e16d87065 |
| actions/upload-artifact | v4 | ea165f8d65b6e75b540449e92b4886f43607fa02 |
| actions/download-artifact | v4 | d3f86a106a0bac45b974a628896c90dbdf5c8093 |

## 5. workflow_dispatch 和首次上线限制

必须先经批准让 workflow 可在**默认分支 main**发现，再使用 Actions → Paperbook CI → Run workflow；UI 的工作流 ref 与输入 test_ref 是不同概念。本轮没有上传文件，GitHub 目前仍无本套可手动触发的新 workflow。

首次完整联调时可选择 test_ref=`integration/member3-v1.1.6`（本轮实际对应 709155cb），或输入完整 SHA。手动输入其他没有资源的分支应真实失败。manual run 的 Actions head 可能是控制工作流 commit，不一定是被测 709155cb；结果明确保存 tested_sha，不能据此谎称 PR #7 Head 自动出现 CI Checks。要对 PR #7 自动触发，需另行审批其事件版本中 workflow 的可用性及重触发方案；本轮不改其源分支。

当前 main 连 Schema 测试文件都未包含；CI 基础设施 PR 合并预览不会凭空获得业务测试，八组会报告缺失。需要队长安排基础设施与业务版本的推广次序。不得将该次八组缺失当作 CI 实现成功绿色，也不得删除门禁绕过它。dev 已有部分基础测试，但未纳入成员3完整资源时，同样不能称八组全部可执行。

## 6. 测试对应关系与移植

| 组 | 基线 | 实际入口 |
|---|---:|---|
| schema | 409 | target/orchestrator/tests/test_schema_contract.py + test_schema_round2.py |
| api | 42 | target/orchestrator/tests/test_mock_api.py，默认 mock |
| member134 | 134 | target/orchestrator/vendor/member3_v116/tests；独立进程与 cwd |
| enhanced | 12 | tools/ci/member3/test_independent.py、test_v115_boundary.py、test_v116_boundary.py |
| integration | 21 | target/orchestrator/tests/test_member3_integration.py |
| lifecycle | 10 | target/orchestrator/tests/test_member3_lifecycle.py |
| replay | 2 | tools/ci/member3/test_pr_boundaries.py |
| http | 12 检查 | tools/ci/http_check.py + http_server.py，真实 loopback Uvicorn |

此前三组仓库外检查已完成可移植迁移，改变的仅是资源路径、配置入口和可信守卫启动方式，**73 个原 assert AST 全部一致**：增强 18+13+8，重放 5，HTTP 29。来源 SHA 与数量保存在 REVIEW_TEST_PROVENANCE.json，审查驱动原文件未改。

增强检查不读作者预生成 artifacts：在独立目录复制公共视觉 fixture、调用目标原有 template / silent API，生成本轮 Story、MP3、WAV、Video，再验证原断言。HTTP 12 项含 Capture、Generate、幂等、queued→running→done、五阶段、公共 Schema、媒体 GET / probe / 完整解码、错误响应、清理和 trace_id；未新增任何业务接口。

## 7. Python、依赖及平台

| 项目 | 配置 / 实际结果 |
|---|---|
| CI | Ubuntu runner，Python 3.12；真实 GitHub 运行待验证 |
| 业务依赖 | 安装所选 target 的 orchestrator/tests/requirements-api-test.txt，不在控制分支复制或重写业务依赖 |
| 固定核心版本 | Pydantic 2.14.1、pytest 9.2.0、FastAPI 0.162.0、Starlette 0.50.0、anyio 4.11.0、Uvicorn 0.54.0、httpx 0.28.1、python-multipart 0.0.33、Pillow 13.0.0 |
| YAML 工具 | 独立 tools/ci/requirements-ci.txt 固定 PyYAML 6.0.3，不升级业务环境 |
| 本机最终复现 | Python 3.12.14，现有 pinned-env，Pydantic 2.14.1；pip check 退出 0 |
| OpenCV | 本套成员3八组无 cv2 需要，不加入；成员2真实视觉 / GPU 包不在此轮范围 |
| 本机媒体 | FFmpeg / FFprobe 9.0.2 essentials；中文字体 msyh.ttc；工具和字体未复制入仓库 |
| Ubuntu 媒体 | apt ffmpeg、fonts-noto-cjk、fontconfig；FFMPEG_PATH / FFPROBE_PATH / VIDEO_FONT 由 runner 自动发现，实际版本写结果，待远程验证 |
| Windows Job | 暂不加入；本机 Windows 已跑通不等于 GitHub Windows 自动安装已验收 |

本机 WSL 只返回安装 / 帮助信息，没有可用 Linux 发行版；未找到 Docker。本轮没有擅自安装 WSL 或启动额外虚拟机。因此不能声明 Linux 原八组已经通过。Ubuntu apt 版本与字体 / FFmpeg 编码差异须首跑观察；不通过时定位 CI 或真实平台问题，不改 vendor 断言蒙混过关。

控制程序处理 Linux dir_fd 相对路径和 Windows长路径，并使用 pathlib / os.pathsep。该 Linux 路径逻辑已静态审查，但尚无 Linux 运行证明。VIDEO_FONT 对环境配置读取的 vendor fixture 生效；Adapter 本身保留既有字体选择，Linux 中文字幕字形视觉质量不在“媒体可解码”断言的证明范围。

## 8. Mock 环境和资源控制

测试子进程使用最小环境，不继承 Token 或模型配置；GENERATION_BACKEND=mock、TTS_ENGINE=silent，LLM / TTS URL、key 置空。只允许 loopback 与白名单媒体进程，禁止外网 DNS / HTTP 和模型 SDK 导入。真实 .env 不可读，写入仅限本组 attempt 与 detached 目标 vendor 的测试临时目录。guard 是防误调用措施，不是执行任意敌对代码的 OS 沙箱。

vendor 历史基线 SAFETY_ENABLED=0 原样保留；成员3 Adapter 自身强制启用安全检查，原安全负例仍执行，不是为 CI 删除安全拦截。上游 safety=true 的固定输入明确为 MOCK fixture，不宣称是真实内容审核。测试全过程未使用真实模型或额度。

不同组独立进程 / 临时目录，不共享生成缓存。媒体组缺少工具 / 字体直接失败，不允许原测试 skip 后假绿。HTTP 正常退出后必须端口释放；超时不会清理仍可能使用的工作目录，保留异常证据。

## 9. 本地最终验证

### 9.1 固定依赖环境、准确目标 SHA

本机解释器：`C:/Users/16173/Documents/ChatGPT/人工智能+/module-review-20261109/member3-pr-review/pinned-env/Scripts/python.exe`。测试副本为 709155cb，与原源分支相同；预检 AST 解析目标 orchestrator 下 **69 个 Python 文件**。所有组运行后目标 tracked diff 为空；原成员3工作区也无变化。

| 组 | 基线 | 实际通过 | 失败 | 跳过 | 未执行 | 退出码 | 耗时秒 |
|---|---:|---:|---:|---:|---:|---:|---:|
| schema | 409 | 409 | 0 | 0 | 0 | 0 | 2.063 |
| api | 42 | 42 | 0 | 0 | 0 | 0 | 4.609 |
| member134 | 134 | 134 | 0 | 0 | 0 | 0 | 32.421 |
| enhanced | 12 | 12 | 0 | 0 | 0 | 0 | 5.281 |
| integration | 21 | 21 | 0 | 0 | 0 | 0 | 19.797 |
| lifecycle | 10 | 10 | 0 | 0 | 0 | 0 | 2.079 |
| replay | 2 | 2 | 0 | 0 | 0 | 0 | 2.344 |
| http | 12 | 12 | 0 | 0 | 0 | 0 | 9.031 |

表中是本轮最终实际结果，不是把历史报告照抄为结果。每组分别统计，不相加作为唯一总数；HTTP 12 是检查项，不冒充 12 个 pytest node。

### 9.2 基础设施及负向门禁

- PyYAML 实际解析、触发 / 权限 / SHA pin / Job 依赖 / CI AST / 差异空白检查退出 0（yaml-validation.log）。不是 actionlint 或 GitHub 服务端已通过。
- 门禁 unittest：**8/8**，退出 0，包含空 / 缺组、失败 / skip、JUnit errors、数量漂移、混用 SHA、上游失败但测试绿的阻断。
- 八组汇总：退出 0，所有组 tested_sha 一致为 709155cb。
- main 原代码预检：八组分别退出 1，通过 0、失败测试 0、skip 0，not_executed 各为本组基线；原因是必要文件不存在。验证不会空绿。
- 首次试跑暴露了本轮 guard 对 Windows subprocess executable=None、runpy 空 argv、长路径的适配问题，已仅在 CI 辅助层修复；早期失败证据保留在 initial-failures 及 results，不计入最终通过结果。未为通过修改业务、vendor 或原断言。
- 新增文件没有缓存 / 虚拟环境 / 临时 XML；试跑产生的 CI 自有 __pycache__ 已清理并局部忽略，未清理任何用户目录。

### 9.3 HTTP 与媒体

最终 HTTP 检查 12/12；server_exit=0，port_closed=true。所有音频与视频真实 HTTP GET 后 ffprobe 及 FFmpeg `-v error -xerror -i <file> -f null -` 均退出 0。MP4 实际为 H.264 720×1280、25fps + AAC，约 4.663 秒；不是伪造可播放 URL。均为模板 / 静音链路。

证据：`C:/Users/16173/Documents/ChatGPT/人工智能+/ci-bootstrap-20261109/results-pinned/summary.md` 与各组 result.json，HTTP attempt 下 http-integration-results.json、下载媒体、server log、guard log。全部位于仓库外，HTTP 服务已关闭。

## 10. 每组实际执行命令

工作流使用 setup-python 的 python；以下是本机实际固定解释器、路径和内部命令。每组 run.py 会构造最小环境，命令不能脱离其 guard / 资源配置单独理解为完整隔离。完整 cwd、timeout、versions 和 tested_sha 同样保留在 result.json。


### schema

实际本地入口（Windows，固定依赖解释器）：

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe -B C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\run.py --target C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\target-member3 --output C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned --group schema
```

内部实际执行命令（与 result.json 对应）：

工作目录：`C:/Users/16173/Documents/ChatGPT/人工智能+/ci-bootstrap-20261109/target-member3`，超时 240 秒。

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\guard.py pytest C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\target-member3\orchestrator\tests\test_schema_contract.py C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\target-member3\orchestrator\tests\test_schema_round2.py -c C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\pytest-review.ini --basetemp C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\schema\attempt-a73875f16c0c\tmp\pytest -W error -q -ra --tb=short -o xfail_strict=true -o log_file=C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\schema\attempt-a73875f16c0c\logs\pytest.log --junitxml C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\schema\attempt-a73875f16c0c\junit.xml
```

### api

实际本地入口（Windows，固定依赖解释器）：

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe -B C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\run.py --target C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\target-member3 --output C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned --group api
```

内部实际执行命令（与 result.json 对应）：

工作目录：`C:/Users/16173/Documents/ChatGPT/人工智能+/ci-bootstrap-20261109/target-member3`，超时 240 秒。

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\guard.py pytest C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\target-member3\orchestrator\tests\test_mock_api.py -c C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\pytest-review.ini --basetemp C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\api\attempt-4e9767f0cfce\tmp\pytest -W error -q -ra --tb=short -o xfail_strict=true -o log_file=C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\api\attempt-4e9767f0cfce\logs\pytest.log --junitxml C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\api\attempt-4e9767f0cfce\junit.xml
```

### member134

实际本地入口（Windows，固定依赖解释器）：

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe -B C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\run.py --target C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\target-member3 --output C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned --group member134
```

内部实际执行命令（与 result.json 对应）：

工作目录：`C:/Users/16173/Documents/ChatGPT/人工智能+/ci-bootstrap-20261109/target-member3/orchestrator/vendor/member3_v116`，超时 240 秒。

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\guard.py pytest tests -q -ra --tb=short -o xfail_strict=true -o log_file=C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\member134\attempt-9d320c638b57\logs\pytest.log --junitxml C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\member134\attempt-9d320c638b57\junit.xml
```

### enhanced

实际本地入口（Windows，固定依赖解释器）：

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe -B C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\run.py --target C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\target-member3 --output C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned --group enhanced
```

内部实际执行命令（与 result.json 对应）：

工作目录：`C:/Users/16173/Documents/ChatGPT/人工智能+/ci-bootstrap-20261109/target-member3/orchestrator/vendor/member3_v116`，超时 240 秒。

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\guard.py prepare
```

工作目录：`C:/Users/16173/Documents/ChatGPT/人工智能+/ci-bootstrap-20261109/target-member3`，超时 240 秒。

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\guard.py pytest C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\member3\test_independent.py C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\member3\test_v115_boundary.py C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\member3\test_v116_boundary.py -c C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\pytest-review.ini --basetemp C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\enhanced\attempt-cc4b62340606\tmp\pytest -q -ra --tb=short -o xfail_strict=true -o log_file=C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\enhanced\attempt-cc4b62340606\logs\pytest.log --junitxml C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\enhanced\attempt-cc4b62340606\junit.xml
```

### integration

实际本地入口（Windows，固定依赖解释器）：

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe -B C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\run.py --target C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\target-member3 --output C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned --group integration
```

内部实际执行命令（与 result.json 对应）：

工作目录：`C:/Users/16173/Documents/ChatGPT/人工智能+/ci-bootstrap-20261109/target-member3`，超时 240 秒。

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\guard.py pytest C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\target-member3\orchestrator\tests\test_member3_integration.py -c C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\pytest-review.ini --basetemp C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\integration\attempt-c2186d34ad76\tmp\pytest -W error -q -ra --tb=short -o xfail_strict=true -o log_file=C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\integration\attempt-c2186d34ad76\logs\pytest.log --junitxml C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\integration\attempt-c2186d34ad76\junit.xml
```

### lifecycle

实际本地入口（Windows，固定依赖解释器）：

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe -B C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\run.py --target C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\target-member3 --output C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned --group lifecycle
```

内部实际执行命令（与 result.json 对应）：

工作目录：`C:/Users/16173/Documents/ChatGPT/人工智能+/ci-bootstrap-20261109/target-member3`，超时 240 秒。

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\guard.py pytest C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\target-member3\orchestrator\tests\test_member3_lifecycle.py -c C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\pytest-review.ini --basetemp C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\lifecycle\attempt-eed1acb7b913\tmp\pytest -W error -q -ra --tb=short -o xfail_strict=true -o log_file=C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\lifecycle\attempt-eed1acb7b913\logs\pytest.log --junitxml C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\lifecycle\attempt-eed1acb7b913\junit.xml
```

### replay

实际本地入口（Windows，固定依赖解释器）：

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe -B C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\run.py --target C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\target-member3 --output C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned --group replay
```

内部实际执行命令（与 result.json 对应）：

工作目录：`C:/Users/16173/Documents/ChatGPT/人工智能+/ci-bootstrap-20261109/target-member3`，超时 240 秒。

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\guard.py pytest C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\member3\test_pr_boundaries.py -c C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\pytest-review.ini --basetemp C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\replay\attempt-19021b9b7aee\tmp\pytest -W error -q -ra --tb=short -o xfail_strict=true -o log_file=C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\replay\attempt-19021b9b7aee\logs\pytest.log --junitxml C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned\replay\attempt-19021b9b7aee\junit.xml
```

### http

实际本地入口（Windows，固定依赖解释器）：

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe -B C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\run.py --target C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\target-member3 --output C:\Users\16173\Documents\ChatGPT\人工智能+\ci-bootstrap-20261109\results-pinned --group http
```

内部实际执行命令（与 result.json 对应）：

工作目录：`C:/Users/16173/Documents/ChatGPT/人工智能+/ci-bootstrap-20261109/target-member3`，超时 150 秒。

```text
C:\Users\16173\Documents\ChatGPT\人工智能+\module-review-20261109\member3-pr-review\pinned-env\Scripts\python.exe C:\Users\16173\Documents\ChatGPT\人工智能+\space-ci-bootstrap\tools\ci\guard.py http
```


## 11. Actions 权限与尚未解决事项

两个管理 API /actions/permissions、/actions/permissions/workflow 再次均返回 **HTTP 404**。当前账号为 WRITE、admin=false、maintain=false；没有越权尝试，也不推断 Actions 被关闭。

需要仓库管理员人工打开 **GitHub → Settings → Actions → General**，确认：Actions permissions、Workflow permissions、必要官方 Actions 是否允许、是否允许工作流运行。本轮没有更改管理设置或索要 Token。

待远程验证：GitHub YAML / runner 服务端行为、Ubuntu apt 媒体依赖、原有测试 Linux 兼容性、Artifacts 下载 / 汇总、workflow_dispatch 默认分支发现及指定 ref 测试。当前不添加未经验证的 Windows job，不宣称全平台通过。真实模型质量、Linux 字幕视觉效果、部署与服务公开不在本轮范围。

main / dev 的业务版本推广与 PR #7 Checks 关联问题必须由队长安排；不能在本轮直接修改它们，或为了 bootstrap 成功降低八组门禁。

## 12. 下一步部署建议

1. 队长审查这 20 个纯基础设施文件与本地结果；当前没有 Commit / Push / PR。
2. 管理员确认 Actions 设置。另行授权后才提交 / 推送 CI 分支并申请基础设施 PR（建议目标 main，使默认分支可发现工作流）；这不等于自动批准合并。
3. 明确 bootstrap 阶段 main 缺业务测试时的推广顺序和预期失败，不以跳过 / 假绿绕过。基础设施审查完成并获准使其进入默认分支后，先手动固定 test_ref=709155cb 试跑 Ubuntu 八组。
4. 验证每组真实云端数量、0 skip、解码、服务关闭及 artifacts，再考虑 required checks。新 CI commit / PR merge SHA 需重新核对，不沿用本地通过作云端结论。
5. 对 PR #7 所需的自动事件 workflow 可用性另立授权；不得擅自把 CI 加到其源分支或创建 Commit。本轮不合并成员3 PR。

**最终结论 A：文件建设完成，可以申请 CI 基础设施 PR；云端运行和推广尚待验证与队长授权。**
