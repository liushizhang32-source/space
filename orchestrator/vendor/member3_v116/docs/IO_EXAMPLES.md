# 模块输入输出示例

三个模块可以**分别独立运行**，互不依赖进程状态，只通过 `DATA_DIR` 下的文件衔接。

| 模块 | 命令 | 输入 | 输出 | 依赖 |
|---|---|---|---|---|
| Story | `python -m agents.generation story` | `json/{page_id}_ocr.json`、`json/{page_id}_vlm.json` | `json/{page_id}_story.json` + 音频 | ffmpeg + ffprobe（silent 引擎）或 `TTS_HTTP_URL` |
| TTS（A6） | `python -m agents.generation tts` / `serve` | HTTP JSON 或 CLI `--text` | `audios/tts_{hash}.mp3` + 响应 JSON | ffmpeg + ffprobe 或 `TTS_HTTP_URL` |
| Video | `python -m agents.generation video` | `json/{page_id}_story.json` + `uploads/{page_id}_orig.*` | `videos/{page_id}_video.mp4` + `json/{page_id}_video.json` | ffmpeg + ffprobe |

真实样例文件在 `artifacts/`，见 `artifacts/README.md`。

---

## 1. Story 模块

### 输入（C1 / C2）

`json/book01_p03_ocr.json`：

```json
{
  "schema_version": "1.0",
  "book_id": "book01",
  "page_id": "book01_p03",
  "page_no": 3,
  "status": "ok",
  "image_width": 900,
  "image_height": 1200,
  "text_blocks": [
    {"block_id": "book01_p03_t01", "order": 1, "text": "从前有只小兔子，住在森林边上。", "bbox": [90, 940, 800, 990], "confidence": 0.97}
  ],
  "page_confidence": 0.97,
  "elapsed_ms": 1830
}
```

`json/book01_p03_vlm.json`：

```json
{
  "schema_version": "1.0",
  "book_id": "book01",
  "page_id": "book01_p03",
  "page_no": 3,
  "status": "ok",
  "image_width": 900,
  "image_height": 1200,
  "description": "夜晚的森林，一只小兔子站在树下，月光洒在树梢。",
  "objects": [
    {"object_id": "book01_p03_o01", "label": "兔子", "bbox": [420, 620, 620, 900], "confidence": 0.92}
  ],
  "scene_tags": ["夜晚", "森林"],
  "safety": {"pass": true, "flags": []},
  "elapsed_ms": 2100
}
```

### 命令

```bash
python -m agents.generation story --page-id book01_p03 --age-level 3-6
```

### 输出（C3，节选）

```json
{
  "schema_version": "1.0",
  "book_id": "book01",
  "page_id": "book01_p03",
  "page_no": 3,
  "title": "从前有只小兔子，住在森林边上",
  "age_level": "3-6",
  "status": "ok",
  "segments": [
    {
      "segment_id": "book01_p03_s01",
      "order": 1,
      "narration": "从前有只小兔子，住在森林边上。",
      "scene": "夜晚的森林，一只小兔子站在树下，月光洒在树梢。",
      "duration_sec": 4.091,
      "duration_source": "tts",
      "audio_url": "http://127.0.0.1:8000/audios/tts_2e36d97e5cd9.mp3",
      "highlight_object_ids": ["book01_p03_o01"]
    }
  ],
  "total_duration_sec": 7.636,
  "safety_pass": true,
  "safety_flags": [],
  "model": {"name": "mock-template", "version": "1.0"},
  "elapsed_ms": 145
}
```

### 降级输出（OCR 失败、VLM 正常）

`degraded = ["no_ocr"]`，`scene` 仍非空（用画面描述兜底），`status` 仍为 `ok`，
页面状态由流水线聚合为 `partial`。

---

## 2. TTS 模块（A6）

### HTTP 请求

```http
POST /api/v1/tts
Content-Type: application/json

{"text": "从前有只小兔子，住在森林边上。", "voice_id": "female_warm", "speed": 1.0, "format": "mp3"}
```

### HTTP 响应

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "audio_url": "http://127.0.0.1:8000/audios/tts_2e36d97e5cd9.mp3",
    "duration_ms": 4091,
    "sample_rate": 24000
  },
  "trace_id": "tr_01M6TNKJ7NPA3CPE0BB46N8PMR"
}
```

CLI 等价：

```bash
python -m agents.generation tts --text "从前有只小兔子，住在森林边上。"
```

### 失败示例

| 输入 | HTTP | 响应 |
|---|---|---|
| `{}` | 200 | `{"code": 1001, "msg": "缺少参数 text", "data": null}` |
| `{"text": "字"*200}` | 200 | `{"code": 1002, "msg": "text 超过 120 字（当前 200 字）"}` |
| TTS 服务返回垃圾字节 | 200 | `{"code": 3008, "msg": "TTS 返回的音频不可用（文件不存在/格式不支持/无法解码）"}` |
| ffmpeg 缺失 | 200 | `{"code": 2004, "msg": "ffmpeg 不可用，无法生成 mock 音频"}` |

### 产物

`audios/tts_{sha1_12}.mp3`，内容哈希命名；真实文件见 `artifacts/tts/tts_sample.mp3`。

---

## 3. Video 模块

### 输入

- `json/book01_p03_story.json`（上一步产物）
- `uploads/book01_p03_orig.png`（书页原图）

### 命令

```bash
python -m agents.generation video --page-id book01_p03
```

### 输出（C4）

```json
{
  "schema_version": "1.0",
  "book_id": "book01",
  "page_id": "book01_p03",
  "page_no": 3,
  "status": "ok",
  "video_url": "http://127.0.0.1:8000/videos/book01_p03_video.mp4",
  "duration_sec": 7.636,
  "resolution": "720x1280",
  "fps": 25,
  "segments": [
    {"segment_id": "book01_p03_s01", "start_sec": 0.0, "end_sec": 4.091},
    {"segment_id": "book01_p03_s02", "start_sec": 4.091, "end_sec": 7.636}
  ],
  "elapsed_ms": 816
}
```

### 降级

| 故障 | 结果 |
|---|---|
| 找不到原图 | `VideoError(3007)`，不写 `video.json` |
| ffmpeg 失败 | 重试 1 次后 `3007`，不写 `video.json` |
| 输出 mp4 无法解码 | `3007`，删除坏文件，不写 `video.json` |
| TTS 无音频（story 里没有 `audio_url`） | 视频照出，静音 + 字幕 |
