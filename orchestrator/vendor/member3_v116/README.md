# 纸书智伴 · 成员 3（Story / TTS / Video）

按 `docs/API_v1.0.md`（ZSZB-API-1.0 冻结版）实现的生成侧模块：**故事生成 → 语音合成 → 视频合成**。
当前版本 **v1.1.6**（分支 `wzy622-patch-1`）：**134 项自动化测试通过**，`A6 POST /api/v1/tts` 已用真实 HTTP 跑通，
Story / TTS / Video 可分别独立运行；三个入口共用同一套安全检查，产物必须“先验证、后发布”。

> 本目录是**从零按契约搭的骨架**（仓库 `liushizhang32-source/space` 返回 404，拿不到 dev 分支）。
> 接入仓库时：`agents/generation/` 原样放到 `agents/` 下，`tests/`、`docs/`、`examples/`、`artifacts/`、
> `.env.example`、`requirements.txt` 合并进同名目录，分支用 `wzy622-patch-1`，PR 目标 `dev`。

![story frame](docs/images/story-frame.png)

> 上图是 `demo` 用内置样例页 + 静音 TTS 生成的画面：字幕条为真实渲染，**音频与故事都是 mock**，不代表真实模型效果。

## 这个模块负责什么

| 契约 | 产物 / 接口 | 代码 |
|---|---|---|
| C3 | `json/{page_id}_story.json` | `agents/generation/story/` |
| C4 | `json/{page_id}_video.json` + `videos/{page_id}_video.mp4` | `agents/generation/video.py` |
| A6 | `POST /api/v1/tts` | `agents/generation/tts/` |

输入只读成员 2 的 `json/{page_id}_ocr.json`、`json/{page_id}_vlm.json`，不写它们的文件、不反向调用。

## 快速开始

```bash
# 1) 依赖（沙箱内已把 wheel 解压到 _vendor/，正常环境直接 pip）
pip install -r requirements.txt

# 2) 配置：复制 .env.example 为 .env，至少确认 FFMPEG_PATH 指向可用的 ffmpeg
#    不配 LLM_* 时故事走 mock 模板；不配 TTS_HTTP_URL 时 TTS 走静音 mock

# 3) 自检
python -m agents.generation check

# 4) 用内置 mock 页跑通全链路（不需要成员 2 的产物）
python -m agents.generation demo --overwrite
# -> _demo_data/json/{story,video}.json + _demo_data/videos/book01_p03_video.mp4

# 5) 启动 A6 服务
python -m agents.generation serve --port 8001
curl -s http://127.0.0.1:8001/api/v1/tts -H "Content-Type: application/json" -d '{"text":"小朋友，你好。"}'

# 6) 测试
pytest
```

> 在离线沙箱里跑（没有 pip 安装权限）时，先把 `_vendor` 加进 `PYTHONPATH`：
> `$env:PYTHONPATH = ".;_vendor"`（PowerShell）或 `export PYTHONPATH=.:_vendor`，再执行上面的命令。

Windows 下如果 `ffmpeg` 不在 PATH，可在 `.env` 里写 `FFMPEG_PATH=D:\ffmpeg\bin\ffmpeg.exe`、
`FFPROBE_PATH=D:\ffmpeg\bin\ffprobe.exe`。

## 命令清单

```
python -m agents.generation run    --page-id book01_p03 --age-level 3-6 [--no-video]
python -m agents.generation story  --page-id book01_p03 --age-level 3-6
python -m agents.generation video  --page-id book01_p03
python -m agents.generation tts    --text "..." [--speed 0.95] [--format mp3]
python -m agents.generation serve  --host 127.0.0.1 --port 8001
python -m agents.generation check
python -m agents.generation schema --out docs/schemas
python -m agents.generation demo   [--variant text|wordless] [--no-video] [--overwrite]
```

`run` 的 stdout 就是给中枢用的 `pages[]` 结构（`page_id / page_no / status / degraded /
story_url / video_url / error / elapsed_ms`），可直接塞进 job 状态机。

## 第七轮修复（v1.1.6，隔离复测后）

- **恢复日志容错**：先 WARNING，主日志失败写备用日志，两者都失败只记 ERROR；
  日志 I/O 失败不再抛出异常、不遮蔽 3007 恢复语义；
- 公共响应仍只带 `recovery_id`，不含本机路径。

逐条回应见 [docs/REVIEW_RESPONSE.md](docs/REVIEW_RESPONSE.md)。

