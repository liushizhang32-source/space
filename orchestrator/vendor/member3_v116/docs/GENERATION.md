# 成员 3 · Story / TTS / Video 实现说明

对应契约：`docs/API_v1.0.md`（ZSZB-API-1.0 冻结版），C3 / C4 / A6，以及 §1.13 超时重试、§1.14 降级矩阵。

---

## 1. 契约映射

### 1.1 C3 `json/{page_id}_story.json`

| 字段 | 实现 |
|---|---|
| `schema_version` | 固定 `"1.0"` |
| `book_id` / `page_id` / `page_no` | 从 `page_id` 反解，三者一致性由模型校验 |
| `title` | LLM 给标题；mock 通道取首句或场景标签，≤80 字 |
| `age_level` | CLI/中枢传入，仅 `3-6` / `6-9`，其它值返 1002 |
| `segments[].segment_id` | `{page_id}_s{order:02d}`，order 从 1 连续 |
| `segments[].narration` | **强制 ≤120 字**（A6 上限），过长在标点处切分 |
| `segments[].scene` | LLM 输出，缺失时用 VLM `description` 兜底 |
| `segments[].duration_sec` | TTS 实测；TTS 失败时按 220 字/分钟估算 |
| `segments[].duration_source` | `tts` / `estimate`，与上一条严格对应 |
| `segments[].audio_url` | `duration_source=tts` 时必填（模型级校验） |
| `segments[].highlight_object_ids` | 只允许引用 vlm.json 里真实存在的 `object_id` |
| `total_duration_sec` | 分段之和，误差 >0.1s 直接判产物非法 |
| `safety_pass` / `safety_flags` | 开关默认关（Q8），开启且命中词表时该页判 blocked、不落盘 |
| `model` | `{"name": "mock-template"}` 或 `{"name": <LLM_MODEL>}`，用于区分 mock/真实 |
| `elapsed_ms` | 从进入 story 到落盘的真实耗时 |

### 1.2 C4 `json/{page_id}_video.json`

- 每段一张静帧，时长等于该段 `duration_sec`；`segments[]` 首尾相接，从 0 开始。
- `duration_sec` 用 ffprobe 实测；与分段之和偏差 >0.2s 时按比例缩放时间轴后重新校验。
- `resolution` 默认 `720x1280`（Q4 未拍板，取建议值；`VIDEO_RESOLUTION` 可改）。
- 合成失败（ffmpeg 报错、找不到原图、超时）→ 3007，**不写** `video.json`，页面 `partial + [no_video]`。

### 1.3 A6 `POST /api/v1/tts`

请求：

```json
{"text": "从前有只小兔子。", "voice_id": "female_warm", "speed": 0.95, "format": "mp3"}
```

成功：

```json
{"code": 0, "msg": "ok", "data": {"audio_url": "http://127.0.0.1:8000/audios/tts_9f2c1a4b7d3e.mp3", "duration_ms": 4091, "sample_rate": 24000}, "trace_id": "tr_01..."}
```

| 情况 | code | 说明 |
|---|---|---|
| `text` 缺失/空白 | 1001 | `data: null` |
| `text` >120 字 | 1002 | 提示当前字数 |
| `speed` 不在 0.5~2.0 | 1002 | |
| `format` 不是 mp3/wav | 1002 | |
| 引擎不可用（无 ffmpeg / 未配 TTS_HTTP_URL） | 2004 | 服务不可用 |
| 合成执行失败 | 3008 | 可重试（§1.13 白名单） |
| 进程超时 | 2002 | 可重试 |

HTTP 状态恒为 200，错误只体现在 `code`；请求体类型错误（如 `speed: "abc"`）由 422 转成 1002。

---

## 2. 状态与降级

`pipeline.run_page()` 的判定表（严格按 §1.7 三级状态）：

| OCR | VLM | 故事内容 | degraded | 页面状态 |
|---|---|---|---|---|
| ok | ok | 文字 + 画面 | `[]` | done |
| empty（无字书） | ok | 纯画面 | `[]` | done |
| failed | ok | 画面描述 + 物体 | `[no_ocr]` | partial |
| ok | failed | 只用文字 | `[no_scene]` | partial |
| failed/empty | failed | — | — | failed（3001） |
| ok/empty | ok | TTS 全失败 | `[no_audio]`，`duration_source=estimate` | partial（视频仍产出，静音+字幕） |
| ok/empty | ok | 视频失败 | `[no_video]`，返回 story_url | partial |
| 任一层安全拦截 | — | 不产出 | — | blocked（3004） |

多次重试仍失败 → 抛对应 `AppError`，不吞异常；CLI 以非 0 退出码结束。

---

## 3. 关键实现决策

