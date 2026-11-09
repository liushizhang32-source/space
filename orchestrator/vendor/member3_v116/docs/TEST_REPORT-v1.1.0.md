# 第一轮审查修复报告 · v1.1.0

| 项 | 内容 |
|---|---|
| 分支 | `wzy622-patch-1` |
| 版本 | v1.1.0（基于第一轮交付 v1.0.0） |
| 审查结论 | B（修复后进入独立运行测试） |
| 本轮结论 | 4 项问题全部修复；**74 / 74 测试通过**；Story / TTS / Video 均可独立运行 |
| 未改动 | `docs/API_v1.0.md`、公共 Schema、`dev`、`main`、`feat/generation` |

## 1. 环境

| 项 | 值 |
|---|---|
| OS | Windows 11（沙箱 workspace-write） |
| Python | 3.12.14 |
| ffmpeg / ffprobe | 9.0.2 |
| pydantic / fastapi / uvicorn | 2.14.2 / 0.162.0 / 0.54.0 |
| pytest | 9.2.0 |
| 模型调用 | **无**（未使用任何付费 API；LLM 未配置，TTS 为 silent） |

## 2. 修复清单

### 2.1 TTS 异常处理器 JSONResponse 参数位置错误（P0）

- **现象**：请求体类型错误时接口会抛 `TypeError` / 返回 500，违反“HTTP 恒 200”。
- **根因**：`tts/service.py` 写成 `JSONResponse(200, fail(...))`，第一个位置参数是 `content`，
  结果 `content=200`、`status_code=<dict>`。
- **修法**：改为关键字 `status_code=200, content=...`；两个 handler 提为模块级
  `handle_validation_error` / `handle_unexpected`，可直接单测。
- **验证**：`tests/test_tts_service.py`
  - `test_validation_error_returns_http_200_and_code_1002`
  - `test_unhandled_error_returns_http_200_and_code_9001`

### 2.2 降级路径产生空 scene（P1）

- **根因**：`scene = segment.scene or state.description`，VLM 失败且无描述时落到空串；
  旧模型允许 `scene=""`，不合格产物能落盘。
- **修法**：
  1. 新增 `fallback_scene()` 五级兜底：VLM 描述 → 物体标签 → 场景标签 → 旁白摘录 → `"书页画面。"`；
  2. `StorySegment.scene` 改为 `min_length=1` + strip 校验，空 scene 直接判契约不合法。
- **验证**：
  - `test_scene_filled_when_vlm_failed`
  - `test_scene_filled_when_vlm_has_no_description`
  - `test_empty_scene_is_rejected`（Schema 层）

### 2.3 生成后安全检查（P1）

- **根因**：只在输入侧查词表；LLM/模板生成的 title、narration、scene 没有复检就落盘。
- **修法**：新增 `agents/generation/safety.py`，三道闸：
  1. 上游输入（OCR 文本 + 画面描述）；
  2. 生成草稿（title + 每段 narration/scene）；
  3. 产物落盘前（整份 story.json 的所有展示文本）。
  命中即 3004，**不写 story.json**；上游 `vlm.safety.pass=false` 仍然无条件拦截。
- **验证**：`test_post_generation_safety_blocks_unsafe_story`
  （monkeypatch 让生成器产出含违禁词的草稿，确认 3004 且文件不存在）

### 2.4 HTTP 音频有效性检查（P1）

- **根因**：只尝试用 ffprobe 取时长，取不到就退化成 `estimate`，坏字节也会带着 `audio_url` 返回。
- **修法**：
  1. 新增 `media.probe_audio()`：文件存在且非空 → 有音频流 → 编码在允许集合 → 时长 > 0 →
     `deep=True` 时用 ffmpeg 真解码一遍；
  2. `HttpEngine`：落盘后**深检**，失败删文件并返回 3008；
  3. 缓存命中：**浅检**，损坏（0 字节 / 截断 / 文本冒充）直接删除并重新合成；
  4. `SilentEngine` 产物也过同一套校验；
  5. 视频同理：`probe_video(deep=True)` 失败删 mp4、不写 `video.json`、返回 3007。
- **验证**：
  - `test_http_engine_rejects_undecodable_audio`
  - `test_http_engine_accepts_valid_audio`
  - `test_corrupted_cache_is_regenerated`
  - `test_probe_audio_accepts_generated_mp3` / `rejects_text_file` / `rejects_empty_file` / `rejects_missing_file`
  - `test_probe_video_rejects_non_video`
  - `test_compose_video_end_to_end`（新增最终 mp4 深检断言）

