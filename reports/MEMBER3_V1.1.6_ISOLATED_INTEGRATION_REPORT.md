# 成员3 v1.1.6 Orchestrator 隔离集成报告

日期：2026-11-08。

## 1. 最终结论

**A：隔离集成全部通过，可以申请队长批准 PR。**

在本轮已验证环境中，Capture → 固定 OCR/VLM → 成员3 Story → 静音 TTS → 实际视频合成 → Jobs 终态 → 同一 Orchestrator 静态 URL 下载闭环通过。安全拒绝、异常映射、降级、force 取消和无效产物拒绝发布有新增回归覆盖。

本轮没有真实 LLM、真实语音供应商或成员2实际 OCR/VLM 调用，没有模型额度消耗。A 不表示真实模型能力已验收，不表示已批准合并或部署。未 Commit、Push、合并或创建 PR，等待队长验收。

## 2. 分支、远程与现场保护

原工作区：`C:/Users/16173/Documents/ChatGPT/人工智能+/space`，保留在 dev，HEAD 仍为 `f7bded63d3227adee61e8da407307dd15997136b`。其中已有 Jobs/Storage 修改、成员2测试及未跟踪报告均保留，没有覆盖、清理、暂存或移入本分支。

origin 已核对为 `https://github.com/liushizhang32-source/space.git`。使用 HTTP/1.1 从 GitHub 建立独立克隆，获取当时最新 origin/dev：

```text
b946bc9e6618231481448692d055c029e073b7ee
Merge pull request #1 from liushizhang32-source/feat/generation
```

上述合并已存在于远程基准，不是本轮执行的合并。基准中包含旧成员3模块；本轮未覆盖它，也没有把它当 v1.1.6 使用。

集成目录：`C:/Users/16173/Documents/ChatGPT/人工智能+/space-member3-v116-integration`。

实际工作分支：`integration/member3-v1.1.6`，从 origin/dev 新建，未跟踪为 dev；当前 HEAD 仍是上述基准，无新增提交。集成源代码、测试、说明及本报告全部只在这个独立目录/分支修改。原 dev 和 main 未修改，也未更改全局 Git 配置。Git 的 ownership 提示通过每条命令的 safe.directory 参数解决。

未发现适用的 AGENTS.md。最终 `git diff --check` 通过；API 文档、公共 Schema、三个 API 的 routes/models、原 Jobs 和原 Storage 对 origin/dev 差异为空。

## 3. 使用的 v1.1.6 代码与溯源

- 原交付 ZIP：`C:/Users/16173/xwechat_files/wxid_jna1bafh925d32_40fd/msg/file/2026-11/paperbook-member3-generation-wzy622-patch-1-v1.1.6(1).zip`。
- SHA-256：`d2e9b02963ded6df40e6e09e7dd0819d4bdf0b65bf197c28ec16ece569ac7fb6`。
- 对照原工作区 `reports/MEMBER3_V1.1.6_ISOLATED_TEST_REPORT.md` 的版本、91 文件清单、134/12/12 测试结果与本机源代码，匹配。
- 将完整 91 文件原样保留在 `orchestrator/vendor/member3_v116/`，包括 45 个 Python 文件、作者测试、文档和必要样本。没有修改成员3源码或作者测试。
- `orchestrator/vendor/MEMBER3_V116_PROVENANCE.json` 保存版本、ZIP SHA 和逐文件 SHA；最终再次校验，91 文件与交付版本全部一致。
- Adapter 只导入 `orchestrator.vendor.member3_v116.agents.generation` 的独立命名空间，避免加载根目录已有旧 `agents`。
- 依赖复用现有环境，无安装、升级或新增第三方库。没有读取真实 `.env`、使用模型密钥或执行附件中的安装/verify shell 脚本。

## 4. 集成文件清单

