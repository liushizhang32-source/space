# 最小 FastAPI Mock 交付报告

日期：2026-11-05（Asia/Hong_Kong）。分支：dev。基准 HEAD：7006d5e9be17219253ef9e04ff279262bd37b549。本轮未提交、暂存或推送。

## 实现结果

| 接口 | 实现 |
|---|---|
| POST /api/v1/capture | multipart 上传，支持 jpg/png/webp；扩展名、MIME 与解码格式一致性验证；10 MiB 文件读取上限、4096 像素长边上限；page_no、book_id 验证；原图与 JPEG 缩略图真实落盘；复用 CaptureData/CaptureResponse，不触发 OCR。 |
| POST /api/v1/generate | page_ids/age_level/force；创建内存任务；相同活动页面集合返回原 job_id；force 取消重叠 queued/running 后重建；done 后重建；默认最多 3 个活动任务；返回 queued/status/poll_after_ms。 |
| GET /api/v1/jobs/{job_id} | 后台协程按 OCR→VLM→Story→TTS→render 顺序运行，不通过查询推进；queued/running/done、进度、页面状态、阶段状态、时长、UTC 时间戳；不存在按 A3 场景返回 1003。 |

API 按 code/msg/data/trace_id 统一封装，错误 HTTP 200；trace_id、job_id 为标准结构的 ULID。产物复用原 OCRData/VLMData/StoryData 校验。存储页面索引使用相对路径，响应由 ASSET_BASE_URL 拼接。仅文件存在后赋值 story_url/video_url；静态目录可实际访问。

真实模型调用为零。MOCK 视频为带标识的 H.264 测试画面，音频为静音 MP3，均为本机生成并通过完整解码检查的真实文件。测试/运行均不需要 API Key 或模型额度。

## 新增文件（20 个）

- `.gitignore`：忽略运行数据、缓存、虚拟环境与敏感环境文件。
- `orchestrator/README.md`：启动、调用、测试及限制说明。
- `orchestrator/main.py`：应用工厂、生命周期、统一错误出口、静态资源挂载。
- `orchestrator/requirements.txt`：服务依赖。
- `orchestrator/api/__init__.py`、`models.py`、`routes.py`：请求/任务数据模型与三个接口。
- `orchestrator/core/__init__.py`、`config.py`、`errors.py`、`ids.py`：配置、业务错误与 ULID。
- `orchestrator/services/__init__.py`、`storage.py`、`jobs.py`：本地产物与内存任务调度。
- `orchestrator/assets/README.md`、`mock.mp3`、`mock.mp4`：真实测试媒体及来源说明。
- `orchestrator/tests/requirements-api-test.txt`：接口测试依赖入口。
- `orchestrator/tests/test_mock_api.py`：42 项接口测试。
- `orchestrator/tests/MOCK_SERVICE_REPORT.md`：本报告。

没有修改已有跟踪文件。docs/API_v1.0.md 和原五份 Schema 均与 HEAD 一致。原第一轮未跟踪 XML 保留，未覆盖或提交。

## 环境与执行结果

实测 Python 3.12.14、Pydantic 2.14.1、pytest 9.2.0、FastAPI 0.162.0、Starlette 0.50.0、AnyIO 4.11.0、HTTPX 0.28.1、Uvicorn 0.54.0、python-multipart 0.0.33、Pillow 13.0.0。

使用现有独立解释器：`C:\Users\16173\Documents\ChatGPT\人工智能+\.venv-schema-tests\Scripts\python.exe`，没有使用 PATH 的 MySQL Python。

首次依赖安装选择的 Starlette 1.10.0 对 HTTPX TestClient 发出弃用警告，降为满足 FastAPI 版本要求的 0.50.0；随后将产生旧别名弃用警告的 AnyIO 4.16.0 固定为 4.11.0。未过滤或屏蔽警告。依赖已写入 requirements.txt，pip check 返回 No broken requirements found，退出码 0。