## 第六轮修复（v1.1.5，独立运行测试后）

1. **发布恢复错误不重试**：`VideoPublishError.retryable=False`，`compose_video` 显式短路；
2. **恢复诊断可追踪**：pipeline 写 `logs/{page_id}_publish_errors.jsonl` 并 WARNING，
   公共响应只给 `recovery_id`，不泄漏本机路径。

逐条回应见 [docs/REVIEW_RESPONSE.md](docs/REVIEW_RESPONSE.md)。

## 第五轮审查修复（v1.1.4）

针对 F01–F03 三项视频发布阻塞，逐条回应见 [docs/REVIEW_RESPONSE.md](docs/REVIEW_RESPONSE.md)：

1. **提交与清理分离**：备份删除失败只告警，绝不回滚已提交产物；
2. **回滚失败保留证据**：分步恢复、保留 `.bak`、抛 `VideoPublishError` 并给出路径；
3. **锁覆盖回滚**：备份/提交/回滚在同一页级锁内，回滚不再释放锁；
4. **MIME 精确判定**：裸 MIME 白名单，`text/html; charset` 不再误判。

## 第四轮审查修复（v1.1.3）

针对 R112-01～R112-04 四项阻塞，逐条回应见 [docs/REVIEW_RESPONSE.md](docs/REVIEW_RESPONSE.md)：

1. **安全时序**：最终 `scene` 与 `narration` 在 TTS 前统一审核；3004 不再被降级成 no_audio；
   视频阶段 3004 保持 blocked。
2. **Video 事务发布**：唯一临时名 + 页级锁 + 旧版本备份，失败回滚，finally 清理；
   声明了 audio_url 但文件缺失直接报错。
3. **HTTP 严格校验**：JSON 必须对象、base64 严格校验、text/html 包 JSON 拒绝、
   wav 只认 wav 容器、超时映射 2002。
4. **Story 模型对齐**：`status=ok`、`highlight_object_ids` 默认 `[]` 且拒绝 null、
   `safety_flags` 默认 `[]`、完整 ID 格式。

## 第三轮审查修复（v1.1.2）

针对报告中的 4 项 P0 复查项 + 2 项 P1 风险，逐条回应见 [docs/REVIEW_RESPONSE.md](docs/REVIEW_RESPONSE.md)：

1. **Video 拒绝 `safety_pass=false`**：即使安全开关关闭，story 自带 false 也返 3004、不产出。
2. **先验证后发布**：静音 TTS 写 `.part` 先深检再替换；Video 先验临时 mp4 再 move，然后写 JSON。
3. **HTTP 补齐**：错误体限长读取、容器格式（`format_name`）校验、缓存深检 + 格式比对。
4. **并发与误删**：临时名加线程/uuid；失败不再删除已有有效文件；Windows 替换退避重试。
5. **Story 输入身份**：ocr/vlm 的 `schema_version/page_id/page_no/book_id` 必须与请求页一致；
   未知枚举按 `failed` 处理。

## 第二轮审查修复（v1.1.1）

审查结论仍为 B（局部问题），本轮 4 项安全 + 3 项结构问题全部处理，详见 [docs/TEST_REPORT-v1.1.1.md](docs/TEST_REPORT-v1.1.1.md)：

1. **统一安全入口**：`safety.ensure_safe` / `guard_text` / `ensure_story_safe`，
   Story、TTS（含 A6 独立调用）、Video 三条路径都接入，无法绕过。
2. **缺 ffmpeg 不得算通过**：媒体校验三态 `OK / INVALID / UNAVAILABLE`；
   缺 ffmpeg 时 TTS 返 2004、Video 返 2004 且不发布产物。
3. **HTTP 下载校验**：状态码、Content-Type、Content-Length/实际大小、真实格式、可解码；
   超限/错误页/格式不符直接判失败。
4. **临时文件清理**：超时、解码失败、格式不符都删 `.part` 与半成品。
5. **highlight 归属**：`highlight_object_ids` 必须属于当前 `page_id`。
6. **Schema 一致性**：模型 ↔ 导出 JSON Schema ↔ C3 字段集合有自动比对测试。

## 第一轮审查修复（v1.1.0）

