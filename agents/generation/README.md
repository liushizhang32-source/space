# 纸书智伴 · 成员 3（Story / TTS / Video）

按 `docs/API_v1.0.md`（ZSZB-API-1.0 冻结版）实现的生成侧模块：**故事生成 → 语音合成 → 视频合成**。
当前状态：**60 项自动化测试通过**，`A6 POST /api/v1/tts` 已用真实 HTTP 跑通，`demo` 能产出一页完整 mp4。

> 本模块从 `feat/generation` 分支合入 `dev`：代码在 `agents/generation/`，测试在根目录 `tests/`，
> schema 在 `docs/schemas/`，接口契约见 `docs/API_v1.0.md`。

![story frame](../../docs/images/story-frame.png)

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

## 目录

```
agents/generation/
  config.py     环境变量 -> Settings（全部有默认值，不配也能跑）
  errors.py     契约错误码 + 可重试白名单
  ids.py        page_id / segment_id / ULID / TTS 内容哈希
  schemas.py    C3、C4 的 Pydantic 模型（extra=allow，additionalProperties=true）
  storage.py    DATA_DIR 布局、原子写、相对路径 -> 绝对 URL
  proc.py       子进程封装（超时 -> 2002、隐藏控制台）
  media.py      ffprobe 时长/采样率探测
  envelope.py   code/msg/data/trace_id 统一响应
  llm.py        故事 LLM 客户端（OpenAI 兼容，重试 1 次）
  story/        故事生成：LLM 通道 + mock 模板通道 + 降级判定
  tts/          静音/HTTP 引擎、内容哈希缓存、A6 FastAPI 路由
  video.py      ffmpeg 合成：静帧 + 配音 + 字幕条（Pillow 预渲染 overlay）
  pipeline.py   单页 story->tts->video，输出页面状态与 degraded
  cli.py        命令行入口
tests/          57 项用例（schema、降级矩阵、缓存、错误码、重试、端到端）
docs/GENERATION.md  详细说明：接口、状态判定、Mock 边界、联调注意
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
5. **C3 `scene` 必填性**：字段表没列 `scene`，但示例有。本模块始终输出（降级时用画面描述兜底），
   若评审认为应可选，可去掉校验而不影响消费方。