| 类型 | 文件 | 用途 |
|---|---|---|
| 修改 | `orchestrator/core/config.py` | 后端选择、FFmpeg/FFprobe 路径、本地审核词表；默认仍为 mock |
| 修改 | `orchestrator/main.py` | 仅按后端选择 Jobs 实现，复用现有 routes、响应和静态挂载 |
| 新增 | `orchestrator/services/member3_adapter.py` | 固定视觉输入、成员3阶段适配、公共模型与媒体检查、私有生成和发布 |
| 新增 | `orchestrator/services/member3_jobs.py` | 异步阶段状态、线程调度、取消收尾、错误/降级与任务聚合 |
| 新增 | `orchestrator/tests/test_member3_integration.py` | 21 项集成回归 |
| 新增 | `orchestrator/tests/pytest.ini` | 隔离根旧模块配置对 tmpdir 插件的影响，不改原测试 |
| 新增 | `orchestrator/vendor/member3_v116/` | 原交付完整 91 文件副本 |
| 新增 | `orchestrator/vendor/MEMBER3_V116_PROVENANCE.json` | 独立可核对的来源记录 |
| 新增 | `docs/MEMBER3_V116_INTEGRATION.md` | Windows 启动、切换、回归命令和部署前提 |
| 新增 | 本报告 | 实际结果和限制 |

合计修改 2 个已有文件、新增 98 个文件（其中 91 个是完整原包）。没有将 XML、运行数据、媒体测试结果、便携工具、虚拟环境或缓存加入交付清单。运行证据放在第 11 节所列仓库外目录。

## 5. Adapter 设计及模块接入

### 5.1 后端与固定视觉输入

`GENERATION_BACKEND=mock` 为默认值，继续使用原 Jobs/Storage 和原 Mock 素材；原 API 回归验证行为未变。

`GENERATION_BACKEND=member3` 选择新 Member3Jobs + Adapter。成员3配置通过显式构造创建，固定模板 Story、silent TTS、空 LLM/供应商配置，不从 `.env` 或模型凭证环境变量创建真实服务。

OCR/VLM 是固定 MOCK 内容，随当前 Capture 派生 book/page/object ID、图片尺寸及整图 bbox；进入下游前分别用当前公共 OCRData/VLMData 校验。上游 safety.pass=false 无条件拒绝。没有调用成员2真实模块。

### 5.2 Story 与独立 TTS 阶段

成员3 builder 本身会同步调用 TTS。为了保留 Jobs 的 story/tts 分阶段显示，Adapter 在 Story 阶段传入 DeferredTTS，仅提供估算时长，不生成音频。原 builder 仍负责草稿、scene 兜底、ID、高亮清理与生成前后安全检查。

延迟动作产生的 no_audio 不当作实际故障；实际 TTS 阶段调用原 TTSClient，测量并解码每段音频，更新 duration_source、audio_url、时长及 total_duration。普通 TTS 错误保留估算时长并降级 no_audio；3004 安全错误立即停止，不降级成成功。

Story 在阶段检查及发布前使用当前公共 StoryData 校验；安全标志和文本审核再次检查。文件没有新增公共必填字段。模型、scene、highlight_object_ids 的当前页归属均按已有规则验证。

### 5.3 Video 与有效产物门槛

调用原 compose_video，保留其安全、资源检查和发布/回滚逻辑。之后额外深度解码并核对视频尺寸、fps、音轨和时长；没有把“文件存在”当有效产物。

音视频通过验证时记录 SHA。公开发布前再次确认媒体仍存在且 SHA 未变；临时发布副本也与该 SHA 对照，随后逐文件 os.replace。丢失、损坏或变更的媒体不返回成功 URL。

VideoPublishError 保持不可重试，恢复记录进入内部 logs，保留包含备份的私有工作目录，供人工恢复。私有目录和 logs 没有静态挂载，恢复细节不加入公共 Jobs 响应。

### 5.4 调度、取消与公开边界