实际完整测试命令（仓库根目录）：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& '..\.venv-schema-tests\Scripts\python.exe' -m pytest orchestrator/tests -q --tb=short -W error -p no:cacheprovider
```

结果：451 passed in 3.65s，退出码 0。原两个 Schema 测试文件及其参数集未改动，409 项均通过；新增接口测试 42 项均通过。无失败、跳过、xfail 或收集错误。

接口测试覆盖：三种合法图片、实际预览与原图保存、可选 book_id、伪装/损坏/不支持格式、10 MiB 临界值与超限、4096 边界与超限、缺失/非法参数、创建任务、排队/运行/完成与单调进度、阶段顺序、真实媒体与 JSON URL、queued/running 幂等、queued/running 强制取消、完成后重建、缺失 job/page、并发限制、多页排序、部分重叠防丢页、非法 JSON、未知路由、统一 9001 兜底、产物失败与 trace_id。

另外启动了真实 Uvicorn 子进程（临时 DATA_DIR、随机空闲本机端口），通过 localhost HTTP 请求获得 HTTP 200 / code 1003 的预期统一响应。检查完成后关闭进程，没有遗留后台服务。视频、音频两份素材均通过 FFmpeg 全文件解码；运行服务无需 FFmpeg。

最终 git diff --check 通过；冻结文档/Schema 的 git diff 为空；分支及 HEAD 未变化，无暂存内容。

## 启动

在仓库根目录运行：

```powershell
& 'C:\Users\16173\Documents\ChatGPT\人工智能+\.venv-schema-tests\Scripts\python.exe' -m uvicorn orchestrator.main:app --host 127.0.0.1 --port 8000
```

Swagger UI：`http://127.0.0.1:8000/docs`。其他环境先使用 Python 3.12 安装 orchestrator/requirements.txt；测试环境另安装 orchestrator/tests/requirements-api-test.txt。

## 已知限制及契约边界

- 本版单进程、单 worker，任务和页面索引仅存内存；重启需重新上传。未实现数据库、鉴权、自动清理、真实模型、重试/超时或完整降级矩阵。
- 图像文件上限为 10×1024×1024 字节。应用仅限读取文件 10 MiB+1 字节；multipart 解析/临时文件落盘由框架处理，尚无反向代理级整个请求体限流。
- page_no 按冻结 page_id 的两位格式限制为 1–99；正文上传表只写从 1 开始，100 以上无法形成合法冻结 ID，记录此边界待队长确认，未修改原 Schema。
- v1 推荐单页；当前保留数组支持至 30 页。相同活动页面集合幂等；部分重叠批次返回 2003，避免返回已有任务后静默遗漏其他页，批次策略待真实整本功能时进一步确认。
- 错误表列有 3005，但 A3 具体不存在场景写 1003；本轮按 A3 返回 1003。未改动文档。
- OCR/VLM empty 是模拟结果，safety=true 是占位结论；Story 标题和模型信息明确 MOCK。静音音频不含真实旁白，视频是固定 MOCK 画面，不能代表上传页面的生成质量。阶段 ok 表示本地模拟产物生成成功。
- 名义时长 1 秒，未计入音频编码器填充，不作为真实 TTS 实测时长验收。真实接入必须替换音频、视频并回填实测时长。
- 未实现真实 TTS/ASR/QA/health 独立接口；保留原 Story 尺寸、order 连续性和列表默认值歧义。
- 小规模本地文件写入在任务协程内同步完成，便于取消后不再覆盖新任务产物；真实大文件处理需后台 worker、原子产物发布和版本隔离。

## 下一阶段

建议队长验收 capture→generate→jobs 与媒体静态访问闭环。随后按 Storage.produce 的阶段边界接入真实 OCR/VLM/Story/TTS/Video 适配器，逐步增加超时/重试、失败降级与安全拦截测试。接入真实 TTS 时先替换静音素材与名义时长，再验证字幕/配音/视频同步；保持已有 Schema 与接口回归不变。