1. **TTS 缓存键**：`sha1(f"{text}|{voice_id}|{speed:.2f}")[:12]`，文件名 `tts_{key}.{fmt}`。
   文本原样（不 strip/不改标点），保证视频与问答复用同一份音频。命中缓存不重新合成。
2. **时长来源**：`duration_source` 只在 ffprobe 真正量到时写 `tts`；量不到（无 ffprobe）写 `estimate`。
3. **字幕**：Pillow 预渲染透明 PNG（圆角半透明底 + 白字，最多 4 行），再 overlay 到画面底部。
   比 `drawtext` 稳：中文、换行、Windows 盘符冒号都不会把 filtergraph 弄坏；渲染失败自动退回无字幕。
4. **原子写**：JSON 先写 `.tmp` 再 `os.replace`；音频/视频同样先写 `.part` 再替换，避免中枢读到半个文件。
5. **URL 策略**：JSON 里的 `audio_url` / `video_url` 写**绝对 URL**（`ASSET_BASE_URL` + 相对路径），
   因为成员 5 直接读 `json/` 做评测；存储层只保存相对位置。换机器只改 `ASSET_BASE_URL`。
6. **重试**：Story 1 次（退避 2s），Video 1 次（退避 2s，§1.13 表里写 5s，用 `MAX_RETRY`/退避可在 env 调）；
   TTS 单段 20s 超时。1xxx / 3003 / 3004 不重试。
7. **未知字段**：Pydantic 全部 `extra="allow"`，导出 Schema 的 `additionalProperties=true`，
   符合"只许新增可选字段、消费方忽略未知字段"。

---

## 4. Mock / 真实 切换

| 能力 | mock（默认） | 真实 |
|---|---|---|
| 故事 | 模板拼接，`model.name="mock-template"` | 配 `LLM_BASE_URL` + `LLM_API_KEY` + `LLM_MODEL` |
| TTS | `TTS_ENGINE=silent`，等长静音 mp3 | `TTS_ENGINE=http` + `TTS_HTTP_URL`（返回音频字节或 base64 JSON） |
| 视频 | 真实 ffmpeg 合成，但音轨是静音 | 同左，换成真实配音即可 |

HTTP TTS 协议（本模块约定，供成员 3 接自建服务）：

```
POST TTS_HTTP_URL
{"text": "...", "voice_id": "female_warm", "speed": 1.0, "format": "mp3"}
→ 200 audio/mpeg（二进制）
或 200 application/json {"audio_base64": "...", "sample_rate": 24000}
```

---

## 5. 与联调用例的对应

| 用例 | 本模块行为 |
|---|---|
| T02 正常全链路 | `run_page` → done，mp4 可播放 |
| T03 OCR 失败 VLM 成功 | `partial + [no_ocr]`，故事基于画面 |
| T04 VLM 失败 OCR 成功 | `partial + [no_scene]` |
| T05 两者都失败 | failed，error.code=3001，不产出 story.json |
| T06 故事生成失败 | 2001（LLM 配了但失败且未开兜底） |
| T07 TTS 失败 | `partial + [no_audio]`，`duration_source=estimate`，静音+字幕 |
| T08 视频失败 | `partial + [no_video]`，仍返回 `story_url` |
| T13 阶段超时 | 子进程超时 → 2002，按降级表处理，不挂死 |
| T17 安全拦截 | blocked，不产出 |

---

## 6. 测试

```
pytest        # 74 passed
```

| 文件 | 覆盖 |
|---|---|
| `tests/test_ids.py` | page_id/segment_id/ULID/内容哈希 |
| `tests/test_schemas.py` | C3/C4 契约、未知字段、必填联动、时间轴连续性 |
| `tests/test_story.py` | 四种输入组合、长文本切分、TTS 失败降级、安全拦截 |
| `tests/test_tts.py` | 1001/1002/2004/3008、缓存命中、A6 响应体 |
| `tests/test_video.py` | 端到端编码、静音视频、缺图、重试次数、失败不落盘 |
| `tests/test_pipeline.py` | done / partial / failed 三种页面状态 |

需要 ffmpeg 的用例会在检测不到 ffmpeg 时 `skip`。

---

## 7. 待确认

1. **Q4 分辨率**：默认 720×1280（建议值），C4 示例是 1080×1920，需群里拍板。
2. **Q10 取消接口**：正文没有，未实现。
3. **C3 `scene` 是否必填**：字段表未列、示例有；本模块始终输出。
4. **TTS 真引擎选型**（Q2）：`TTS_VOICE_ID` 已统一，但具体引擎/服务还没定，`http` 只定了传输协议。
5. **Job 级重试与并发**：`MAX_CONCURRENT_JOBS`、job 总超时由成员 1 实现，本模块不重复做。