每个任务页使用唯一 `DATA_DIR/.member3/` 工作目录；原图在 Storage 锁内按 Capture 元数据复制。工作线程不写公开目录。

耗时生成/媒体解码通过 asyncio.to_thread 执行，轮询和 force 不被同步 FFmpeg 阻塞。线程不能直接取消：旧任务取消后等待线程完成，清理其私有数据，再退出；新任务用独立目录运行。发布前无 await 的取消检查及短本地发布步骤阻止旧任务在 force 后发布。

公开 URL 只在本任务完成发布后赋值。普通成功/失败清理私有目录；恢复失败保留备份；清理 I/O 异常记内部日志。发布是逐文件原子替换，不宣称跨文件事务或多进程原子快照。

## 6. Orchestrator 状态和错误结果

- 固定视觉正常及三个成员3阶段正常：页面 done，任务 done，progress=100。
- 普通 TTS 失败：TTS stage=failed，no_audio，使用估算时长继续生成静音视频；页面 partial，任务 partial_failed，错误码保留。
- 普通 Render 失败：Render stage=failed，no_video，返回合法 Story/音频，video_url=null；页面 partial，任务 partial_failed。
- 安全拒绝：页面 blocked，任务 failed（或批量中的 partial_failed），清空该页公开 URL，后续未开始阶段 skipped，不发布本任务产物。
- Story 不可生成、非法输入或不可发布产物：明确 failed，错误映射至公共码，URL 不误报成功。
- 批量中一页失败不会阻止后续页；仍按 page_no 排序，聚合状态和进度正确。
- queued/running 幂等和 force 行为复用既有 create/get 接口，没有新增请求字段。成员3本地 video_error/recovery_id 不原样塞入冻结 /jobs 数据结构。

## 7. 分组回归与新增测试

解释器：`C:/Users/16173/Documents/ChatGPT/人工智能+/.venv-schema-tests/Scripts/python.exe`。

实际 Python 3.12.14；Pydantic 2.14.2；pytest 9.2.0；FastAPI 0.162.0；Starlette 0.50.0；Uvicorn 0.54.0；Pillow 13.0.0；本地 FFmpeg/FFprobe 9.0.2。

| 测试组 | 实际数量 | 通过 | 失败 / error | skip / xfail | 子进程退出码 | pytest 自身耗时 |
|---|---:|---:|---:|---:|---:|---:|
| 公共 Schema 原回归 | 409 | 409 | 0 / 0 | 0 / 0 | 0 | 0.637 秒 |
| 原 FastAPI Mock API | 42 | 42 | 0 / 0 | 0 / 0 | 0 | 3.808 秒 |
| 成员3原完整套件 | 134 | 134 | 0 / 0 | 0 / 0 | 0 | 27.065 秒 |
| 成员3审核方增强 | 12 | 12 | 0 / 0 | 0 / 0 | 0 | 1.034 秒 |
| 本轮新集成回归 | 21 | 21 | 0 / 0 | 0 / 0 | 0 | 15.115 秒 |

上述组各自统计一次；作者 v1.1.5/v1.1.6 新增回归已包含在 134 内，不再另外加数。真实 HTTP 检查独立列于下一节。重复执行、初始化失败和 CLI 运行不增加测试总数。

集成回归实际覆盖：完整新产物、公共响应/trace、幂等、视觉安全/bbox/跨页 ID/无内容拒绝、无字页降级、HTTP TTS 超时与 HTML、下游 TTS/Video 安全拒绝、缺原图、渲染失败、损坏视频、恢复备份保留、force 线程取消、批量局部失败、非法后端、词表拦截、损坏音频、发布前音频丢失、最终发布安全错误。

测试入口均在受控子进程执行，禁用外部模型 SDK、外部 Python 网络和非媒体白名单程序；不继承真实凭证。文件写入限证据目录，另只放行作者原测试夹具所需的 vendor/_test_tmp，运行后清理，源码哈希不变。这是进程级控制，不是虚拟机或操作系统级强隔离认证。

