# 第六轮（v1.1.5）修复报告

| 项 | 内容 |
|---|---|
| 分支 | `wzy622-patch-1` |
| 版本 | v1.1.5（基于通过独立运行测试的 v1.1.4） |
| 上游结论 | 正常链路通过；RT-01/RT-02 两项增强验收失败 |
| 本轮结论 | RT-01 / RT-02 修复；**131 / 131 测试通过**（解压复验） |
| 未改动 | 正常链路、公共 Schema、API 文档、错误码集合、`main`、`dev` |
| 历史交付 | v1.1.0 ～ v1.1.4 包与报告原样保留 |

## 1. RT-01｜需要人工恢复的发布错误仍自动重试

- **根因**：`VideoPublishError` 继承 `VideoError` 的 3007，而 3007 在 §1.13 重试白名单里，
  `compose_video` 的 `retryable` 判断放行了自动重试。
- **修法**：
  - `VideoPublishError` 覆盖 `retryable` 属性 → `False`（错误码保持 3007，不破坏契约分支）；
  - `compose_video` 增加显式 `isinstance(exc, VideoPublishError)` 短路，双保险；
  - 普通 3007（ffmpeg 临时失败）仍按原策略重试 1 次。
- **验证**：
  - `test_video_publish_error_is_not_retryable`
  - `test_compose_does_not_retry_publish_error`（`max_retry=1`，底层只调用 1 次）

## 2. RT-02｜pipeline 丢失恢复诊断

- **根因**：`pipeline.run_page` 捕获视频错误后只保留 `code/msg`，`VideoPublishError.detail`
  里的备份路径与恢复信息被丢弃。
- **修法**：
  - 新增 `record_publish_recovery()`：生成 `rec_<ULID>`，写
    `{DATA_DIR}/logs/{page_id}_publish_errors.jsonl`（event / recovery_id / page_id / code / msg / detail / at），
    并发 `logger.warning`；
  - `run_page` 的 `video_error` 增加 `recovery_id`，**不包含**本机路径；
  - 备份路径只存在内部日志和 WARNING 中，供排障使用。
- **验证**：`test_pipeline_records_recovery_diagnostics`
  - `recovery_id` 以 `rec_` 开头；
  - 公共 payload 不含 `MOCK_RECOVERY_BACKUP_PATH`；
  - JSONL 日志存在且含路径；
  - caplog 捕获 WARNING。

## 3. 与独立测试报告的对应

| 报告项 | 处理 | 复测 |
|---|---|---|
| 原 128 项 pytest | 未改动源码行为 | 本轮 131 项中全部保留 |
| 补充 7 项（2 失败） | RT-01/RT-02 修复 | 对应两例现应通过 |
| 真实 HTTP 12/12 | 未改 TTS 路由与 envelope | 不受影响 |
| 正常 CLI/媒体链路 | 未改生成与编码参数 | 不受影响 |

## 4. 测试

```
131 passed in 19.50s（解压包内复验同结果）
```

新增 `tests/test_regressions_v115.py` 3 例；原有 128 例全部保留。

## 5. 修改文件清单（v1.1.4 → v1.1.5）

```
新增  tests/test_regressions_v115.py（3 例）
修改  agents/generation/errors.py     VideoPublishError.retryable = False
修改  agents/generation/video.py      compose_video 显式不重试 VideoPublishError
修改  agents/generation/pipeline.py   record_publish_recovery + video_error.recovery_id
修改  README.md / PACKAGE.md / docs/*
```

## 6. 已知限制（未变）

1. 发布锁仅进程内；跨进程同页写需外部锁。
2. 双文件发布非跨文件原子事务，读者可能短暂看到混合版本。
3. 未接真实 TTS/LLM；产物为静音 mock + 模板故事。
4. 缓存键不区分 silent/http 来源（R112-05）。
5. 媒体元数据核对与 `stages[]` 聚合未做（R112-06/07）。
6. 无 git commit/PR（仓库 404、本机无 git）。

## 7. 复现

```bash
pip install -r requirements.txt
export FFMPEG_PATH=/path/to/ffmpeg FFPROBE_PATH=/path/to/ffprobe
python -m pytest            # 131 passed
python examples/install_example.py
export DATA_DIR=./_verify_data TTS_ENGINE=silent
python -m agents.generation run --page-id book01_p03
```
