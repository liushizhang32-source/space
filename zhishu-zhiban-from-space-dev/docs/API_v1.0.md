# 纸书智伴 · 接口文档 v1.0（定稿）

> 本文档是 5 个模块之间传数据的合同。冻结后只许新增可选字段，不许改名、不许改类型、不许改必填性。

| 项目 | 内容 |
|---|---|
| 文档编号 | ZSZB-API-1.0 |
| 版本 | v1.0（冻结） |
| 日期 | 2026-11-04 |
| 拟定 | 队长（成员1） |
| 评审 | 架构评审 |
| 状态 | 已冻结，可据此开工 |
| 存放位置 | 仓库 `docs/API_v1.0.md`（与代码同版本管理） |

**冻结规则**

1. 字段改名、改类型、改必填性、改枚举值 → 版本升 v1.1，全员回归，禁止单人改动。
2. 新增字段必须**可选**，消费方必须忽略未知字段；JSON Schema 禁止 `additionalProperties: false`。
3. 争议以本文档为准，群聊结论无效；改动必须走 PR 并同步版本号。
4. 任何一天发现本文档和代码不一致，改代码，不改文档（除非文档本身就错，走第 1 条）。

**文档结构**

- 第 1 章：契约本体——可以照着直接写代码的部分。冻结后只许新增可选字段。
- 附录 A–D：评审记录、分工、联调用例、待确认问题。过程材料，不参与实现；改字段前必读附录 A。

**修订记录**

| 版本 | 日期 | 变更 | 作者 |
|---|---|---|---|
| v1.0-draft | 2026-11-03 | 初稿，5 个模块接口 | 队长 |
| v1.0 | 2026-11-04 | 补齐 7 个 HTTP 接口、4 个文件契约、三级状态、错误码、降级矩阵；修复 12 个 P0；正文改为契约前置、过程材料降为附录 | 队长 + 架构评审 |

<!-- pagebreak -->
# 第 1 章 · 接口契约（冻结本体）

## 1.1 系统架构与调用流程

```
┌─────────┐
│ 前端(4) │  拍照 / 生成 / 点读 / 问答
└────┬────┘
     │ HTTP  /api/v1/*
┌────▼──────────────────────────────────┐
│ 编排中枢 Orchestrator (成员1)          │
│  /capture /generate /jobs /health     │
│  状态机 · 重试 · 降级 · 日志           │
└──┬──────────┬──────────┬──────────┬───┘
   │ 文件契约  │ 文件契约  │ 文件契约  │ HTTP
┌──▼───┐  ┌───▼──┐  ┌────▼────┐  ┌──▼────┐
│ OCR  │  │ VLM  │  │ Story   │  │ TTS   │
│ (2)  │  │ (2)  │  │ +Video  │  │ (3)   │
└──────┘  └──────┘  │  (3)    │  └───▲───┘
                    └─────────┘      │
┌──────────┐   ┌──────────┐          │
│ ASR (4)  │──▶│ QA  (4)  │──────────┘
└──────────┘   └──────────┘
                    │
              ┌─────▼─────┐
              │ 评测 (5)  │  读全部产物
              └───────────┘
```

**一次生成流程（时序）**

```
前端 → POST /capture          存图 + 返回 page_id / image_width / image_height
前端 → POST /generate         建 job，异步入队，立即返回 job_id
中枢 → OCR(成员2)             写 json/{page_id}_ocr.json
中枢 → VLM(成员2)             写 json/{page_id}_vlm.json
中枢 → Story(成员3)           读 ocr+vlm，调 TTS 内部函数，写 json/{page_id}_story.json
中枢 → Video(成员3)           读 story，合成，写 json/{page_id}_video.json + videos/*.mp4
前端 → GET /jobs/{id} 轮询     2s 一次，直到 done / partial_failed / failed
```

**一次问答流程（时序）**

```
前端 → POST /asr              音频 → 文本（成员4）
前端 → POST /qa               page_id + question(+tap) + session_id
QA   → 读 story.json 组织上下文
QA   → LLM 生成答案
QA   → POST /tts              答案转语音（成员3）
QA   → 返回 answer + citations + audio_url
```

## 1.2 统一约定

### 1.2.1 统一响应格式

**所有 HTTP 接口一律返回 HTTP 200**，错误只看 `code`。禁止混用 HTTP 状态码（否则前端要判两层）。

```json
{
  "code": 0,
  "msg": "ok",
  "data": {},
  "trace_id": "tr_01JB8Z3K4M5N6P7Q8R9S0T1V2W"
}
```

失败：

```json
{
  "code": 1001,
  "msg": "缺少参数 page_id",
  "data": null,
  "trace_id": "tr_01JB8Z3K4M5N6P7Q8R9S0T1V2W"
}
```

### 1.2.2 ID 规范

| 对象 | 规则 | 正则 | 示例 | 生成方 |
|---|---|---|---|---|
| `book_id` | 小写字母开头，字母数字，4~12 位 | `^[a-z][a-z0-9]{3,11}$` | `book01` | 中枢 |
| `page_id` | `{book_id}_p{2位页码}` | `^[a-z][a-z0-9]{3,11}_p\d{2}$` | `book01_p03` | 中枢 |
| `block_id` | `{page_id}_t{2位}` | `^.+_t\d{2}$` | `book01_p03_t01` | 成员2 |
| `object_id` | `{page_id}_o{2位}` | `^.+_o\d{2}$` | `book01_p03_o01` | 成员2 |
| `segment_id` | `{page_id}_s{2位}` | `^.+_s\d{2}$` | `book01_p03_s01` | 成员3 |
| `job_id` | `job_` + ULID(26) | `^job_[0-9A-HJKMNP-TV-Z]{26}$` | `job_01JB8Z...` | 中枢 |
| `session_id` | `ses_` + 8~32 位小写字母数字 | `^ses_[a-z0-9]{8,32}$` | `ses_abc12345` | 前端 |
| `answer_id` | `ans_` + ULID(26) | `^ans_[0-9A-HJKMNP-TV-Z]{26}$` | `ans_01JB8Z...` | 成员4 |
| `trace_id` | `tr_` + ULID(26) | `^tr_[0-9A-HJKMNP-TV-Z]{26}$` | `tr_01JB8Z...` | 入口生成 |

约束：