主要命令由证据目录下驱动运行：

```powershell
$py = 'C:\Users\16173\Documents\ChatGPT\人工智能+\.venv-schema-tests\Scripts\python.exe'
& $py .\run_baseline.py
& $py .\run_additional.py
& $py .\run_orchestrator.py
& $py .\run_http_integration.py
```

完整绝对 argv、退出码、耗时及测试 XML 留存。Schema/API/新集成使用 `-W error`；作者 134 保留其自有 pytest 配置，没有删除、修改、skip、xfail 或放宽原测试。

初次配置时，审核 guard 未放行作者自带 _test_tmp，以及 pytest 默认日志目标不在证据目录，造成夹具/启动权限错误。仅校正审核驱动与许可的测试临时路径后重新运行，最终全部通过；初始化记录保留在 `logs/setup-attempt/`、`run-results-setup-attempt.json`、`orchestrator-results-setup-attempt.json`，不混算为业务测试结果。没有为通过测试修改作者源码或旧断言。

## 8. 真实本机 HTTP 集成：12/12

使用真正的 Orchestrator Uvicorn、member3 后端和新 DATA_DIR，监听 `127.0.0.1:61258`，不是 TestClient，也不依赖额外 Story/Video 资源网关。

| HTTP 检查 | 实际结果 |
|---|---|
| OpenAPI | 三个既有接口路径保持 |
| Capture | book01_p03，合法 PNG 上传成功，返回实际图片尺寸和 preview_url |
| Preview | 同一应用静态地址 200，image/jpeg |
| Generate | queued，合法 job_ ULID，poll_after_ms=2000 |
| 活动请求重复 | 复用同一 job_id |
| Jobs 每 2 秒轮询 | queued → running → done，进度 0 → 80 → 100 |
| OCR/VLM 文件 | 同一应用静态读取成功，通过公共 Schema，为固定 MOCK |
| Story 文件 | 同一应用静态读取成功，通过公共 StoryData |
| 音频下载/解码 | 所有段音频 HTTP 200，FFmpeg 完整解码成功 |
| 视频下载/解码 | HTTP 200，SHA 与实际输出一致，完整解码/容器/音视频流检查成功 |
| 不存在 job | HTTP 200、code=1003，统一 envelope 和 trace |
| 临时目录收尾 | 正常任务工作目录清理完成 |

任务实际 job_id：`job_01M6XVCGAQ4VCK8NPMVWSB1Q1D`。最后状态无 error/degraded，页面 done，各阶段均 ok，耗时依次为 OCR 306、VLM 292、Story 321、TTS 638、Render 1593 ms。

轮询间隔为 2 秒，因此没有观察到每个阶段的每次 running 切换；上述逐阶段结果来自最终 Jobs 状态，未编造中间快照。统一 code/msg/data/trace_id 及 X-Trace-ID 对应格式全部校验。

本轮 HTTP 驱动耗时 6.638 秒（含启动、请求和收尾）。临时 Uvicorn PID 29280 正常退出码 0，端口再次检查已关闭。没有对局域网或公网公开服务。

## 9. 音视频实际结果

- Story：模板模型 mock-template，scene 非空，高亮当前页合法；duration_source=tts，生成段数 1。
- 音频：真实新生成静音 MP3，28,460 字节，24000Hz，探测时长 4.636 秒，解码退出 0。
- 视频：真实新合成 MP4，28,106 字节，720×1280、25fps、H.264 + AAC 音轨，探测时长 4.663203 秒，解码退出 0。
- 视频 SHA-256：`2995fffd961ac077bf5d082a0c0104d6ef62165a136b4d09e33882b38180b35b`，HTTP 下载与输出文件一致。
- 该音轨为静音 MOCK，不能当作真实朗读质量验证；视频也不是生成式视觉模型产物。

