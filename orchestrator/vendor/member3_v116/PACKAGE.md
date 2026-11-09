# 成员 3 代码包 · Story / TTS / Video

| 项 | 内容 |
|---|---|
| 包名 | `paperbook-member3-generation-wzy622-patch-1-v1.1.6` |
| 版本 | v1.1.6（隔离复测后修复版） |
| 分支 | `wzy622-patch-1` |
| 打包日期 | 2026-11-08 |
| 对应契约 | `docs/API_v1.0.md`（ZSZB-API-1.0 冻结版）C3 / C4 / A6 |
| 归属 | 成员 3（Story / TTS / Video） |
| 测试 | **134 passed**（`python -m pytest`） |
| 历史版本 | v1.1.0 ～ v1.1.5 包与报告原样保留 |

## 1. 本版修复（F115-01）

| 问题 | 修法 | 验证 |
|---|---|---|
| 恢复日志不可写时 `PermissionError` 直接抛出 | 先 `logger.warning`；主日志 `OSError` 捕获 → 备用日志 → 都失败仅 `logger.error`；始终返回 `recovery_id`，状态仍 `partial + no_video` | `test_regressions_v116.py` 3 例 |

说明：公共 `video_error` 仍只含 `code/msg/recovery_id`，本机路径只进内部日志。

## 2. 包内容

```
paperbook-member3-generation-wzy622-patch-1-v1.1.6/
├── README.md / PACKAGE.md / requirements.txt / pytest.ini
├── .env.example / .gitignore
├── agents/generation/        story / tts / video / pipeline / safety / cli
├── tests/                    134 项用例
├── docs/                     实现说明、IO 示例、七轮报告、逐条回应、变更记录、Schema
├── examples/                 示例输入 + 安装脚本
├── artifacts/                实际音视频产物 + ffprobe 证据 + Schema 校验结果
└── scripts/                  verify.ps1 / verify.sh
```

**不含**：真实 API Key、`.env`、模型权重、ffmpeg 二进制、`_vendor`、缓存目录。

## 3. 环境要求

- Python 3.10+
- `ffmpeg` 与 `ffprobe`（缺失时明确 2004，不发布未验证产物）
- 依赖见 `requirements.txt`

## 4. 验证

```bash
pip install -r requirements.txt
python -m pytest                 # 134 passed

python examples/install_example.py
python -m agents.generation story --page-id book01_p03
python -m agents.generation tts   --text "从前有只小兔子，住在森林边上。"
python -m agents.generation video --page-id book01_p03
python -m agents.generation run   --page-id book01_p03
```

Windows 一键：`powershell -ExecutionPolicy Bypass -File scripts\verify.ps1`

## 5. 三个模块可独立运行

| 模块 | 命令 | 输入 | 输出 |
|---|---|---|---|
| Story | `story --page-id book01_p03` | `json/*_ocr.json`、`json/*_vlm.json` | `json/*_story.json` + 音频 |
| TTS | `tts --text "..."` / `serve --port 8001` | 文本 / HTTP JSON | `audios/tts_{hash}.mp3` + 响应 |
| Video | `video --page-id book01_p03` | `json/*_story.json` + `uploads/*_orig.*` | `videos/*.mp4` + `json/*_video.json` |

## 6. 发布恢复语义

- 同进程同页写者由 `_page_lock(page_id)` 串行；跨进程未串行化。
- 提交后清理失败只告警；回滚失败保留 `.bak` 并抛 `VideoPublishError`。
- `VideoPublishError` 不自动重试；调用方转人工恢复。
- pipeline 写 `logs/{page_id}_publish_errors.jsonl`（失败退 `logs/publish_errors_fallback.jsonl`），
  仍失败则只记 `logger.error`；公共结果只给 `recovery_id`。

## 7. 产物证据（artifacts/）

```
TTS    mp3 / 24000 Hz / mono / 4.09s            （artifacts/tts/probe.txt）
Video  h264 720x1280 + aac 44100Hz / 7.67s      （artifacts/video/probe.txt）
Story  StoryDoc 通过：status=ok、scene 非空、highlight 默认 [] 且属于本页
```

> 故事为 `mock-template`、音频为静音（`TTS_ENGINE=silent`），仅验证链路与文件有效性。

## 8. 配置（关键项）

| 变量 | 默认 | 作用 |
|---|---|---|
| `TTS_MAX_AUDIO_BYTES` | 10485760 | HTTP 音频响应大小上限 |
| `TTS_TIMEOUT_SEC` | 20 | 下载/合成超时（超时 2002） |
| `SAFETY_ENABLED` / `SAFETY_BLOCKLIST` | 0 / 空 | 统一安全开关与词表 |
| `FFMPEG_PATH` / `FFPROBE_PATH` | ffmpeg / ffprobe | 媒体生成与校验 |

CLI 启动时加载工作目录 `.env`（仅补齐未设置变量）。包里没有密钥。

## 9. 与其他人对接

- **成员 1（中枢）**：`pipeline.run_page()` 或 `run` 子命令；结果与 `pages[]` 同构（无 `stages[]`）。
  恢复错误通过 `video_error.recovery_id` 追踪。
- **成员 4（问答）**：只调 `POST /api/v1/tts`；不安全文本 3004。
- **成员 5（评测）**：读 `json/*_story.json`、`json/*_video.json`。

## 10. 分支与 PR

仓库 `github.com/liushizhang32-source/space` 仍 404，本机无 git，因此无真实 commit/PR；
`wzy622-patch-1` 为交付标识。合并建议（不要重复推到 `feat/generation`）：

```bash
git checkout -b wzy622-patch-1 origin/dev
git add -A
git commit -m "fix(generation): recovery log I/O fallback; keep 3007 recovery result"
git push -u origin wzy622-patch-1
# PR: wzy622-patch-1 -> dev
```

## 11. 已知限制

1. 发布锁仅进程内；多进程同页写需外部锁。
2. 双文件发布非跨文件原子事务（读取一致性策略见文档）。
3. 未接真实 TTS/LLM；产物为静音 mock + 模板故事。
4. 缓存键不区分 silent/http 来源（R112-05）。
5. 媒体元数据核对与 `stages[]` 聚合未做（R112-06/07）。
6. 无 git commit/PR（仓库不可达）。
