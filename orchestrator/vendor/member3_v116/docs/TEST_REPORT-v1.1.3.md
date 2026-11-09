# 第四轮（v1.1.3）修复报告

| 项 | 内容 |
|---|---|
| 分支 | `wzy622-patch-1` |
| 版本 | v1.1.3（基于 v1.1.2） |
| 审查结论 | B（4 项阻塞，修复后再审） |
| 本轮结论 | R112-01～R112-04 全部处理；**123 / 123 测试通过**（解压复验） |
| 未改动 | `docs/API_v1.0.md`、公共 Pydantic Schema、`main`、`dev` |
| 历史交付 | v1.1.0 / v1.1.1 / v1.1.2 包与报告原样保留 |

## 1. R112-01｜最终 scene 安全复查晚于 TTS（P0）

- **修法**：`build_page_story` 先生成全部最终文本（`title` + 每段 `narration` + **兜底后的最终 `scene`**），
  统一过 `ensure_safe`，**之后**才调用 TTS；`fallback_scene` 不再发生在 TTS 之后。
- **安全错误不被吞**：TTS 阶段抛出的 `3004` 直接向上传播；不再落入 `except` 被记成 `no_audio`。
- **pipeline**：视频阶段 `3004` 返回 `status=blocked` 并保留 error，不再降级成 `no_video`。
- 测试（新增）：
  - `test_fallback_scene_safety_blocks_before_tts`：旁白干净、兜底 scene 命中词表 →
    `3004`、TTS 调用次数 0、无音频、无 story.json；
  - `test_tts_safety_error_propagates_not_degraded`：TTS 抛 3004 不被降级；
  - `test_pipeline_video_safety_is_blocked`：视频 3004 → `blocked`。

## 2. R112-02｜Video 发布不是 MP4/JSON 事务（P1，历史 P0-4 残留）

- **修法**：新增 `_publish_pair()`：
  1. 唯一临时名（pid + tid + uuid8）写 staged MP4 与 JSON 临时文件；
  2. 页级锁（`_page_lock(page_id)`）内成对替换；
  3. 替换前把旧 MP4/JSON 移到 `.bak`，任一步失败按相反顺序恢复旧版本；
  4. `finally` 清理本轮 staged / backup / json tmp。
- 测试（新增）：
  - `test_video_json_publish_failure_restores_old_pair`：第 4 次替换失败 → 旧 MP4/旧 JSON 字节不变、无残留；
  - `test_video_failure_without_old_pair_leaves_nothing`：无旧产物时失败 → 不产生 mp4/json；
  - `test_video_missing_audio_file_raises`：story 声明 audio_url 但文件缺失 → 报错，不再静默静音。

## 3. R112-03｜HTTP JSON/base64/类型边界（P1）

- **修法**：
  - 先按 `Content-Type` 判定：`text/html` 即使 body 是 JSON 也拒绝；
  - JSON 必须是 dict；`audio_base64` 必须是非空字符串；
  - `base64.b64decode(..., validate=True)`，`binascii.Error/ValueError` 统一转 `3008`；
  - `sample_rate` 非法时忽略而不崩溃；
  - wav 只接受 `format_name == wav`（不再允许 w64），空容器集合直接判不匹配；
  - `HTTPError` 句柄读取 400 字节后关闭；`URLError.reason` 为超时时映射 `2002`。
- 测试（新增）：JSON 数组、缺 `audio_base64`、坏 base64、`text/html` 包 JSON、w64/空容器、
  `URLError(timeout)` → 2002。

## 4. R112-04｜Story 自有模型与公共 StoryData 差异（P1）

- **修法**（只改成员自有模型与导出物，不动公共 Schema）：
  - `StoryDoc.status` 只允许 `"ok"`；失败状态只存在于内部结果；
  - `highlight_object_ids` 默认 `[]`、显式 `null` 直接拒绝；
  - `safety_flags` 默认 `[]`；
  - ID 校验改为完整格式 `^{page_id}_s\d{2}$` / `^{page_id}_o\d{2}$`，
    `book01_p03_oBAD_o01` 这类“前缀对、格式错”的值会被拒绝；
  - 生成器每段始终输出 `highlight_object_ids`（无高亮写 `[]`）。
- 测试（新增）：`status=failed` 拒绝、highlight null 拒绝、畸形 object_id 拒绝、
  省略可选字段时默认 `[]`、VideoDoc `status=failed` 拒绝。

## 5. P2 同步改进（不阻塞，但本轮顺手做）

- `.env` 现在真的会被 CLI 加载（`load_dotenv`，仅补齐未设置的环境变量）。
- TTS 独立服务挂载 `/audios` 静态目录，返回的 audio_url 在 8001 端口可直接访问。
- 媒体深检启用 `ffmpeg -xerror`，坏帧更早失败。
- 测试临时目录在用例结束后清理。

## 6. 测试

```
123 passed in 17.79s（解压包内复验同结果）
```

| 文件 | 用例 | 本轮变化 |
|---|---|---|
| `tests/test_regressions_v113.py` | 17 | **新增** |
| 其余 12 个文件 | 106 | 少量用例数据随模型收紧调整 |

## 7. 修改文件清单（v1.1.2 → v1.1.3）

```
新增  tests/test_regressions_v113.py（17 例）
修改  agents/generation/story/builder.py   最终 scene 先行 + 统一安全检查 + 3004 不降级
修改  agents/generation/pipeline.py        视频 3004 → blocked
修改  agents/generation/video.py           MP4/JSON 事务发布、页级锁、audio 缺失报错
修改  agents/generation/tts/engine.py      JSON/base64/类型严格校验、w64 拒绝、超时映射、句柄关闭
修改  agents/generation/tts/service.py     /audios 静态挂载
修改  agents/generation/schemas.py         status=ok、highlight 默认 []/拒绝 null、完整 ID 格式
修改  agents/generation/config.py          load_dotenv
修改  agents/generation/cli.py             启动时加载 .env
修改  agents/generation/media.py           深检 -xerror
修改  tests/conftest.py                    用例结束清理临时目录
修改  tests/test_story_schema_contract.py  required 预期随默认值调整
修改  docs/schemas/*                       重新导出
```

## 8. 已知限制

1. 未接真实 TTS / LLM（不调用付费 API），产物为静音 mock + 模板故事。
2. 安全词表为子串匹配，非语义审核。
3. `ffmpeg`/`ffprobe` 硬依赖；缺失时明确 2004，不发布未验证产物。
4. 缓存键仍不区分 silent/http 来源（R112-05），切换引擎前应换 `DATA_DIR`。
5. 单页 v1；多页、job 状态机、取消接口不在本模块范围。
6. 无 git commit/PR（仓库 404、本机无 git）。

## 9. 复现

```bash
pip install -r requirements.txt
export FFMPEG_PATH=/path/to/ffmpeg FFPROBE_PATH=/path/to/ffprobe

python -m pytest            # 123 passed
python examples/install_example.py
export DATA_DIR=./_verify_data TTS_ENGINE=silent
python -m agents.generation run --page-id book01_p03
```
