# 对 v1.1.5 隔离复测报告（F115-01）的回应 · v1.1.6

测试报告：`reports/MEMBER3_V1.1.5_ISOLATED_TEST_REPORT.md`。
RT-01 / RT-02 已复测通过；本轮只修新增的 F115-01。

## F115-01｜恢复日志不可写时抛 PermissionError（P2）

**状态：已修复。**

- `pipeline.record_publish_recovery` 不再让诊断写入影响业务结果：
  1. 生成 `recovery_id` 后**先 `logger.warning`**（即使后续写盘全失败，也有诊断出口）；
  2. 写主日志 `logs/{page_id}_publish_errors.jsonl`，`OSError` 局部捕获；
  3. 失败改写备用日志 `logs/publish_errors_fallback.jsonl`，同样捕获；
  4. 两者都失败时 `logger.error` 记录 `recovery_id` + detail，仍返回 `recovery_id`；
  5. 公共 `video_error` 依旧只有 `code/msg/recovery_id`，不含本机路径。
- 视频状态保持 `partial + no_video`，3007 语义不变，不会因为日志失败变成成功。

**证据**

- `test_primary_log_io_failure_uses_fallback`
  （主 JSONL `open` 注入 `PermissionError` → 结构化结果返回、备用日志含 detail、WARNING 存在）
- `test_all_log_targets_fail_but_result_preserved`
  （主/备都失败 → 仍返回 `recovery_id`，`logger.error` 有持久化失败记录）
- `test_log_dir_creation_failure_does_not_raise`
  （`logs/` mkdir 失败也不抛）

## 与上轮 7 项增强检查的关系

- RT-01（发布恢复错误不重试）、RT-02（pipeline 恢复诊断）逻辑未改，仍通过；
- 正常 HTTP/媒体/CLI 链路未改；
- 新增用例只针对诊断写入故障，不改变公共字段。

## 复测

```bash
python -m pytest      # 134 passed（原 131 + 新增 3）
```

## 仍未关闭的限制

1. 发布锁仅进程内；跨进程同页写需外部锁。
2. 双文件发布不是跨文件原子事务；读者一致性需业务侧判断。
3. 缓存键未区分 silent/http（R112-05）；切换真实引擎前应换 `DATA_DIR`。
4. 媒体元数据核对（R112-06）与 `stages[]` 聚合（R112-07）未做。
5. 未接真实 LLM/TTS；产物是 mock 模板 + 静音音轨。
6. 无 git commit/PR（仓库 404）。
