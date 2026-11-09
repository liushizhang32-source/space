# 第七轮（v1.1.6）修复报告

| 项 | 内容 |
|---|---|
| 分支 | `wzy622-patch-1` |
| 版本 | v1.1.6（基于 v1.1.5） |
| 上游结论 | 上轮 RT-01/RT-02 已修复；新增 F115-01（恢复日志 I/O 失败） |
| 本轮结论 | F115-01 修复；**134 / 134 测试通过**（解压复验） |
| 未改动 | 公共 Schema、API 文档、错误码集合、`main`、`dev`、成员二文件 |
| 历史交付 | v1.1.0 ～ v1.1.5 包与报告原样保留 |

## 1. F115-01｜恢复日志不可写会抛出 PermissionError

- **根因**：`record_publish_recovery` 里 `mkdir` / `open` / `write` 没有 `OSError` 保护，
  且 `logger.warning` 写在文件写入之后；日志路径一坏，异常直接冒泡，`run_page` 拿不到
  `PageRunResult`，原本的 3007“需人工恢复”语义也被遮蔽。
- **修法**（诊断写入改为尽力而为，绝不改变业务结果）：
  1. 先生成 `recovery_id` 并**立即 `logger.warning`**，保证至少有一个诊断出口；
  2. 主日志 `logs/{page_id}_publish_errors.jsonl`，捕获 `OSError`；
  3. 失败则写备用日志 `logs/publish_errors_fallback.jsonl`，同样捕获 `OSError`；
  4. 两者都失败：`logger.error` 记录 `recovery_id` 与 detail，仍然返回 `recovery_id`；
  5. 公共 `video_error` 仍只有 `code/msg/recovery_id`，不泄漏本机路径。
- **验证**：
  - `test_primary_log_io_failure_uses_fallback`：主 JSONL `open` 抛 `PermissionError` →
    返回 `partial`、`recovery_id` 有效、备用日志含 detail、WARNING 存在；
  - `test_all_log_targets_fail_but_result_preserved`：主/备都失败 → 仍返回结构化结果，
    `logger.error` 有“恢复信息未能持久化”；
  - `test_log_dir_creation_failure_does_not_raise`：`logs/` 的 `mkdir` 失败也不抛。

## 2. 关于上一版表述的更正

上轮报告把 v1.1.4 写成“基于通过独立运行测试的 v1.1.4”。按独立测试报告，
v1.1.4 的准确状态是：**正常链路通过，RT-01/RT-02 两项增强检查失败**；
这两项在 v1.1.5 修复后才通过。本版及后续文档统一按此表述。

## 3. 测试

```
134 passed in 19.02s（解压包内复验同结果）
```

新增 `tests/test_regressions_v116.py` 3 例；原有 131 例全部保留。

## 4. 修改文件清单（v1.1.5 → v1.1.6）

```
新增  tests/test_regressions_v116.py（3 例）
修改  agents/generation/pipeline.py   record_publish_recovery：先告警、主/备日志、OSError 全捕获
修改  README.md / PACKAGE.md / docs/*
```

## 5. 已知限制（未变）

1. 发布锁仅进程内；跨进程同页写需外部锁。
2. 双文件发布非跨文件原子事务，读者可能短暂看到混合版本。
3. 未接真实 TTS/LLM；产物为静音 mock + 模板故事。
4. 缓存键不区分 silent/http 来源（R112-05）。
5. 媒体元数据核对与 `stages[]` 聚合未做（R112-06/07）。
6. 无 git commit/PR（仓库 404、本机无 git）。

## 6. 复现

```bash
pip install -r requirements.txt
export FFMPEG_PATH=/path/to/ffmpeg FFPROBE_PATH=/path/to/ffprobe
python -m pytest            # 134 passed
python examples/install_example.py
export DATA_DIR=./_verify_data TTS_ENGINE=silent
python -m agents.generation run --page-id book01_p03
```
