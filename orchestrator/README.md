# 纸书智伴 Orchestrator Mock

这是用于前端联调的本地 Mock。所有 OCR/VLM/Story/TTS/Video 阶段均不调用真实模型，不需要 API Key。

## 安装与启动

在仓库根目录，使用 Python 3.12 和独立虚拟环境：

```powershell
python -m pip install -r orchestrator/requirements.txt
python -m uvicorn orchestrator.main:app --host 127.0.0.1 --port 8000
```

当前工作区已有的可用解释器启动命令：

```powershell
& 'C:\Users\16173\Documents\ChatGPT\人工智能+\.venv-schema-tests\Scripts\python.exe' -m uvicorn orchestrator.main:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/docs` 可通过 Swagger 上传与调用。上面的通用 python 必须是可用的 Python 3.12，不要使用本机 PATH 中损坏的 MySQL 内置解释器。

可选环境变量：`DATA_DIR`（默认 ./data）、`ASSET_BASE_URL`（默认 http://127.0.0.1:8000）、`MAX_CONCURRENT_JOBS`（默认 3）。换端口或供其他电脑访问时，同步设置 ASSET_BASE_URL 为客户端可访问的服务地址。

只运行一个 worker。内存任务不可跨进程共享，重启会丢失任务和已上传页面的内存索引；磁盘文件保留，但本版重启后需要重新 capture。

## 三个接口

1. POST /api/v1/capture：multipart 的 image、page_no 与可选 book_id。校验扩展名、MIME 与解码内容均为 jpg/png/webp，文件不超过 10×1024×1024 字节、长边不超过 4096；保存原图和真实 JPEG 缩略图，不触发任务。page_no 接受 1–99，以满足冻结 page_id 的两位页码格式；超过 99 返回 1002。
2. POST /api/v1/generate：JSON `{"page_ids":["book01_p03"],"age_level":"3-6","force":false}`。只接受本进程已 capture 的页面，模拟 queued → running → done，每阶段约 0.3 秒，首次排队约 0.2 秒，返回 poll_after_ms=2000。v1 推荐单页；数组支持 1–30 页，按 page_no 排序。相同活动页面集合返回原 job；force=true 取消所有重叠活动任务后重建；完成后再次提交创建新任务。批次仅部分页面重叠时返回 2003，不静默遗漏新页面。取消只影响内存任务，不删除已有产物。
3. GET /api/v1/jobs/{job_id}：返回进度、阶段、页面及 UTC 时间戳。查询不推进状态，任务由后台协程实际运行；不存在时按文档 A3 场景返回 1003。

HTTP 错误、请求参数错误和业务错误均返回 HTTP 200 的 code/msg/data/trace_id；ULID trace_id 每请求生成。正常 API 响应复用 APIResponse 与 CaptureData。OCR/VLM/Story 文件复用原 Schema 校验。

## 产物与限制

uploads/previews/json/audios/videos/logs 在 DATA_DIR 下创建。仅 previews/json/audios/videos 提供静态访问，原图不公开。页面产物使用固定 page_id 文件名；存储页面索引保留相对路径，响应拼接 ASSET_BASE_URL。

OCR/VLM 返回 empty；故事标题标注 MOCK，model.name=mock。TTS 复制真实静音 MP3，Video 复制真实标有 MOCK 的 MP4。video_url/story_url 在对应文件落盘后才赋值；文件生成失败会显式将任务设为 failed，不伪造可播放 URL。这些数据不能用作识别、故事质量、语音或视频性能验收。详细素材说明见 assets/README.md。

Mock 名义时长为 1 秒，未实现真实字幕/配音同步、重试/超时、降级矩阵全分支、持久化、24 小时清理和鉴权；不提供 ASR/QA/TTS/health 独立接口。文件操作仅适用于本地少量联调流量，未实现整个 multipart 请求体的上游流量限制。

## 自动化测试

```powershell
python -m pip install -r orchestrator/tests/requirements-api-test.txt
python -m pytest orchestrator/tests -q --tb=short -W error -p no:cacheprovider
```

接口测试使用临时目录、FastAPI TestClient 和完整生命周期，验证真实文件与静态 URL；无需启动外部服务。固定 Starlette/AnyIO 版本是为了保持 HTTPX TestClient 在 -W error 下兼容，不隐藏弃用警告。

后续将 Storage.produce 的模拟阶段替换为真实模块适配器；继续使用现有 Schema 验证模块产物，保留 Jobs 的幂等、取消与统一错误出口。真实 TTS 接入后写入实测时长，再接视频合成和降级/超时策略。