## 10. 发现并处理的问题、保留限制

### 本轮已处理

1. **旧模块命名冲突**：远程 dev 已有旧 agents，采用独立 vendor 命名空间，保留旧文件。
2. **同步生成阻塞/取消后线程继续运行**：增加线程工作单元、私有工作目录、取消 drain 和受控发布。force 并发回归通过。
3. **发布前媒体丢失**：增加验证时 SHA、发布前与副本完整性检查；音频丢失返回 3008，页面 failed，不发布悬空 URL。
4. **最终安全异常的错误映射**：无论阶段包装后的 APIError 或成员3 AppError，都保留 3004/blocked；新增回归通过。
5. **pytest 配置冲突**：根旧成员3 pytest.ini 禁用 tmpdir；Orchestrator 新配置保留该插件，旧测试源码不改，409/42 回归通过。

### 尚未验证与部署前提

- 真实 LLM、语音供应商、外部安全审核、真实语音/内容质量、鉴权和付费额度管理均未验证。
- 只有固定 MOCK OCR/VLM，没有接入成员2实际模块；下一阶段需独立批准成员2→成员3链路。
- 逐文件替换不是跨文件事务；跨进程同页写、并发读者一致性、进程崩溃/断电恢复和压力测试未完成。本阶段建议单进程，同页任务由现有幂等/force 管理。
- 线程取消等待后台步骤退出，不是强杀进程；阶段预算/严格墙钟超时还需后续验收。
- 分离原 Mock、成员3静音与未来真实引擎 DATA_DIR，避免来源共享的缓存误用。
- 当前环境 Pydantic 为 2.14.2，而现有 Orchestrator requirements 精确固定 2.14.1；本轮没有改依赖或验证全新锁定环境安装。建议 PR 前按团队锁定环境复现；本结论限定于列出的实际环境。
- page_no 仍沿用原 CaptureForm 的 1–99 限制，与 API 文档的边界待确认事项保留，没有修改契约或原限制。
- 本轮未新增 CORS；本机真实 HTTP 可用不等于独立浏览器前端跨域或局域网部署已验收。

目前没有本轮范围内未解决的测试失败或新阻塞问题。以上限制需随 PR 说明，不自动扩大为真实模型或生产验收。

## 11. 证据和本机复现

证据目录 R：

```text
C:/Users/16173/Documents/ChatGPT/人工智能+/module-integration-20261108/member3-orchestrator-v116/
```

| 证据 | 位置（相对 R） |
|---|---|
| 最终分组 XML | `logs/schema.xml`、`api.xml`、`member134.xml`、`additional.xml`、`integration.xml` |
| 分组控制台输出 | 对应 `logs/*.log` |
| 实际命令/退出码 | `run-results.json`、`additional-results.json`、`orchestrator-results.json` |
| HTTP 请求响应/轮询/解码 | `http-integration-results.json`、`logs/http-story.json` |
| 服务日志/隔离记录 | `logs/http_integration_server.log`、`logs/guard-*.json` |
| HTTP 实际输出/下载文件 | `http-data/`、`downloads/` |
| 分组统计/源码不变/版本/服务退出 | `FINAL_SUMMARY.json` |
| 原有两文件修改 diff、空白检查 | `final-tracked.diff`、`diff-check.txt` |
| 新文件完整清单 | `new-files.txt`（最终报告生成后刷新） |

启动和复测的具体 Windows 命令见 `docs/MEMBER3_V116_INTEGRATION.md`。仅使用现有已核实解释器和工具，不要求提供密钥。

## 12. 队长验收建议

建议审查本隔离分支的 Adapter、取消/发布边界、错误/降级映射和本报告，确认团队依赖环境与后续单进程策略后，批准申请 PR。此处只给建议，不创建 PR，不暂存、提交、推送或合并。

**最终结论：A：隔离集成全部通过，可以申请队长批准 PR。**
