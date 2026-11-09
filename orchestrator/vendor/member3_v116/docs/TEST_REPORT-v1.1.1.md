# 第二轮审查修复报告 · v1.1.1

| 项 | 内容 |
|---|---|
| 分支 | `wzy622-patch-1` |
| 版本 | v1.1.1（基于 v1.1.0） |
| 审查结论 | B（局部问题，第三轮修复后申请独立运行测试） |
| 本轮结论 | 安全 4 项 + Story 结构 4 项全部处理；**95 / 95 测试通过**；独立调用 TTS/Video 无法绕过安全检查 |
| 未改动 | `docs/API_v1.0.md`、公共 Schema、`main`、`dev` |
| 历史交付 | v1.1.0 包与报告原样保留（`TEST_REPORT-v1.1.0.md`、`dist/...v1.1.0.zip`） |

## 1. 环境

| 项 | 值 |
|---|---|
| OS | Windows 11（workspace-write 沙箱） |
| Python | 3.12.14 |
| ffmpeg / ffprobe | 9.0.2 |
| pydantic / fastapi / uvicorn | 2.14.2 / 0.162.0 / 0.54.0 |
| pytest | 9.2.0 |
| 模型调用 | 无（未使用任何付费 API） |

## 2. 安全修复

### 2.1 统一 Story / TTS / Video 的安全检查入口

- **问题**：安全逻辑只在 Story 生成路径里；单独调 A6 或 `video` 子命令可以绕过。
- **修法**：`agents/generation/safety.py` 提供三个统一入口，三条路径都接上：
  - `ensure_safe(texts, settings, stage)`：底层词表检查；
  - `guard_text(text, settings, stage)`：TTS 单段文本（A6 / CLI / 进程内）；
  - `ensure_story_safe(story, settings, stage)`：Video 消费整份 story.json。
- **接入点**：
  - Story：输入 / 生成草稿 / 落盘前三道闸；
  - `TTSClient.synthesize()`：合成前先过 `guard_text`（A6 路由同样经过它）；
  - `compose_video()`：契约校验后、渲染前过 `ensure_story_safe`。
- **验证**：`tests/test_safety_entrypoints.py`（6 例）
  TTS 客户端拦截/放行、A6 路由返回 `code=3004`、Video 入口拦截且不产生 mp4/video.json、
  Video 拒绝越页 highlight、拒绝 page_id 不一致。

### 2.2 FFmpeg 不存在时不得判定为“解码成功”

- **问题**：`_decode_ok()` 在找不到 ffmpeg 时返回 `True`，等于把未验证文件当合格产物。
- **修法**：`media` 改为三态 `MediaStatus.OK / INVALID / UNAVAILABLE`：
  `_decode_ok()` 返回 `bool | None`；`validate_audio/video(deep=True)` 缺 ffmpeg 时返回 `UNAVAILABLE`；
  TTS 映射为 `2004`（不返回 `audio_url`）；Video 映射为 `2004` 并删除已生成 mp4、不写 `video.json`。
- **验证**：`test_deep_audio_check_is_unavailable_without_ffmpeg`、
  `test_deep_video_check_is_unavailable_without_ffmpeg`、`test_tts_without_ffmpeg_returns_2004`、
  `test_video_without_ffmpeg_fails`。

### 2.3 HTTP 音频下载校验

- **修法**：`HttpEngine` 强制校验：
  1. HTTP 状态必须 200；
  2. `Content-Type` 必须在 `audio/*`、`application/octet-stream`、`binary/octet-stream` 白名单内，
     `text/html` 直接判“不是音频”；
  3. `Content-Length` 先验，读流再按 `TTS_MAX_AUDIO_BYTES`（默认 10 MB）硬截断；
  4. 落盘后 `validate_audio(deep=True)` 验证真实编码、时长、可解码；
  5. 请求 `mp3` 实际 `wav`（或反之）判“格式不匹配”。
- **验证**：`tests/test_http_audio.py`（9 例）。

### 2.4 超时 / 解码失败必须清理临时文件

- **修法**：`.part` 写入与替换包在 `try/except`，任何异常都删除临时文件与目标文件，成功才 `os.replace`；
  `_render_once` 的 `finally` 清理整个临时目录。
- **验证**：`test_http_timeout_cleans_up`、`test_http_garbage_audio_cleans_temp`
  断言无 `*.part` / `*.tmp`、无半成品。

## 3. Story 数据结构修复

1. **模型 ↔ Schema ↔ 契约一致性**：新增 `tests/test_story_schema_contract.py`（5 例）：
   导出 schema 与 `docs/schemas/story.schema.json` 内容相等；顶层/分段 properties 与 C3 字段集合相等；
   required 与 C3 必填集合相等；`schema_version` const 1.0；`additionalProperties: true`。
   同时重新导出了 `docs/schemas/{story,video}.schema.json`。
