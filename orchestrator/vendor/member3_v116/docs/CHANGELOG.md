# 变更记录

## v1.1.6（2026-11-08，wzy622-patch-1，隔离复测后修复）

- 恢复日志写入改为尽力而为：先 WARNING，主日志失败写备用日志，两者都失败只记 ERROR，
  不再因日志 I/O 失败抛出异常或遮蔽 3007 恢复语义。
- 新增 `tests/test_regressions_v116.py`（3 例），测试 131 → **134**。

---

## v1.1.5（2026-11-08，wzy622-patch-1，独立运行测试后修复）

- `VideoPublishError` 不可重试（`retryable=False`，错误码仍 3007）；`compose_video` 显式短路。
- `pipeline` 捕获发布恢复错误时写 `logs/{page_id}_publish_errors.jsonl` 并输出 WARNING，
  公共响应只加 `recovery_id`，不泄漏本机路径。
- 新增 `tests/test_regressions_v115.py`（3 例），测试 128 → **131**。

---

## v1.1.4（2026-11-08，wzy622-patch-1，第五轮静态审查后备修复）

- Video 发布拆分“提交”与“提交后清理”：备份清理失败只告警，不回滚已提交产物。
- 回滚步骤逐项防护；恢复失败时保留 `.bak` 并抛 `VideoPublishError`（含恢复路径）。
- 备份/提交/回滚全部在同一把页级锁内，回滚不再释放锁。
- 明确锁只覆盖同进程同页写者；双文件发布不是跨文件原子事务。
- MIME 改为裸值精确判定（`text/html; charset` 不再误判）。
- 模型负例断言收紧为 `ValidationError`。
- 新增 `tests/test_regressions_v114.py`（5 例），测试总数 123 → **128**。

---

## v1.1.3（2026-11-08，wzy622-patch-1，第四轮静态审查后备修复）

- 最终 `scene` 与 `narration` 在 TTS 前统一完成安全审核；安全拒绝（3004）不再被降级成 no_audio；
  视频阶段 3004 保持 blocked。
- Video 改为 MP4/JSON 事务化发布：唯一临时名、页级锁、旧版本备份与失败回滚、finally 清理。
- HTTP JSON/base64 严格校验：JSON 必须对象、`audio_base64` 必须非空字符串、严格 base64、
  text/html 包 JSON 拒绝、wav 只认 wav 容器、超时映射 2002、错误句柄关闭。
- Story 模型收紧：`status` 仅 `ok`、`highlight_object_ids` 默认 `[]` 且拒绝 null、
  `safety_flags` 默认 `[]`、完整 ID 格式校验。
- 顺带：`.env` 实际加载、TTS 服务挂载 `/audios`、深检 `-xerror`、测试临时目录清理。
- 新增 `tests/test_regressions_v113.py`（17 例），测试总数 106 → **123**。

---

## v1.1.2（2026-11-07，wzy622-patch-1，第三轮静态审查后备修复）

- Video 拒绝 `story.json` 的 `safety_pass=false`（即使安全开关关闭），返回 3004。
- 静音 TTS 与 Video 改为“临时产物验证通过后才发布”；失败只清理临时文件。
- HTTP 错误体限长读取；音频容器格式（`format_name`）纳入校验；缓存命中改为深检 + 格式比对。
- 失败路径不再删除已有有效音频；临时文件/临时目录加入线程与随机后缀；Windows 替换加退避重试。
- Story 输入页身份校验（schema_version/page_id/page_no/book_id），未知枚举按 failed 处理。
- 新增 `tests/test_regressions_v112.py`（11 例），测试总数 95 → **106**。

**测试**：106 passed；历史包 v1.1.0 / v1.1.1 保留。

---

## v1.1.1（2026-11-07，wzy622-patch-1，第二轮审查 B 类修复）

**安全**

- 统一安全检查入口：`safety.ensure_safe` / `guard_text`（TTS）/ `ensure_story_safe`（Video）；
  Story、TTS（含 A6 独立调用）、Video 三条路径都接入，无法绕过。
- 媒体校验改为三态：`OK / INVALID / UNAVAILABLE`；缺 ffmpeg 时不再判定为解码成功，
  TTS 返回 2004、Video 返回 2004 且不发布产物。
- HTTP 音频下载校验：状态码、Content-Type、Content-Length/实际大小、真实编码格式、可解码。
- 下载超时 / 解码失败 / 格式不符：清理 `.part` 与半成品，不留下未验证文件。

**Story 结构**

- `highlight_object_ids` 必须属于当前 `page_id`（`{page_id}_o` 前缀）。
- 新增“模型 ↔ 导出 Schema ↔ 契约字段”一致性测试；重新导出 `docs/schemas/`。
- 不改公共 API 与公共 Pydantic Schema。

**测试**：74 → 95（新增 `test_http_audio.py` 9、`test_safety_entrypoints.py` 6、
`test_story_schema_contract.py` 5，`test_media.py` +4，`test_tts.py` 迁出 3）。

**影响文件**：`config.py`、`media.py`、`safety.py`、`tts/engine.py`、`tts/client.py`、
`video.py`、`schemas.py`、`.env.example`、`docs/schemas/*`、三份新增测试。

---

## v1.1.0（2026-11-07，wzy622-patch-1，第一轮审查 B 类修复）

- 修 `JSONResponse(200, ...)` 参数位置错误，A6 异常处理器恢复 HTTP 200。
- 降级路径 `scene` 五级兜底 + Schema 强制非空。
- 生成后安全检查（草稿 / 落盘前）。
- 音频/视频有效性校验（存在、编码、时长、可解码）。

**测试**：60 → 74。

---

## v1.0.0（2026-11-07，feat/generation 骨架）

- 首版交付：C3 / C4 / A6、单页流水线、降级矩阵、内容哈希缓存、60 项测试、代码包。
