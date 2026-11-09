# GitHub Actions CI 使用说明

本套基础设施独立于成员3业务代码。控制分支从默认分支 main 的
`009d9ed7875ef71b95a6582600ecea89cc98cfa8` 建立；没有携带成员3集成 Commit。

## 触发和测试版本

- PR 目标为 dev / main 时，测试 GitHub 提供的合并预览 SHA。
- push 到 main / dev 时，测试该次 push 的 SHA。
- workflow_dispatch 的 `test_ref` 可选择本仓库的分支、tag 或完整 SHA。
- resolve 作业先解析一次 ref；八组全部使用同一个不可变 SHA。结果会再次核对版本一致。
- 官方 Actions 均固定完整 Commit SHA，权限只有 `contents: read`，不部署、不写 PR、不合并。

**首次启用条件：**workflow_dispatch 要求工作流存在于默认分支。当前文件只在本地
ci/bootstrap-github-actions，尚未提交 / 推送，GitHub 上没有新工作流，也没有本套 CI 结果。
只有队长另行批准基础设施 PR 并使 workflow 可在默认分支发现后，才可以从 Actions 页面
选择工作流版本，再填 `test_ref=integration/member3-v1.1.6` 等测试代码版本。

人工运行的 workflow commit 与被测试 commit 可能不同；以 result.json 的 tested_sha
为准。手动测试某 ref 不保证向现有 PR #7 的 Head 注册 Checks，不能把手动结果冒充
该 PR 的 pull_request 运行。若要自动触发 PR #7，还需另行审批工作流在相应 PR 事件
版本中的可用性和重新触发方式，本轮不改其源分支。

## main 的现有缺口

main 现在只有五份公共 Schema，没有原八组测试、FastAPI Mock 或 vendor。对 main
执行八组时会分别显示 not_executed 并返回非零，而不会生成空绿色报告。对 CI 基础设施
PR 的合并预览同样不能假装已有完整业务测试。先审查基础设施、再决定业务基线推广次序；
不得为使 main 变绿复制未验收业务、自动回退到其他分支，或跳过缺组。

## 八组命令

统一入口（每组独立进程 / 独立输出）：

```text
python tools/ci/run.py --target <代码checkout> --output <报告目录> --group <组名>
python tools/ci/summarize.py --output <报告目录>
```

可先附加 `--preflight`：检查必要文件、记录目标 SHA、AST 解析，不执行测试；状态仍为
not_executed，不能把预检退出 0 当测试通过。

| 组名 | 基线 | 入口 |
|---|---:|---|
| schema | 409 | 目标 orchestrator/tests/test_schema_contract.py、test_schema_round2.py |
| api | 42 | 目标 orchestrator/tests/test_mock_api.py |
| member134 | 134 | 目标 orchestrator/vendor/member3_v116/tests；沿用原 pytest.ini |
| enhanced | 12 | 控制目录 member3/test_independent.py、test_v115_boundary.py、test_v116_boundary.py |
| integration | 21 | 目标 orchestrator/tests/test_member3_integration.py |
| lifecycle | 10 | 目标 orchestrator/tests/test_member3_lifecycle.py |
| replay | 2 | 控制目录 member3/test_pr_boundaries.py |
| http | 12 检查 | 控制目录 http_check.py / http_server.py，真实 loopback Uvicorn |

pytest 在测试 guard 内执行，命令和 cwd 全部写入 result.json。除 vendor 原测试保留自己的
配置外，使用本控制目录 pytest-review.ini（保留 tmpdir，禁用缓存），每组独立 basetemp、
JUnit。Schema / API / 集成 / 生命周期 / 重放沿用 `-W error`。
`xfail_strict=true` 使 XPASS 成为失败；skip 和 XFAIL 同样阻止绿色门禁。数量漂移也失败，
不要删除或弱化测试以凑固定数字；新增有效测试应经审核更新明确的基线。