2. **highlight 页面归属**：`StoryDoc` 校验每个 `highlight_object_ids` 以 `{page_id}_o` 开头；
   用例 `test_highlight_object_must_belong_to_page`、`test_video_entry_rejects_foreign_highlight`。
3. **不改公共 API / Schema**：只改本模块自有模型，未动 `orchestrator/schemas/` 与 `docs/API_v1.0.md`。

## 4. 测试统计

```
95 passed in 12.54s
```

| 文件 | 用例 | 本轮变化 |
|---|---|---|
| `tests/test_http_audio.py` | 9 | **新增** |
| `tests/test_safety_entrypoints.py` | 6 | **新增** |
| `tests/test_story_schema_contract.py` | 5 | **新增** |
| `tests/test_media.py` | 9 | +4（ffmpeg 缺失三态、TTS/Video 2004） |
| `tests/test_tts.py` | 16 | -3（HTTP 用例迁到新文件） |
| `tests/test_ids.py` | 9 | — |
| `tests/test_schemas.py` | 13 | — |
| `tests/test_story.py` | 16 | — |
| `tests/test_pipeline.py` | 5 | — |
| `tests/test_video.py` | 5 | — |
| `tests/test_tts_service.py` | 2 | — |

净增 **21** 例（74 → 95）。

## 5. 独立入口验证

| 场景 | 调用 | 结果 |
|---|---|---|
| Story | `story --page-id book01_p03` | exit 0 |
| TTS | `tts --text "验证 v1.1.1。"` | exit 0，`code=0` |
| Video | `video --page-id book01_p03` | exit 0，`720x1280` |
| 全链路 | `run --page-id book01_p03` | `status=done` |
| TTS 不安全文本 | `synthesize("…打架…")` | `3004`，不落盘 |
| Video 不安全 story | `compose_video(...)` | `3004`，无 mp4/video.json |
| 无 ffmpeg | TTS / Video | `2004` / 失败，不发布未验证文件 |

## 6. 产物有效性证据

- `artifacts/tts/probe.txt`：mp3 / 24000 Hz / mono / 4.09s
- `artifacts/video/probe.txt`：h264 720x1280 + aac 44100Hz / 7.67s
- `artifacts/story/schema_check.txt`：StoryDoc 通过、scene 非空
- `artifacts/manifest.json`：v1.1.1、文件 sha256、mock 标注

## 7. 修改文件清单（v1.1.0 → v1.1.1）

```
新增  tests/test_http_audio.py
新增  tests/test_safety_entrypoints.py
新增  tests/test_story_schema_contract.py
新增  docs/CHANGELOG.md
保留  docs/TEST_REPORT-v1.1.0.md
修改  agents/generation/config.py        tts_max_audio_bytes
修改  agents/generation/media.py         三态校验 MediaStatus/validate_audio/validate_video
修改  agents/generation/safety.py        guard_text / ensure_story_safe
修改  agents/generation/tts/engine.py    下载校验、临时文件清理、三态
修改  agents/generation/tts/client.py    TTS 入口安全检查、缓存 UNAVAILABLE 拒绝
修改  agents/generation/video.py         入口契约+安全检查、validate_video 三态
修改  agents/generation/schemas.py       highlight 页面归属校验
修改  .env.example                        TTS_MAX_AUDIO_BYTES
修改  docs/schemas/{story,video}.schema.json（重新导出）
修改  tests/test_media.py / tests/test_tts.py
```

## 8. 已知限制

1. 真实 TTS 未接入（不调用付费服务），音频为静音 mock；HTTP 下载校验已就绪。
2. 真实 LLM 未接入，故事为 `mock-template`。
3. 安全词表是子串匹配，不是语义审核；生产需替换为审核服务（分支已就绪）。
4. `ffprobe` 是硬依赖：缺失时 TTS 2004、视频 `no_video`（有意为之：无法验证就不发布）。
5. 无 git commit/PR（仓库 404、本机无 git），`wzy622-patch-1` 为交付标识。
6. 单页 v1；多页/整本、任务状态机、取消接口不在本模块范围。

## 9. 复现

```bash
pip install -r requirements.txt
export FFMPEG_PATH=/path/to/ffmpeg FFPROBE_PATH=/path/to/ffprobe

python -m pytest                       # 95 passed
export DATA_DIR=./_verify_data TTS_ENGINE=silent
python examples/install_example.py
python -m agents.generation story --page-id book01_p03
python -m agents.generation tts   --text "从前有只小兔子，住在森林边上。"
python -m agents.generation video --page-id book01_p03
python -m agents.generation run   --page-id book01_p03
```
