# 第三轮（v1.1.2）修复报告

| 项 | 内容 |
|---|---|
| 分支 | `wzy622-patch-1` |
| 版本 | v1.1.2（基于 v1.1.1） |
| 审查结论 | B（局部问题，修复后再次审查） |
| 本轮结论 | 审查报告的 4 项 P0 复查项 + 2 项 P1 风险全部处理；**106 / 106 测试通过** |
| 未改动 | `docs/API_v1.0.md`、公共 Schema、`main`、`dev` |
| 历史交付 | v1.1.0 / v1.1.1 包与报告原样保留 |

## 1. 审查意见逐条回应

| 审查意见 | 本轮处理 | 证据 |
|---|---|---|
| 独立 Video 仍未拒绝 `safety_pass=false` | `compose_video` 在契约校验后显式检查 `safety_pass is False` → 3004，且不产生 mp4/video.json | `test_video_rejects_story_with_safety_pass_false` |
| FFmpeg 缺失处理（核心已修复） | 保留三态 `UNAVAILABLE`；补充“静音 TTS / Video 先发布后深检”问题，改为**先验证临时产物再发布** | `test_silent_tts_validates_before_publish`、`test_video_validates_before_publish` |
| HTTP 错误响应读取无边界 | `HTTPError.read(400)` 限长读取，连接异常返回空串；错误体长度断言 | `test_http_error_body_read_is_bounded` |
| HTTP 容器格式未校验 | `AudioProbe` 增加 `format_name`；mp3 必须是 mp3 容器 + mp3 编码，wav 必须是 pcm_* + wav 容器 | `test_mp3_in_mp4_container_rejected` |
| HTTP 缓存验证有缺口 | 缓存改为**深检**（解码）+ 容器/编码与请求格式比对，不符即删除重建 | `test_cache_with_wrong_container_is_rebuilt` |
| 超时/临时文件清理不完整 | 静音 TTS 与 Video 改为“临时文件验证通过后才 `os.replace`/move”；失败只删临时文件 | 同上两条 publish-order 用例 |
| P1：失败清理可能删除旧有效音频 | 引擎失败路径**不再 unlink 目标文件**，只删自己的 `.part`；目标文件只在验证通过后替换 | `test_http_failure_keeps_existing_valid_audio` |
| P1：同内容并发共用临时路径 | TTS 临时名 = 进程 + 线程 + 随机 8 位；Video 临时目录同理；Windows 并发替换加退避重试 | `test_concurrent_same_text_shares_cache_safely` |
| Story 输入页身份检查不足 | 新增 `validate_input_doc`：`schema_version/page_id/page_no/book_id` 与请求页逐项比对，不符返 1002 | `test_story_rejects_mismatched_ocr_page`、`..._vlm_page_no` |
| Story 枚举兜底 | `normalize_status`：未知状态按 `failed` 处理（§1.2.6 default 分支），不误判成功 | `test_unknown_status_falls_back_to_failed` |

## 2. 关键实现细节

### 2.1 发布顺序（先验证，后发布）

```
TTS：写 .part → validate_audio(deep) → 通过才 os.replace → 返回
     失败：只删 .part，已存在的有效文件不动

Video：渲染到 tmp → validate_video(deep) → 通过才 move 到 videos/
       然后写 video.json；JSON 写失败则回收 mp4
```

### 2.2 HTTP 下载校验（完整链路）

1. 状态码必须 200；
2. `Content-Type` 白名单（audio/*、octet-stream），`text/html` 直接拒绝；
3. `Content-Length` 先验 + 读流按 `TTS_MAX_AUDIO_BYTES` 硬截断；
4. 落盘临时文件 → `validate_audio(deep=True)`：容器、编码、采样率、时长、解码；
5. `format_matches`：mp3 必须 `codec=mp3 & format_name 含 mp3`；wav 必须 `pcm_* & wav`；
6. 全部通过才替换为正式文件。

### 2.3 并发安全

- 临时文件：`{name}.{pid}.{tid}.{uuid8}.part`，同进程多线程不共用；
- Video 临时目录：`{page_id}_video_{pid}_{tid}_{uuid8}`；
- Windows `os.replace` 共享冲突：最多 6 次、递增退避重试。

## 3. 测试

```
106 passed in 15.15s
```

| 文件 | 用例 | 本轮变化 |
|---|---|---|
| `tests/test_regressions_v112.py` | 11 | **新增**（安全字段、输入身份、容器、缓存、发布顺序、并发、错误体） |
| `tests/test_http_audio.py` | 9 | — |
| `tests/test_safety_entrypoints.py` | 6 | — |
| `tests/test_story_schema_contract.py` | 5 | — |
| `tests/test_media.py` | 9 | — |
| `tests/test_story.py` | 16 | 用例数据改为完整 C1/C2 文档（配合身份校验） |
| `tests/test_tts.py` | 16 | — |
| `tests/test_schemas.py` | 13 | — |
| `tests/test_ids.py` | 9 | — |
| `tests/test_pipeline.py` | 5 | — |
| `tests/test_video.py` | 5 | — |
| `tests/test_tts_service.py` | 2 | — |

## 4. 独立运行验证

| 命令 | 结果 |
|---|---|
| `story --page-id book01_p03` | exit 0 |
| `tts --text "..."` | exit 0，code=0 |
| `video --page-id book01_p03` | exit 0，720x1280 |
| `run --page-id book01_p03` | status=done |

## 5. 修改文件清单（v1.1.1 → v1.1.2）

```
新增  tests/test_regressions_v112.py（11 例）
修改  agents/generation/tts/engine.py   唯一临时名、先验后发、错误体限长、容器校验、并发替换重试
修改  agents/generation/tts/client.py   缓存深检 + 容器/编码比对
修改  agents/generation/video.py        safety_pass=false 拒绝、先验后发、JSON 与 mp4 同发布、唯一临时目录
修改  agents/generation/story/builder.py 输入页身份校验、未知枚举按 failed
修改  agents/generation/media.py        AudioProbe.format_name
修改  README.md / PACKAGE.md / docs/CHANGELOG.md / docs/TEST_REPORT*
```

## 6. 已知限制

1. 未接真实 TTS / LLM（不调用付费 API），产物仍是静音 mock + 模板故事。
2. 安全词表为子串匹配，非语义审核。
3. `ffmpeg`/`ffprobe` 硬依赖：缺失时明确 2004，不发布未验证产物。
4. 单页 v1；多页、job 状态机、取消接口不在本模块范围。
5. 无 git commit/PR（仓库 404、本机无 git）。
6. 并发场景验证为线程级（4 线程同文本），未做多进程/多机压测。

## 7. 复现

```bash
pip install -r requirements.txt
export FFMPEG_PATH=/path/to/ffmpeg FFPROBE_PATH=/path/to/ffprobe

python -m pytest                       # 106 passed
export DATA_DIR=./_verify_data TTS_ENGINE=silent
python examples/install_example.py
python -m agents.generation run --page-id book01_p03
```