- `book_id` **禁止含下划线**，保证 `page_id` 可用最后一个 `_p` 切分。
- 所有派生 ID 稳定可复现，禁止用随机 UUID（前端要能算出来，评测要能对齐）。
- 一页一故事，故事的键就是 `page_id`，不另设 `story_id`。

### 1.2.3 坐标规范

```json
"bbox": [x1, y1, x2, y2]
```

- 原图像素、整数、左上角为原点。
- `x2`/`y2` 为右下角**不含**端点；`x1 < x2`，`y1 < y2`。
- 每个页面级产物必须提供 `image_width` / `image_height`。
- 前端缩放公式：`x_disp = x * 显示宽 / image_width`。
- 禁止归一化坐标、禁止浮点。

### 1.2.4 时间与单位

- 时长：`*_ms`（毫秒）/ `*_sec`（秒），**后缀即单位**，不得混用。
- 时间戳：`*_at`，ISO-8601 UTC 带 `Z`，例 `2026-11-04T12:00:00.000Z`。
- 概率：`confidence`，0~1 浮点。

### 1.2.5 版本

- HTTP 路径统一 `/api/v1/`。
- 模块间 JSON 顶层必带 `"schema_version": "1.0"`。
- 消费方**必须忽略未知字段**；JSON Schema 禁止写 `additionalProperties: false`（与"只许新增字段"冲突）。

### 1.2.6 枚举

全部 `lower_snake_case` 字符串，禁止数字枚举。消费方必须对未知值走 `default` 分支。

## 1.3 错误码

| 码 | 含义 | 可重试 | 典型场景 |
|---|---|---|---|
| 0 | 成功 | — | — |
| 1001 | 参数缺失 | 否 | 缺 `page_id` / 点读缺 `tap` |
| 1002 | 参数非法 | 否 | `book_id` 格式错、`input_type` 未知 |
| 1003 | 资源不存在 | 否 | `job_id` / `page_id` 查不到 |
| 1004 | 文件过大 | 否 | 图 > 10MB |
| 1005 | 未鉴权 | 否 | 内网演示可不启用 |
| 1006 | 文件类型不支持 | 否 | 传了 gif/tiff |
| 2001 | 模型调用失败 | 是 | LLM/OCR/VLM 返回错误 |
| 2002 | 超时 | 是 | 阶段超时 |
| 2003 | 限流 | 是 | 并发 > 3 |
| 2004 | 服务不可用 | 是 | TTS 服务未启动 |
| 3001 | 未识别到文字 | 否 | OCR 空结果（**非错误**，走 empty 分支） |
| 3002 | 未检测到语音 | 否 | ASR 静音，前端提示重录 |
| 3003 | 超出绘本范围 | 否 | QA 拒答 |
| 3004 | 内容安全拦截 | 否 | 三层任一触发 |
| 3005 | 任务不存在 | 否 | `job_id` 无效 |
| 3006 | 任务已终态 | 否 | 对终态 job 重复操作 |
| 3007 | 视频生成失败 | 是 | ffmpeg 报错 |
| 3008 | 语音合成失败 | 是 | TTS 报错 |
| 9001 | 未预期错误 | 是 | 兜底 |

> `3001`、`3002`、`3003`、`3004` 是**业务结论**，不是系统故障。它们出现在 `code` 里是为了让前端能分支，但不应计入错误率。

## 1.4 API 清单

| # | 方法 | 路径 | 归属 | 调用方 | 同步/异步 |
|---|---|---|---|---|---|
| A1 | POST | `/api/v1/capture` | 成员1 | 前端 | 同步 10s |
| A2 | POST | `/api/v1/generate` | 成员1 | 前端 | 同步建任务 |
| A3 | GET | `/api/v1/jobs/{job_id}` | 成员1 | 前端 | 同步 |
| A4 | POST | `/api/v1/asr` | 成员4 | 前端 | 同步 10s |
| A5 | POST | `/api/v1/qa` | 成员4 | 前端 | 同步 30s |
| A6 | POST | `/api/v1/tts` | 成员3 | 成员4 / 成员3 内部 | 同步 20s |
| A7 | GET | `/api/v1/health` | 成员1 | 全员 / 演示前自检 | 同步 3s |

## 1.5 A1 · POST /api/v1/capture

**用途**：上传一页绘本照片，分配 `page_id`。**只存储，不触发 OCR**（OCR 在 `/generate` 时由中枢触发）。

**请求**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `image` | file | 是 | jpg/png/webp，≤10MB，长边 ≤4096 |
| `book_id` | string | 否 | 不传则服务端新建一本书并返回 |
| `page_no` | int | 是 | 从 1 开始 |