增强和重放源自此前审查用例；所有原 assert AST 均保留。来源 SHA 和原断言数量保存在
REVIEW_TEST_PROVENANCE.json。增强组先使用被测 vendor 的固定视觉样例、模板 Story、
silent MP3 / WAV 和本地 FFmpeg 生成**本次**媒体，再执行原检查；不借用作者 artifacts。

## 环境与隔离

Ubuntu 是首个 CI 平台，Python 3.12。应用 / 测试依赖安装目标版本的
orchestrator/tests/requirements-api-test.txt，当前集成目标固定 Pydantic 2.14.1。
不安装成员2真实推理包，也不为成员3增加 OpenCV。PyYAML 6.0.3 仅用于控制文件验证。

媒体组安装 Ubuntu ffmpeg（含 ffprobe）、fonts-noto-cjk、fontconfig，预检两工具版本及
可用字体。apt 包版本随 runner 软件源变化，实际版本写进结果；尚未声称此组合已在
GitHub Ubuntu 执行通过。Windows 已本地验证，但未增加 Windows Actions job，避免
未经验证的自动下载 / 字体配置进入矩阵。

本地媒体组需提供：

```text
FFMPEG_PATH=<本机 ffmpeg 绝对路径>
FFPROBE_PATH=<本机 ffprobe 绝对路径>
VIDEO_FONT=<本机有效中文字体绝对路径>
```

测试子进程使用最小环境：GENERATION_BACKEND=mock、TTS_ENGINE=silent，LLM / TTS
服务地址和密钥清空，不读取用户真实 .env，不继承 GitHub Token。外网和真实模型 SDK
导入被 guard 拒绝，仅允许 loopback 和本地媒体进程。该 guard 是防误调用措施，
不是执行任意恶意代码的安全沙箱。依赖 / 工具安装阶段仍需要正常的软件源网络。

vendor 历史基线的 SAFETY_ENABLED=0 保留原测试环境语义；Adapter 自身强制启用安全
检查，负向安全用例显式配置其策略，并未修改或删除安全断言。不把空词表 / MOCK
安全标志解释为真实内容已审核。VIDEO_FONT 用于读取环境配置的 vendor fixture；
Adapter 目前使用其原有默认字体选择，Linux 字幕字形视觉质量另需验收。

每次执行生成独立 attempt 目录；结果顶层只引用本次 attempt，避免读取上次 JUnit。
Linux fd 相对路径和 Windows 长路径均按实际目标路径检查。测试超时返回非零并终止
本次测试进程树；保留目录和日志，不以提前删除目录代替线程生命周期验证。
HTTP wrapper 正常结束时必须服务 exit=0、端口释放，音视频实际 GET、probe、完整解码。

## 结果和工作流门禁

resolve / infrastructure / tests（八组矩阵）/ summary 四类 job；矩阵 fail-fast=false，
每组独立查错，无 continue-on-error。每组最多 12 分钟，内部子进程另有 150 / 240 秒限制。

每组上传 .ci-results，保留 14 天，含 result.json、JUnit、命令、日志、守卫和解码证据。
汇总分别列 passed / failed / skipped / not_executed，不把重叠用例加成唯一总数。
缺文件、安装失败、运行失败、缺报告、数量不符、skip / xfail、版本混用均不能通过。

Actions 管理 API 对当前 WRITE 非管理员账号仍返回 404，不能推断 Actions 关闭。
管理员应人工确认 Settings → Actions → General 的 Actions permissions、Workflow
permissions、官方 Actions 允许范围和是否允许运行。本轮没有变更任何管理设置。

本地校验：

```text
python -m pip install -r tools/ci/requirements-ci.txt
python tools/ci/validate.py
python -m unittest discover -s tools/ci/tests -v
```

validate 使用 YAML 解析并检查触发器、组名、权限、SHA pin、job 依赖、超时、AST 与
差异空白；不是 actionlint 或 GitHub 服务端验证。最终 GitHub Actions 运行仍待队长批准
提交 / 推送和部署后确认。详细本地证据见本次实现报告。