1. **A6 异常处理器**：`JSONResponse(200, ...)` 参数位置错误 → 改关键字参数，handler 提为模块级。
2. **降级空 scene**：`fallback_scene()` 五级兜底；`StorySegment.scene` 强制非空。
3. **生成后安全检查**：输入 / 生成草稿 / 落盘前三道闸。
4. **音频/视频有效性**：`media.probe_audio/probe_video` 校验存在、编码、时长、可解码。

## 目录

```
agents/generation/
  config.py     环境变量 -> Settings（全部有默认值，不配也能跑）
  errors.py     契约错误码 + 可重试白名单
  ids.py        page_id / segment_id / ULID / TTS 内容哈希
  schemas.py    C3、C4 的 Pydantic 模型（extra=allow，additionalProperties=true）
  safety.py     内容安全：输入 / 生成后 / 落盘前三道闸
  storage.py    DATA_DIR 布局、原子写、相对路径 -> 绝对 URL
  proc.py       子进程封装（超时 -> 2002、隐藏控制台）
  media.py      ffprobe 音频/视频有效性探测（存在、编码、时长、可解码）
  envelope.py   code/msg/data/trace_id 统一响应
  story/llm.py  故事 LLM 客户端（OpenAI 兼容，重试 1 次）
  story/        故事生成：LLM 通道 + mock 模板通道 + 降级判定
  tts/          静音/HTTP 引擎、内容哈希缓存、A6 FastAPI 路由
  video.py      ffmpeg 合成：静帧 + 配音 + 字幕条（Pillow 预渲染 overlay）
  pipeline.py   单页 story->tts->video，输出页面状态与 degraded
  cli.py        命令行入口
tests/          134 项用例（schema、安全入口、HTTP 下载、降级矩阵、缓存、错误码、媒体有效性、并发、端到端）
docs/GENERATION.md    实现细节
docs/IO_EXAMPLES.md   三个模块各自的输入输出示例
docs/TEST_REPORT.md   第七轮（v1.1.6）修复报告
docs/TEST_REPORT-v1.1.5.md ～ -v1.1.0.md  历史报告
docs/REVIEW_RESPONSE.md  对隔离复测意见的逐条回应
docs/CHANGELOG.md     版本变更记录
artifacts/            本轮实际音视频产物 + ffprobe 证据 + Schema 校验结果
```

## Mock 与真实产物

- **故事**：`story.json.model.name` 会写实际来源。没配 `LLM_*` 时是 `mock-template`，
  配了就是 `LLM_MODEL` 的值——评测/演示时直接看这个字段就能区分。
- **音频**：默认 `TTS_ENGINE=silent`，生成的是**等长静音 mp3**（时长按 220 字/分钟估算），
  文件名仍是 `tts_{sha1_12}.mp3`，缓存逻辑与真实引擎一致。接真实 TTS 只需配 `TTS_HTTP_URL`。
- **视频**：画面是真实 ffmpeg 合成的，但配的是静音音轨，所以**不能当作“AI 配音效果”演示**。

## 与其他人怎么对接

- **成员 1（中枢）**：`pipeline.run_page()` 可直接进程内调用；也可 `python -m agents.generation run`
  拿 JSON。中枢只负责调度、重试、聚合 job 状态，不重复实现故事/视频逻辑。
- **成员 4（问答）**：只调 `POST /api/v1/tts`，不要自己接 TTS SDK；音色统一走 `TTS_VOICE_ID`。
- **成员 5（评测）**：直接读 `json/*_story.json`、`json/*_video.json`，字段见 `docs/schemas/`。

## 已知未决 / 需要群里确认

1. **Q4 分辨率**：Q4 建议 720×1280，C4 示例写 1080×1920。默认取 720×1280（render 更稳），
   改 `VIDEO_RESOLUTION` 即可切换，不改代码。
2. **Q10 取消接口**：正文没有 `POST /jobs/{id}/cancel`，本模块不实现；需要的话按冻结流程加版本。
3. **120 字限制**：A6 单次 `text ≤120`，所以 story 的 `narration` 必须在 120 字以内。本模块已强制
   切分；如果成员 3 之外有人直接往 story.json 写长旁白，TTS 会返 1002。
4. **Job 级重试归属**：本模块只实现阶段内重试（Story 1 次、Video 1 次），job 级重试与
   `MAX_CONCURRENT_JOBS` 由成员 1 负责。
5. **C3 `scene` 必填性**：字段表没列 `scene`，但示例有。v1.1.0 起强制非空（降级时用画面描述/物体/标签兜底），
   如果评审认为应可选，可去掉校验而不影响消费方。