**响应**：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "book_id": "book01",
    "page_id": "book01_p03",
    "page_no": 3,
    "preview_url": "http://127.0.0.1:8000/previews/book01_p03_preview.jpg",
    "image_width": 1654,
    "image_height": 2339
  },
  "trace_id": "tr_01JB8Z3K4M5N6P7Q8R9S0T1V2W"
}
```

**错误**：`1001` 缺 `page_no`/`image`；`1004` 超 10MB；`1006` 格式不支持；`1002` `page_no` < 1。

**说明**：`image_width` / `image_height` 必须返回，后续所有 `bbox` 以它为参照系。

## 1.6 A2 · POST /api/v1/generate

**用途**：创建生成任务（OCR → VLM → Story → TTS → Video）。

**请求**：

```json
{
  "page_ids": ["book01_p03"],
  "age_level": "3-6",
  "force": false
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `page_ids` | string[] | 是 | v1 只传 1 个；数组为整本预留，长度 ≤ 30 |
| `age_level` | string | 是 | `3-6` / `6-9` |
| `force` | bool | 否 | 默认 `false`；`true` 时取消同页 `running` 任务并新建 |

**响应**：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "job_id": "job_01JB8Z3K4M5N6P7Q8R9S0T1V2W",
    "status": "queued",
    "poll_after_ms": 2000
  },
  "trace_id": "tr_01JB8Z3K4M5N6P7Q8R9S0T1V2W"
}
```

**幂等规则**：

- `force=false` 且同 `page_id` 存在 `queued`/`running` 任务 → 返回**同一个** `job_id`，不新建。
- `force=true` → 旧的置 `cancelled`，新建一个。
- 已 `done` 且 `force=false` → 新建（重新生成一份，覆盖同名文件）。

**错误**：`1001` 缺 `page_ids`；`1002` 页数 > 30 / `age_level` 非法；`1003` `page_id` 不存在；`2003` 并发 > 3。

## 1.7 A3 · GET /api/v1/jobs/{job_id}

**响应**：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "job_id": "job_01JB8Z3K4M5N6P7Q8R9S0T1V2W",
    "status": "running",
    "progress": 60,
    "current_stage": "render",
    "pages": [
      {
        "page_id": "book01_p03",
        "page_no": 3,
        "status": "processing",
        "stages": [
          {"name": "ocr",    "status": "ok",      "elapsed_ms": 1830},
          {"name": "vlm",    "status": "ok",      "elapsed_ms": 2100},
          {"name": "story",  "status": "ok",      "elapsed_ms": 8600},
          {"name": "tts",    "status": "ok",      "elapsed_ms": 4200},
          {"name": "render", "status": "running", "elapsed_ms": null}
        ],
        "video_url": null,
        "story_url": null,
        "degraded": [],
        "error": null
      }
    ],
    "error": null,
    "created_at": "2026-11-04T12:00:00.000Z",
    "updated_at": "2026-11-04T12:01:00.000Z"
  },
  "trace_id": "tr_01JB8Z3K4M5N6P7Q8R9S0T1V2W"
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | enum | `queued` / `running` / `done` / `partial_failed` / `failed` / `cancelled` |
| `progress` | int | 0~100，按"已完成阶段数 / 总阶段数 / 页数"加权 |
| `current_stage` | enum | `ocr` / `vlm` / `story` / `tts` / `render` |
| `pages[].status` | enum | `pending` / `processing` / `done` / `partial` / `blocked` / `failed` |
| `pages[].stages[].status` | enum | `ok` / `empty` / `failed` / `skipped` / `running` / `pending` |
| `pages[].degraded` | string[] | `no_ocr` / `no_scene` / `no_audio` / `no_video` |
| `video_url` | string \| null | 绝对 URL，`done`/`partial` 且 render 成功时非空 |
| `story_url` | string \| null | story.json 的静态 URL，供评测与调试 |

`pages[]` **按 `page_no` 升序**。

**三级状态模型**

阶段状态由模块写，页面状态由中枢按此表判定：

| OCR | VLM | Story | TTS | Render | 页面状态 | degraded |
|---|---|---|---|---|---|---|
| ok / empty | ok | ok | ok | ok | `done` | `[]` |
| failed | ok | ok | ok | ok | `partial` | `[no_ocr]` |
| ok / empty | failed | ok | ok | ok | `partial` | `[no_scene]` |
| failed | failed | skipped | skipped | skipped | `failed` | `[]` |
| ok / empty | ok | failed | skipped | skipped | `failed` | `[]` |
| ok / empty | ok | ok | failed | ok | `partial` | `[no_audio]` |
| ok / empty | ok | ok | ok | failed | `partial` | `[no_video]` |
| 任一层 safety=false | — | — | — | — | `blocked` | `[]` |

任务状态由页面状态聚合：

| 页面情况 | 任务状态 |
|---|---|
| 全部 `done` | `done` |
| 全部 `failed` / `blocked` | `failed` |
| 混合（≥1 成功且 ≥1 非成功） | `partial_failed` |

## 1.8 A4 · POST /api/v1/asr

**请求**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `audio` | file | 是 | webm/wav/mp3，≤60s，≤5MB |
| `page_id` | string | 是 | 用于日志与上下文 |
| `session_id` | string | 是 | 问答会话 |

**响应**：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "text": "小兔子去哪了",
    "confidence": 0.93,
    "duration_ms": 3200,
    "is_final": true
  },
  "trace_id": "tr_01JB8Z3K4M5N6P7Q8R9S0T1V2W"
}
```

**规则**：

- 静音 → `code: 3002`，`data: null`，前端提示"没听清，再录一次"。
- 转写文本**原样传给 QA，不纠错**（保留原设计决定）。
- 模型：`whisper-large-v3`，路径走环境变量。

## 1.9 A5 · POST /api/v1/qa

**请求**：

```json
{
  "schema_version": "1.0",
  "page_id": "book01_p03",
  "session_id": "ses_abc12345",
  "input_type": "voice",
  "question": "小兔子去哪了？",
  "tap": null,
  "history": [
    {"role": "user", "text": "这是谁？"},
    {"role": "assistant", "text": "这是小兔子。"}
  ]
}
```

**点读请求**：

```json
{
  "schema_version": "1.0",
  "page_id": "book01_p03",
  "session_id": "ses_abc12345",
  "input_type": "tap",
  "question": null,
  "tap": {"object_id": "book01_p03_o01", "label": "兔子"},
  "history": []
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `page_id` | string | 是 | 决定加载哪一页的 story.json |
| `session_id` | string | 是 | 前端生成并保存 |
| `input_type` | enum | 是 | `voice` / `text` / `tap` |
| `question` | string \| null | 条件 | `voice`/`text` 必填非空；`tap` 可空 |
| `tap` | object \| null | 条件 | `tap` 时必填；`voice`/`text` 时必须 `null` |
| `tap.object_id` | string | 是 | 对应 vlm.json 里的 `object_id` |
| `tap.label` | string | 是 | 中文 label，用于兜底问句 |
| `history` | array | 否 | ≤10 轮，超了服务端截断不报错 |

**`question` 为空且 `input_type=tap` 时**，后端用模板 `"这是什么？"` 作为问题，并把 `tap.label` 注入上下文。

**响应**：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "answer_id": "ans_01JB8Z3K4M5N6P7Q8R9S0T1V2W",
    "answer": "小兔子走进了夜晚的森林，去找它的朋友了。",
    "is_fallback": false,
    "citations": [
      {
        "page_id": "book01_p03",
        "object_ids": ["book01_p03_o01"],
        "bbox": [30, 40, 120, 150]
      }
    ],
    "audio_url": "http://127.0.0.1:8000/audios/tts_9f2c1a4b7d3e.mp3",
    "safety": {"pass": true, "flags": []},
    "latency_ms": {"asr": 420, "llm": 900, "tts": 780, "total": 2130}
  },
  "trace_id": "tr_01JB8Z3K4M5N6P7Q8R9S0T1V2W"
}
```

**规则**：

