# 成员3 v1.1.6 隔离集成说明

此模式使用成员3的模板 Story、静音 TTS 和真实本地 FFmpeg 合成；OCR/VLM 使用固定 MOCK 数据。没有接入真实模型或供应商，不会读取模型密钥或 TTS HTTP 配置。

## 后端切换

- `GENERATION_BACKEND=mock`（默认）：原有 Mock 服务不变，继续使用原测试素材。
- `GENERATION_BACKEND=member3`：使用独立 Adapter 和 Member3Jobs，导入 `orchestrator.vendor.member3_v116`，不导入仓库根目录旧 `agents` 模块。
- 不新增路由或请求字段；仍为 Capture、Generate、Jobs 三个现有接口和既有统一响应。

## 本机 Windows 启动

在 `space-member3-v116-integration` 目录执行。以下解释器和工具路径为本机本轮实际验证的现有文件；其他机器需提供自己的 FFmpeg 和 FFprobe，不自动安装。

```powershell
$py = (Resolve-Path '..\.venv-schema-tests\Scripts\python.exe').Path
$env:FFMPEG_PATH = (Resolve-Path '..\.venv-schema-tests\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v9.0.2.exe').Path
$env:FFPROBE_PATH = (Resolve-Path '..\module-integration-20261108\member3-orchestrator-v116\tools\ffprobe.exe').Path
$env:GENERATION_BACKEND = 'member3'
$env:DATA_DIR = Join-Path $PWD 'data\member3-v116'
$env:ASSET_BASE_URL = 'http://127.0.0.1:8016'
& $py -m uvicorn orchestrator.main:app --host 127.0.0.1 --port 8016
```

Swagger：`http://127.0.0.1:8016/docs`。127.0.0.1 仅本机可访问。本轮没有公开服务，没有新增 CORS 配置。

可选 `SAFETY_BLOCKLIST` 为逗号分隔的本地审核词表；成员3模式始终启用本地词表检查，上游 safety.pass=false 无条件阻止生成。空词表不等于真实模型安全审核已验收。

## 调用与产物

1. `POST /api/v1/capture`：multipart 的 `image`、`page_no`、可选 `book_id`，保存原图，返回 page_id。
2. `POST /api/v1/generate`：原请求 `page_ids`、`age_level`、`force`，返回 queued/job_id/poll_after_ms。
3. 每 2 秒 `GET /api/v1/jobs/{job_id}`，读取页面和阶段状态，直到 done/partial_failed/failed/cancelled。
4. 成功后的 preview_url、story_url、Story 中 audio_url、video_url 由同一个 Orchestrator 静态挂载提供，使用与 ASSET_BASE_URL 一致的端口。

页面含降级时为 partial，任务为 partial_failed；TTS 普通失败为 no_audio，采用估算时长继续生成静音视频；Video 普通失败为 no_video，只发布合法 Story/音频。安全拒绝为 blocked，停止后续阶段，不公开本任务产物。无法生成 Story 的页面为 failed。

音视频必须实际解码通过，发布前和发布副本还要核对验证时哈希。非法/丢失媒体不会作为成功地址返回。

## 调度与文件边界

- 每个任务页在 `DATA_DIR/.member3/` 下的唯一工作目录运行，原图按 Capture 元数据锁定复制。
- OCR/VLM 是符合公共 Schema 的固定数据；ID、bbox 和图像边界按当前上传图片生成。
- 调用成员3 builder 时延迟 TTS，先得到安全且符合 StoryData 的 estimate Story，再在独立 TTS 阶段调用原 TTSClient。没有复制或改写成员3的 Story 算法。
- 耗时生成/解码在线程工作单元执行，HTTP 事件循环可响应轮询和 force；取消不能终止线程，所以会等待旧线程结束并清理其私有目录。旧线程从不写公开产物。
- 发布在取消检查之后进行，每个文件使用临时副本 + os.replace，全部选定文件处理完成才返回本任务 URL。它不是跨文件事务或多进程并发写方案。
- VideoPublishError 不自动重试；恢复备份目录保留，恢复记录写入 DATA_DIR/logs。`.member3` 与 logs 都没有静态挂载，不能把备份当临时垃圾自动删除。
- 默认普通任务完成/失败后清理私有目录；清理 I/O 错误写内部日志。进程被强杀的恢复不属于本轮完整验收范围。

## 回归命令

使用已验证解释器和上述 FFmpeg/FFprobe 路径；回归原 Mock API 时设置默认后端：

```powershell
$env:GENERATION_BACKEND = 'mock'
& $py -m pytest orchestrator/tests -q --tb=short -W error
Push-Location orchestrator/vendor/member3_v116
try { & $py -m pytest -q } finally { Pop-Location }
```

Orchestrator 独立 pytest.ini 保留 tmpdir 插件，隔离远程 dev 根配置中的禁用设置，不改作者测试配置。成员3原测试使用其自己的目录夹具，FFmpeg/FFprobe 缺失会 skip，因此验收时必须确认实际为 0 skip；不能把有 skip 的结果报作全部媒体验收通过。

本轮受控驱动另禁止外部网络、模型 SDK 和非媒体进程，记录完整命令/退出码/XML，详情见 `reports/MEMBER3_V1.1.6_ISOLATED_INTEGRATION_REPORT.md`。

## 部署前仍需确认

- 只验收 MOCK/静音链路，真实语音/LLM、外部审核质量和额度策略未验证。
- 多进程写同页、并发读者跨文件一致性、断电恢复仍需单独策略。
- 使用独立 DATA_DIR，避免与旧 Mock 或未来真实引擎的缓存混用。
- 现有依赖文件固定 Pydantic 2.14.1，本轮现有解释器为 2.14.2；未升级/改写依赖。PR 前应在团队锁定环境复现，不把本轮当作全平台安装验证。
- 本轮不提交、不推送、不合并；等待队长验收后决定 PR。
