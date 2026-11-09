# 第五轮（v1.1.4）修复报告

| 项 | 内容 |
|---|---|
| 分支 | `wzy622-patch-1` |
| 版本 | v1.1.4（基于 v1.1.3） |
| 审查结论 | B（剩余阻塞集中在视频发布回滚 F01–F03） |
| 本轮结论 | F01 / F02 / F03 全部修复；**128 / 128 测试通过**（解压复验） |
| 未改动 | 公共 Schema、API 文档、`main`、`dev`；上一版 123 项测试全部保留 |
| 历史交付 | v1.1.0 ～ v1.1.3 包与报告原样保留 |

## 1. F01｜提交完成后备份清理失败会触发破坏性回滚

- **根因**：备份删除放在提交的同一个 `try` 里；任一备份删除失败进入 `except`，
  回滚会删除刚提交成功的新 MP4，而旧 MP4 备份可能已不存在。
- **修法**：拆成两个阶段——
  - **提交阶段**（锁内）：备份旧版本 → 提交 MP4/JSON；失败才回滚；
  - **提交后清理**（锁外）：`_best_effort_unlink()` 逐个删除备份，
    失败只 `logger.warning`，**绝不回滚**已提交产物。
- **测试**：`test_backup_cleanup_failure_does_not_rollback`
  （让 JSON 备份删除抛 `PermissionError`，断言新 MP4/JSON 仍在、有 WARNING）。

## 2. F02｜回滚失败后 finally 仍删除恢复备份

- **根因**：`finally` 无条件 unlink 四类文件；回滚恢复失败时，备份是最后的有效副本。
- **修法**：
  - 回滚分步防护：删除新文件、恢复旧 MP4、恢复旧 JSON 各自 `try`，失败记入 `rollback_errors`；
  - 回滚失败 → **保留现存备份**，抛 `VideoPublishError`，detail 中给出备份路径与失败原因；
  - 回滚成功 → 只清理本轮 staged/json 临时文件；
  - 不再有“无条件删备份”的 `finally`。
- **测试**：`test_rollback_failure_keeps_recovery_backup`
  （JSON 提交失败 + 旧 MP4 恢复失败 → 备份保留且内容为旧版本、错误含 `.mp4.bak.` 路径）。

## 3. F03｜发布锁在回滚前释放

- **根因**：`with 锁` 只包住提交，回滚在锁外重新加锁；A 释放后 B 可发布，A 再回滚会覆盖 B。
- **修法**：备份、提交、回滚全部放在**同一把 `_page_lock(page_id)`** 内；
  只有拿到一致结果（提交成功或回滚完成）才释放锁。提交后的清理不需要锁。
- **测试**：`test_rollback_lock_blocks_other_publisher`
  （A 在 JSON 提交失败处启动 B；B 被锁阻塞；A 回滚完成后 B 发布；断言最终是 B 的字节）。

## 4. 并发与一致性说明

- 锁的作用域：**同进程、同 page_id**。跨进程写者没有串行化，部署上应保证同一页只有一个写进程。
- 成对发布的读者一致性：两次 `os.replace` 之间读者可能看到“旧 MP4 + 新 JSON”或反之；
  读取方应按下发时间/内容做一致性判断，不能把双 rename 当成跨文件原子事务。
- 恢复路径：出现 `VideoPublishError` 时，`.bak.<suffix>` 文件即旧版本，
  人工恢复方式为把 `.bak` 重命名回正式文件名；日志里有完整路径。

## 5. P2 同步修复

- **P2-01 MIME 判定**：改为先取裸 MIME（去掉 `;charset=...`），
  `application/json` / `*+json` 才走 JSON；`audio/*`、`application/octet-stream` 才走二进制；
  `text/html; charset=utf-8` 不再被误判。
  测试：`test_mime_with_parameters_rejected_for_html`、`test_mime_json_with_charset_accepted`。
- **P2-05 断言收紧**：v1.1.3 的模型负例从 `pytest.raises(Exception)` 收紧为 `ValidationError`。

## 6. 测试

```
128 passed in 18.18s（解压包内复验同结果）
```

新增 `tests/test_regressions_v114.py` 5 例；其余 123 例保持。

## 7. 修改文件清单（v1.1.3 → v1.1.4）

```
新增  tests/test_regressions_v114.py（5 例）
修改  agents/generation/video.py      提交/回滚/清理分离，锁覆盖回滚，VideoPublishError
修改  agents/generation/errors.py     新增 VideoPublishError
修改  agents/generation/tts/engine.py MIME 裸值精确判定
修改  tests/test_regressions_v113.py  模型负例改用 ValidationError
修改  README.md / PACKAGE.md / docs/*
```

## 8. 已知限制

1. 发布锁仅进程内；多进程同页写需要外部锁（未实现）。
2. 双文件发布不是跨文件原子事务，读者可能短暂看到混合版本（文档已说明）。
3. 未接真实 TTS/LLM；产物为静音 mock + 模板故事。
4. 缓存键不区分 silent/http 来源（R112-05），切换引擎前建议换 `DATA_DIR`。
5. 媒体元数据核对（音轨/分辨率/fps）与 `stages[]` 聚合仍待后续（R112-06/07）。
6. 无 git commit/PR（仓库 404、本机无 git）。

## 9. 复现

```bash
pip install -r requirements.txt
export FFMPEG_PATH=/path/to/ffmpeg FFPROBE_PATH=/path/to/ffprobe
python -m pytest            # 128 passed
python examples/install_example.py
export DATA_DIR=./_verify_data TTS_ENGINE=silent
python -m agents.generation run --page-id book01_p03
```