- 答不上来：`answer` 固定为 `"这个问题我还不知道，我们一起看看书上画了什么吧"`，`is_fallback: true`，`citations: []`，**不许胡编剧情**。
- 超出绘本范围 → `code: 3003`，`data` 仍返回兜底答案（前端两种都能处理）。
- 内容安全拦截 → `code: 3004`，`data.safety.pass = false`。
- `latency_ms` 仅供评测，前端不得依赖。

## 1.10 A6 · POST /api/v1/tts

**归属**：成员3（唯一 owner）。成员4 通过 HTTP 调用，成员3 内部走同进程函数。

**请求**：

```json
{
  "text": "从前有只小兔子，住在森林边上。",
  "voice_id": "female_warm",
  "speed": 0.95,
  "format": "mp3"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `text` | string | 是 | ≤120 字（超过返 `1002`） |
| `voice_id` | string | 否 | 默认取环境变量 `TTS_VOICE_ID` |
| `speed` | float | 否 | 0.5~2.0，默认 1.0 |
| `format` | string | 否 | 默认 `mp3` |

**响应**：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "audio_url": "http://127.0.0.1:8000/audios/tts_9f2c1a4b7d3e.mp3",
    "duration_ms": 4200,
    "sample_rate": 24000
  },
  "trace_id": "tr_01JB8Z3K4M5N6P7Q8R9S0T1V2W"
}
```

**路径规则**：输出文件名为 `tts_{sha1(text+voice_id+speed)前12位}.mp3`。同一句话重复调用直接命中缓存，不重复合成。