## 3. 测试统计

```
74 passed in 10.14s
```

| 文件 | 用例数 | 说明 |
|---|---|---|
| `tests/test_ids.py` | 9 | ID / ULID / 内容哈希 |
| `tests/test_schemas.py` | 13 | C3/C4 契约（含空 scene 拒绝） |
| `tests/test_story.py` | 16 | 四种输入组合、切分、TTS 降级、安全（输入/生成后） |
| `tests/test_tts.py` | 19 | 校验、缓存、HTTP 音频、损坏缓存、A6 响应 |
| `tests/test_tts_service.py` | 2 | **新增**：异常处理器 HTTP 200 |
| `tests/test_media.py` | 5 | **新增**：音频/视频探测与拒绝坏文件 |
| `tests/test_video.py` | 5 | 合成、静音、重试、失败不落盘、产物深检 |
| `tests/test_pipeline.py` | 5 | done / partial / failed 聚合 |

## 4. 独立运行验证

四个命令分别在干净 `DATA_DIR` 下执行，均 exit 0：

| 命令 | 结果 |
|---|---|
| `story --page-id book01_p03 --age-level 3-6` | 生成 `json/book01_p03_story.json` + 音频 |
| `tts --text "从前有只小兔子，住在森林边上。"` | 生成 `audios/tts_2e36d97e5cd9.mp3`，响应 code=0 |
| `video --page-id book01_p03` | 生成 `videos/book01_p03_video.mp4` + `json/book01_p03_video.json` |
| `run --page-id book01_p03 --age-level 3-6` | `status=done`，degraded=`[]` |

原始 stdout 见 `artifacts/*/cli_stdout.json`。

## 5. 产物有效性证据

TTS（`artifacts/tts/probe.txt`）：

```
Stream #0:0: Audio: mp3 (mp3float), 24000 Hz, mono, fltp, 48 kb/s
Duration: 00:00:04.09
```

Video（`artifacts/video/probe.txt`）：

```
Stream #0:0: Video: h264 (High), yuv420p, 720x1280, 24.96 fps
Stream #0:1: Audio: aac (LC), 44100 Hz, mono
Duration: 00:00:07.67
```

Story Schema 校验（`artifacts/story/schema_check.txt`）：

```
StoryDoc 校验通过
page_id=book01_p03 segments=2 total_duration_sec=7.636 model=mock-template
scene 非空=True
```

## 6. 改动文件

```
新增  agents/generation/safety.py
新增  tests/test_media.py
新增  tests/test_tts_service.py
修改  agents/generation/tts/service.py      异常处理器（参数位置 + 模块级函数）
修改  agents/generation/tts/engine.py       音频落盘后深检；禁止静默降级
修改  agents/generation/tts/client.py       缓存浅检、损坏即重建
修改  agents/generation/story/builder.py    scene 兜底、生成后/落盘前安全检查
修改  agents/generation/schemas.py          scene 非空校验
修改  agents/generation/media.py            probe_audio / probe_video
修改  agents/generation/video.py            最终 mp4 深检
修改  tests/test_story.py, test_schemas.py, test_tts.py, test_video.py
```

## 7. 未覆盖 / 已知限制

1. **未接真实 TTS**：按要求不调用付费服务，音频为 `silent` 静音；真实引擎只需 `TTS_ENGINE=http` + `TTS_HTTP_URL`。
2. **未接 LLM**：故事为 `mock-template`；`model.name` 可区分。
3. **ffprobe 是硬依赖**：音频/视频有效性校验需要 ffprobe；缺失时 TTS 返回 2004、视频降级 `no_video`。
4. **git**：本机无 git 客户端，仓库 404，未产生真实 commit；`wzy622-patch-1` 仅作为本轮交付标识，
   合并时按 `PACKAGE.md` 里的分支说明操作。
5. Windows 沙箱下 pytest 自带 `tmpdir` 清理会误报权限错误，`tests/conftest.py` 用自建 `tmp_path` 规避，
   不影响用例语义。

## 8. 复现

```bash
pip install -r requirements.txt
export FFMPEG_PATH=/path/to/ffmpeg FFPROBE_PATH=/path/to/ffprobe

python -m pytest                 # 74 passed
python examples/install_example.py
export DATA_DIR=./_verify_data TTS_ENGINE=silent
python -m agents.generation story --page-id book01_p03
python -m agents.generation tts   --text "从前有只小兔子，住在森林边上。"
python -m agents.generation video --page-id book01_p03
python -m agents.generation run   --page-id book01_p03
```