## 1.11 A7 · GET /api/v1/health

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "orchestrator": "ok",
    "ocr": "ok",
    "vlm": "ok",
    "story": "ok",
    "tts": "ok",
    "asr": "ok",
    "qa": "ok",
    "version": "1.0"
  },
  "trace_id": "tr_01JB8Z3K4M5N6P7Q8R9S0T1V2W"
}
```

任一模块不可用 → `2004`，`data` 里对应字段为 `"down"`。演示前必须跑一次。

## 1.12 模块间文件契约

模块间**不走 HTTP**，通过 `DATA_DIR` 下的 JSON 文件传递，路径固定：

```
{DATA_DIR}/json/{page_id}_ocr.json
{DATA_DIR}/json/{page_id}_vlm.json
{DATA_DIR}/json/{page_id}_story.json
{DATA_DIR}/json/{page_id}_video.json
```

### C1 · ocr.json（成员2 → 成员3）

```json
{
  "schema_version": "1.0",
  "book_id": "book01",
  "page_id": "book01_p03",
  "page_no": 3,
  "status": "ok",
  "image_width": 1654,
  "image_height": 2339,
  "text_blocks": [
    {
      "block_id": "book01_p03_t01",
      "order": 1,
      "text": "从前有座山",
      "bbox": [120, 240, 980, 300],
      "confidence": 0.98
    }
  ],
  "page_confidence": 0.98,
  "elapsed_ms": 1830
}
```

| 字段 | 说明 |
|---|---|
| `status` | `ok` / `empty`（无字绘本）/ `failed` |
| `order` | 人类阅读顺序，从 **1** 开始 |
| `confidence` | 块级 0~1 |
| `page_confidence` | 块级加权平均；`empty` 时 0 |

`empty` **不是失败**：下游走无字模式，页面状态仍可为 `done`。

### C2 · vlm.json（成员2 → 成员3）

```json
{
  "schema_version": "1.0",
  "book_id": "book01",
  "page_id": "book01_p03",
  "page_no": 3,
  "status": "ok",
  "image_width": 1654,
  "image_height": 2339,
  "description": "夜晚的森林，一只小兔子站在树下",
  "objects": [
    {"object_id": "book01_p03_o01", "label": "兔子", "bbox": [30, 40, 120, 150], "confidence": 0.92},
    {"object_id": "book01_p03_o02", "label": "树",   "bbox": [200, 10, 400, 300], "confidence": 0.96}
  ],
  "scene_tags": ["夜晚", "森林"],
  "safety": {"pass": true, "flags": []},
  "elapsed_ms": 2100
}
```

- `label` 用中文通用词（兔子 / 树 / 房子），**不用英文别名**。
- 无物体时 `objects: []`，`status: "empty"`。
- `object_id` 是主键，`label` 只用于展示。

### C3 · story.json（成员3 → 视频 / 问答 / 评测）

```json
{
  "schema_version": "1.0",
  "book_id": "book01",
  "page_id": "book01_p03",
  "page_no": 3,
  "title": "小兔子的冒险",
  "age_level": "3-6",
  "status": "ok",
  "segments": [
    {
      "segment_id": "book01_p03_s01",
      "order": 1,
      "narration": "从前有只小兔子，住在森林边上。",
      "scene": "夜晚的森林，月光洒在树梢",
      "image_prompt": "night forest, cute rabbit under tree, children's picture book style",
      "duration_sec": 8,
      "duration_source": "tts",
      "audio_url": "http://127.0.0.1:8000/audios/tts_9f2c1a4b7d3e.mp3",
      "highlight_object_ids": ["book01_p03_o01"]
    }
  ],
  "total_duration_sec": 8,
  "safety_pass": true,
  "safety_flags": [],
  "model": {"name": "qwen2-vl", "version": "2026-09"},
  "elapsed_ms": 8600
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `segment_id` | 是 | `{page_id}_s{2位}`，全局唯一 |
| `duration_sec` | 是 | **TTS 实测时长** |
| `duration_source` | 是 | `tts` / `estimate`（TTS 失败时估算） |
| `audio_url` | 条件 | `duration_source="tts"` 时必填 |
| `image_prompt` | 否 | v1 不消费，v2 图生图用 |
| `highlight_object_ids` | 否 | v1 视频忽略，点读用 |

### C4 · video.json（成员3 → 前端 / 评测）

```json
{
  "schema_version": "1.0",
  "book_id": "book01",
  "page_id": "book01_p03",
  "page_no": 3,
  "status": "ok",
  "video_url": "http://127.0.0.1:8000/videos/book01_p03_video.mp4",
  "duration_sec": 8,
  "resolution": "1080x1920",
  "fps": 25,
  "segments": [
    {"segment_id": "book01_p03_s01", "start_sec": 0, "end_sec": 8}
  ],
  "elapsed_ms": 128000
}
```

## 1.13 超时与重试

| 环节 | 超时 | 重试 | 退避 | 备注 |
|---|---|---|---|---|
| `POST /capture` | 10s | 1 | — | 同步 |
| OCR | 30s | 1 | 1s | 阶段 |
| VLM | 30s | 1 | 1s | 阶段 |
| Story | 60s | 1 | 2s | 阶段 |
| TTS（单段） | 20s | 2 | 1s | 阶段 |
| Video | 180s | 1 | 5s | 阶段 |
| `POST /asr` | 10s | 1 | — | 同步 |
| `POST /qa` | 30s | 1 | — | 含 LLM 12s + TTS 10s + 余量 |
| 单 job 总时长 | `300 + 240 × (页数-1)` 秒 | — | — | 超时置 `failed` |

**重试白名单**：仅 `2001`（msg 不含 safety）、`2002`、`2003`、`2004`、`3007`、`3008`。
**不重试**：`1xxx` 全部、`3003`、`3004`、`3006`（安全拦截重试无意义，且会重复计费）。

前端轮询：间隔 2s，最多 `总超时 / 2` 次；超了直接提示"生成超时，请重试"。

## 1.14 降级策略

| 故障 | 页面状态 | 行为 | degraded |
|---|---|---|---|
| OCR 失败，VLM 成功 | `partial` | 用画面描述 + 无字模式出故事 | `[no_ocr]` |
| OCR 成功，VLM 失败 | `partial` | 只用文字出故事 | `[no_scene]` |
| OCR empty（无字书） | `done` | 纯画面出故事 | `[]` |
| Story 失败 | `failed` | 该页无产物 | `[]` |
| TTS 失败 | `partial` | 静音 + 字幕，时长用字数估算（220 字/分钟） | `[no_audio]` |
| Video 失败 | `partial` | 返回图文分页数据，前端降级播放 | `[no_video]` |
| 安全拦截 | `blocked` | 该页不产出，前端显兜底文案 | `[]` |
| 全部页失败 | 任务 `failed` | 返回最后一次错误 | — |

**核心裁定**：只要 ≥1 页成功，任务就是 `partial_failed`，**不是 `failed`**。演示时永远有东西可放。

## 1.15 文件存储规范

```
{DATA_DIR}/
  uploads/   {page_id}_orig.{jpg|png|webp}      原图
  previews/  {page_id}_preview.jpg              缩略图
  json/      {page_id}_{ocr|vlm|story|video}.json
  audios/    tts_{sha1_12}.mp3                  TTS 输出（内容哈希）
  videos/    {page_id}_video.mp4
  logs/      {job_id}.log                       现场日志
```

规则：

1. 文件名 = `{page_id}_{模块}.{ext}`，TTS 例外用内容哈希（跨模块去重）。
2. **禁止**用时间戳、随机串做 key（不可复现、无法覆盖更新、缓存失效）。
3. 存储层只存**相对路径**，HTTP 响应时由网关拼 `ASSET_BASE_URL` 成绝对 URL。
4. 重新生成覆盖同名文件，前端靠 `job_id` 区分批次。
5. 产物保留 24h，演示前不清理。

## 1.16 环境变量

```
# ===== 视觉（成员2）=====
PADDLE_OCR_MODEL_DIR=./models/paddleocr
QWEN_VL_MODEL_PATH=./models/qwen2-vl
QWEN_VL_API_KEY=

# ===== 生成（成员3）=====
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
TTS_ENGINE=
TTS_VOICE_ID=female_warm
FFMPEG_PATH=ffmpeg

# ===== 语音（成员4）=====
WHISPER_MODEL_PATH=./models/whisper-large-v3

# ===== 存储 =====
DATA_DIR=./data
ASSET_BASE_URL=http://127.0.0.1:8000

# ===== 运行（成员1）=====
MAX_RETRY=1
STAGE_TIMEOUT_SEC=30
MAX_CONCURRENT_JOBS=3
```

命名规则：`{类别}_{提供方}_{参数}`。**禁止硬编码**，仓库只提交 `.env.example`。

## 1.17 模块调用关系矩阵

行 = 调用方，列 = 被调用方。`HTTP` = 走接口，`FILE` = 读文件，`—` = 无依赖。

| 调用方 ＼ 提供方 | 成员1 中枢 | 成员2 视觉 | 成员3 生成 | 成员4 前端+语音 | 成员5 评测 |
|---|---|---|---|---|---|
| 成员1 中枢 | — | `FILE` 读 ocr/vlm | `FILE` 读 story/video | — | — |
| 成员2 视觉 | `FILE` 写 ocr/vlm | — | — | — | — |
| 成员3 生成 | `FILE` 写 story/video | `FILE` 读 ocr/vlm | — | — | — |
| 成员4 前端+语音 | `HTTP` A1/A2/A3 | — | `HTTP` A6（TTS） | — | — |
| 成员5 评测 | `FILE` 读全部 | — | — | — | — |

**无循环依赖**：成员3 只读成员2 的产物，成员4 只调成员3 的 TTS，中枢只读写文件不反向调用。

<!-- pagebreak -->
# 附录 A · 评审记录：为什么这么定

## A.1 五个指定问题的裁定

### 问题 1：API 路径前缀不统一 —— 属实，P0

**位置**：§0.6 写"HTTP 统一 `/api/v1/` 前缀"，但 §1/§6/§7 实际路径是 `/api/capture`、`/api/generate`、`/api/jobs/{job_id}`、`/api/qa`、`/api/asr`、`/api/tts`。约定和正文打架。

**为什么是问题**：前端只配一个 `BASE_URL`。如果一半接口带 `/v1`、一半不带，前端要么写死两套拼接、要么每次联调改一遍。等发现时，成员1 的路由、成员4 的请求封装都已经写完了。

**修改方案**：全部统一为 `/api/v1/{资源}`，约定与正文一致。

```
POST /api/v1/capture
POST /api/v1/generate
GET  /api/v1/jobs/{job_id}
POST /api/v1/asr
POST /api/v1/qa
POST /api/v1/tts
GET  /api/v1/health
```

**影响模块**：成员1（路由注册）、成员3（TTS 服务）、成员4（前端 BASE_URL、ASR/QA 调用）。

### 问题 2：VLM、Story 输出缺 `page_no` —— 属实，P1

**位置**：接口 2（vlm.json）、接口 3（story.json）只有 `book_id` + `page_id`，没有整型 `page_no`；接口 1（ocr.json）有。

**为什么是问题**：三个后果。① 排序：`page_id` 是字符串，`book01_p10` 会排到 `book01_p2` 前面，整本聚合必须靠切字符串；② 评测：成员5 人工标注按页号对齐，只能反解析；③ 索引：按 `page_no` 排序是 O(n log n)，按字符串切分是每行一次正则。

**修改方案**：vlm.json、story.json 均补 `page_no`（整型，从 1 开始），与 ocr.json 一致。

**影响模块**：成员2（VLM 输出）、成员3（Story 输出）、成员5（评测排序）、成员1（聚合）。

### 问题 3：QA 的 `question` 必填与点读冲突 —— 属实，P0

**位置**：接口 4（`POST /api/v1/qa`）请求体把 `question` 作为必有字段。点读场景下用户只点了一个物体，没有自然语言输入。

**为什么是问题**：点读是四个界面之一（拍照 / 生成 / 点读 / 问答）。按现在的契约，点读要么造一个假问题塞进去（污染日志和评测），要么直接返 1001。第 10 天联调这条一定挂。

**修改方案**：`question` 改为**条件必填**，新增 `input_type` 区分三种入口，新增 `tap` 承载点读目标。

| `input_type` | `question` | `tap` | 后端行为 |
|---|---|---|---|
| `voice` | 必填，非空 | 必须为 `null` | ASR 转写文本直接用作问题 |
| `text` | 必填，非空 | 必须为 `null` | 手动输入 |
| `tap` | 可选（空则用模板"这是什么？"） | 必填，含 `object_id` | 以物体为锚点组织答案 |

**影响模块**：成员4（前端点读交互、QA 入参校验）、成员3（答案需要引用 `object_id` 做高亮）。

### 问题 4：OCR 失败后的降级逻辑不清 —— 属实，P0

**位置**：§9 降级矩阵写"单页 OCR 失败 → 用 VLM 画面出故事 → 标记 `status:"failed"` → `degraded:["no_ocr"]`"。**同一行里 `status` 是 failed，又说出故事、又出视频**，自相矛盾。

**根本原因**：混用了三个层级的状态——模块自己处理这一页的结果、中枢对这一页的最终结论、整个任务的结论。三者混成一个 `status`，编排代码没法写。

**修改方案**：拆成三级，谁写谁负责。

| 层级 | 字段 | 取值 | 写入方 |
|---|---|---|---|
| 阶段状态 | `stages[].status` | `ok` / `empty` / `failed` / `skipped` | 各模块自报 |
| 页面状态 | `pages[].status` | `pending` / `processing` / `done` / `partial` / `blocked` / `failed` | 编排中枢 |
| 任务状态 | `status` | `queued` / `running` / `done` / `partial_failed` / `failed` / `cancelled` | 编排中枢 |

关键裁定：**OCR 失败但 VLM 成功 → 页面状态是 `partial`，不是 `failed`**；只有"文字和画面都没有"才判 `failed`。判定表见 §1.7。

**影响模块**：成员1（编排判定）、成员2（自报阶段状态）、成员3（必须能处理"无文字输入"）、成员4（前端要渲染 partial 页面）。

### 问题 5：TTS 职责重复 —— 属实，P0

**位置**：模块表把 TTS 挂在"语音问答（成员4）"下，但又写"TTS 音色：成员3 定"；定稿把 TTS 放进 §7 却没写归属，同时故事 Agent（成员3）要产出 `duration_sec`、问答（成员4）要产出 `audio_url`。

**为什么是问题**：两处各实现一套，后果是①演示时视频一个音色、问答突然换一个，评委第一耳朵就听出来；②成员3 和成员4 各自接一次 TTS SDK，工作量翻倍；③`duration_sec` 到底谁测的说不清。

**修改方案**：**TTS 唯一归属成员3**，对外暴露 `POST /api/v1/tts`。

| 调用方 | 调用方式 | 用途 |
|---|---|---|
| 成员3（故事/视频） | 进程内函数调用（不走 HTTP） | 生成分段配音，测出 `duration_sec` |
| 成员4（问答） | HTTP `POST /api/v1/tts` | 生成答案朗读音频 |
| 成员1（编排） | `GET /health` 的 `tts` 字段 | 启动前探活 |

音色全局一份配置（`TTS_VOICE_ID`），禁止在请求里各传各的。TTS 输出路径用**内容哈希**（`tts_{sha1前12位}.mp3`），同一句话视频和问答重复合成时直接命中缓存，不重复计费。

**影响模块**：成员3（唯一 owner，需提供 HTTP 封装）、成员4（改为调用方，不实现）、成员1（探活）。

## A.2 全量审查发现

| # | 位置 | 问题 | 级别 | 修改方案 | 影响模块 |
|---|---|---|---|---|---|
| 1 | 超时表 | `/qa` 总超时 15s，但其内部要调 LLM（12s）+ TTS（20s），自身参数打架 | P0 | QA 端到端改 30s；TTS 在 QA 内限 10s | 成员4 |
| 2 | 任务总超时 | 单 job 300s，但单页 render 就要 180s，多页必超 | P1 | 总超时 = `300 + 240 × (页数-1)` 秒 | 成员1 |
| 3 | `session_id` | 全文档没人负责生成，只出现在请求里 | P1 | 前端首次进问答页时生成 `ses_` + 8~32 位小写字母数字，本地保存 | 成员4 |
| 4 | `history` | 谁维护未定义，前端传则不可信 | P2 | v1 由前端传、后端截断到 10 轮；v2 再迁到服务端 | 成员4 |
| 5 | job `pages[]` | 有 `"story": null` 字段，但结构从未定义 | P1 | 改为 `story_url`（字符串），指向 story.json 静态地址 | 成员1,4 |
| 6 | `voice_id` | 出现在 `/generate` 请求体，但音色是全局配置，两处冲突 | P2 | 从 generate 移除，只保留环境变量 `TTS_VOICE_ID` | 成员1,4 |
| 7 | `story_id` | job 结果里有 `story_id`，但一页一故事，与 `page_id` 1:1，纯冗余 | P2 | 删除，统一用 `page_id` 关联 | 成员1,3,4 |
| 8 | 问答安全 | 问答层用错误码 `3004` 表达拦截，画面/故事层用 `safety` 字段，两套表达 | P2 | 问答层也用 `data.safety`，`code` 仍为 0（拦截是正常业务结果） | 成员4 |
| 9 | `image_prompt` | v1 用"图文+配音"简化合成，该字段实际不消费，却标必填 | P2 | 改可选，注明"v1 不消费，v2 图生图用" | 成员3 |
| 10 | `highlight_object_ids` | 同上，v1 视频不消费 | P2 | 改可选，注明 v1 忽略 | 成员3 |
| 11 | 幂等 | "running 时重复提交返回同一 job_id"导致无法重新生成 | P1 | 增加 `force: bool`，默认 false；true 则新建 job 并取消旧的 | 成员1,4 |
| 12 | `pages[]` 顺序 | 多页结果未规定顺序 | P2 | 按 `page_no` 升序，写死 | 成员1,4 |
| 13 | OCR `empty` | 无字绘本被判 empty 后，故事怎么生成没写 | P1 | empty 不算失败，走无字模式，页面状态 `done` | 成员2,3 |
| 14 | 文件命名 | TTS 若按 `{page_id}_audio_{nn}` 命名，同一句话被视频和问答各生成一份 | P2 | TTS 输出改用内容哈希 `tts_{sha1_12}.mp3` | 成员3,4 |
| 15 | URL 拼接 | 绝对路径依赖 `ASSET_BASE_URL`，换机器要改所有存量数据 | P1 | 存储只存相对路径，响应时由网关拼 `ASSET_BASE_URL` | 成员1 |
| 16 | 成员4 负载 | 前端 4 界面 + ASR + QA + TTS 调用，是关键路径上唯一单点 | P1 | 建议 QA Agent 后端逻辑划给成员1，成员4 只做前端 + ASR 接入 | 全员（见附录 B） |
| 17 | 探活 | 无健康检查接口，联调时不知道对方服务起没起 | P2 | 新增 `GET /api/v1/health` | 成员1 |

## A.3 字段变更汇总（相对草案）

| 变更 | 位置 | 类型 | 原因 | 影响模块 |
|---|---|---|---|---|
| 全部路径加 `/api/v1` | 7 个 API | 改名 | 约定与正文对齐 | 1,3,4 |
| 新增 `page_no` | vlm.json、story.json | 新增 | 排序 / 聚合 / 评测 | 2,3,5 |
| `question` 改条件必填 | `/qa` | 必填性 | 点读场景 | 4 |
| 新增 `input_type` | `/qa` | 新增 | 区分三个入口 | 4 |
| 新增 `tap` | `/qa` | 新增 | 点读目标 | 4 |
| 新增 `stages[]` | `/jobs` | 结构 | 三级状态模型 | 1,2,3 |
| 新增 `pages[].page_no` | `/jobs` | 新增 | 与文件契约对齐 | 1,4 |
| 新增 `force` | `/generate` | 新增 | 重生成 | 1,4 |
| 删除 `voice_id` | `/generate` | 删除 | 全局配置 | 1,4 |
| 删除 `story_id` | `/jobs` | 删除 | 与 page_id 1:1 冗余 | 1,3,4 |
| `story` → `story_url` | `/jobs` | 改类型 | 原结构未定义 | 1,4 |
| 新增 `safety` | `/qa` 响应 | 新增 | 与另外两层统一 | 4 |
| `image_prompt` 改可选 | story.json | 必填性 | v1 不消费 | 3 |
| TTS 路径改内容哈希 | 存储规范 | 规则 | 跨模块去重 | 3,4 |

<!-- pagebreak -->
# 附录 B · 五人分工

| 成员 | 负责模块 | 对外提供 | 依赖谁 | 最终交付 | 本周必须完成 |
|---|---|---|---|---|---|
| 成员1（队长） | Orchestrator、状态机、日志、所有 HTTP 路由 | A1 `/capture`、A2 `/generate`、A3 `/jobs`、A7 `/health` | 成员2 的 ocr/vlm 文件、成员3 的 story/video 文件 | 一键跑通的可执行编排 + `docs/API_v1.0.md` + 联调脚本 | 路由骨架 + mock 数据跑通 A1→A3 |
| 成员2 | PaddleOCR、Qwen2-VL | `json/{page_id}_ocr.json`、`json/{page_id}_vlm.json` | 中枢传图片路径 | 两个模型的封装函数（输入图片路径，输出符合契约的 dict）+ 准确率报告 | ocr.json 跑通真实图片；vlm.json 跑通真实图片 |
| 成员3 | Story Agent、TTS、视频合成 | `json/{page_id}_story.json`、`json/{page_id}_video.json`、A6 `/api/v1/tts` | 成员2 的 ocr/vlm 文件 | 故事生成 + TTS 服务 + ffmpeg 合成脚本 | TTS 服务先起（成员4 等着用）；story.json 用 mock 数据出结构 |
| 成员4 | 前端 4 界面、ASR、QA | A4 `/api/v1/asr`、A5 `/api/v1/qa` + 4 个页面 | 成员1 的 A1/A2/A3、成员3 的 A6 | 可演示的 Web 前端 + ASR/QA 服务 | 前端骨架接 mock；ASR 接口跑通；QA 用假 story 出答案 |
| 成员5 | 数据集、评测、指标 | 无对外接口 | 全员产物 | 测试绘本集（≥10 本 / ≥50 页）+ 评测脚本 + 实测报告 | 测试集就位；评测脚本能读 `json/` 下全部产物 |

**关键路径风险**：成员4 承担前端 4 界面 + ASR + QA + TTS 对接，是单点。建议把 **QA Agent 的后端逻辑（prompt 工程 + 上下文组织）划给成员1**，成员4 只做"前端 → `/qa` 的调用与展示"。此事需团队确认（见附录 D Q3）。

**接口冻结后各成员的改动权限**：只能新增可选字段。任何字段改名 / 改类型必须全员同意 + 全链路回归。

<!-- pagebreak -->
# 附录 C · 联调测试用例

| # | 场景 | 操作 | 预期结果 | 通过标准 |
|---|---|---|---|---|
| T01 | 正常拍照识别 | `POST /capture` 传真实绘本图 | `code:0`，返回 `page_id` + 正确 `image_width/height` | 文件落到 `uploads/`，尺寸与图片实际一致 |
| T02 | 正常全链路 | T01 后 `POST /generate`，轮询 `/jobs` | 2s 内 `queued→running`，≤300s 到 `done`，`video_url` 可播放 | 视频音画同步，旁白与画面页匹配 |
| T03 | OCR 失败但 VLM 成功 | 传一张纯图无字页 | 页面 `partial`，`degraded:["no_ocr"]`，video 仍产出 | 故事基于画面生成，不报 `failed` |
| T04 | VLM 失败但 OCR 成功 | 屏蔽 VLM 服务后跑 T02 | 页面 `partial`，`degraded:["no_scene"]` | 故事基于文字生成，视频正常 |
| T05 | OCR 与 VLM 全失败 | 两服务都停 | 页面 `failed`，任务 `failed`，`error.code` 非 0 | 前端有明确错误文案，不是白屏 |
| T06 | 故事生成失败 | 断开 LLM | 页面 `failed`，任务 `failed`，`error.code: 2001` | 日志有原始异常，页面 30s 内返回而非挂死 |
| T07 | TTS 失败 | 停 TTS 服务 | 页面 `partial`，`degraded:["no_audio"]`，`duration_source:"estimate"` | 视频静音但字幕时长正确 |
| T08 | 视频合成失败 | 改坏 ffmpeg 路径 | 页面 `partial`，`degraded:["no_video"]` | 返回 `story_url`，前端降级为图文翻页 |
| T09 | 点读问答 | `POST /qa` `input_type:"tap"`，`question:null`，带 `tap.object_id` | `code:0`，答案与物体相关，`citations[0].object_ids` 含该 object | 不返 1001；点"兔子"不会答"树" |
| T10 | 语音问答 | `POST /asr` 传录音 → 拿文本 → `POST /qa` | ASR 文本正确，QA 答案 + `audio_url` 可播 | 问答音频音色与视频旁白**一致** |
| T11 | 重复提交任务 | 连点两次 `POST /generate`（`force:false`） | 两次返回**同一** `job_id`，只产一份视频 | 视频文件修改时间只变一次 |
| T12 | 强制重新生成 | `POST /generate` 带 `force:true` | 旧 job → `cancelled`，新 `job_id`，文件覆盖 | 旧轮询返回 `cancelled`，前端切到新 job |
| T13 | 阶段超时 | 人为让 OCR 睡 35s | 30s 时该阶段 `failed`，重试 1 次后仍失败，页面按降级表处理 | 不卡死，日志有 `2002` |
| T14 | 参数缺失 | `POST /generate` 不带 `page_ids` | `code:1001`，`data:null` | msg 明确写出缺哪个参数 |
| T15 | 参数非法 | `page_id` 传 `book01-03` | `code:1002` | 不进入业务逻辑，不产生文件 |
| T16 | 资源不存在 | `GET /jobs/job_不存在` | `code:1003` | 不 500 |
| T17 | 安全拦截 | 构造触发词 | 页面 `blocked`，任务 `partial_failed` | 前端显兜底文案，不显示空白 |
| T18 | 健康检查 | `GET /health` | 全 `ok` | 任一模块停服务时对应字段为 `down` |

**联调顺序建议**：T14/T15/T16（参数层）→ T01（上传）→ T02（全链路）→ T09/T10（问答）→ T11/T12（幂等）→ T03~T08（降级）→ T17/T18（边界）。

<!-- pagebreak -->
# 附录 D · 待确认问题

以下问题不做猜测，需要团队当场拍板。**建议在冻结前一次会议全部定完**。

| # | 问题 | 影响 | 建议 | 截止 |
|---|---|---|---|---|
| Q1 | **v1 是"单页生成"还是"整本生成"？** 本文档按单页设计，`page_ids` 留了数组口子 | 决定 A2/A3 的数据结构与前端进度条 | 按单页做，整本放 v2。演示 2 分钟，单页足够 | 冻结前 |
| Q2 | **TTS 音色最终选型**（原文档写 11/6 前定） | 影响 `duration_sec`、视频时长、演示听感 | 先定一个女声，`TTS_VOICE_ID` 全局唯一，不许两处不同 | 11/6 |
| Q3 | **成员4 是否过载？QA Agent 后端归谁？** | 成员4 = 前端 4 界面 + ASR + QA，是单点 | 建议 QA 后端逻辑划给成员1，成员4 只做前端 + ASR | 冻结前 |
| Q4 | **视频分辨率** 1080×1920 还是 720×1280？ | 影响 render 耗时（可能从 180s 降到 60s） | 演示用 720×1280，稳 | 冻结前 |
| Q5 | **是否引入数据库？** 现在全是文件 | 影响 `/jobs` 重启后能否恢复 | v1 用文件 + 内存，重启丢 job 可接受；不引入 DB | 冻结前 |
| Q6 | **`history` 由前端传还是后端存？** | 影响多轮问答质量与实现量 | v1 前端传（≤10 轮），后端不存 | 冻结前 |
| Q7 | **模型 API 配额与成本上限** | 影响能否压测、能否反复跑全链路 | 定一个日调用上限，超了走 mock | 冻结前 |
| Q8 | **安全过滤 v1 是否真启用？** 还是只留字段恒 true | 影响演示能否出现"拦截"画面 | v1 字段与分支必须实现，开关默认关；演示时可手动开一次展示 | 冻结前 |
| Q9 | **部署形态**：单机一体化还是分服务？ | 影响 `ASSET_BASE_URL`、`/health` 探活、跨机文件共享 | 单机一体化（一台笔记本跑全部），最省事 | 冻结前 |
| Q10 | **是否需要 `POST /jobs/{id}/cancel`？** 本文档未列 | 用户点返回时需要 | 建议加，实现成本半小时；不加则前端只能等 | 冻结前 |
| Q11 | **`age_level` 只有 `3-6`/`6-9` 两档够不够？** | 影响故事语气 | 够，两档即可 | 冻结前 |
| Q12 | **无字绘本（OCR empty）是否纳入测试集？** | 影响 T03 能否复现 | 纳入 2 本，专门验降级 | 测试集定稿前 |

## 冻结前的最后三件事

1. 把本文档原样提交到 `docs/API_v1.0.md`，群里置顶，任何人改字段必须先改文档。
2. 成员3 先起 TTS 服务（成员4 等着用），成员1 先起 mock 路由（成员4 等着接），这两条是关键路径。
3. 全员过一遍 §1.3 错误码表，把自己模块会返回的码勾掉，**没勾的删掉**——错误码表留空号比留错号危害小。
