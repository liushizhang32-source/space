# 纸书智伴前端 Mock 联调

本轮提供单页上传、任务创建、状态轮询和 Mock 视频播放。界面内容和视频仅供联调，不代表真实模型识别效果。

## 本机运行

在仓库根目录，准备 Python 3.12、Node.js 18 或更高版本。先按 `orchestrator/README.md` 安装后端依赖，然后在 PowerShell 启动后端（仅一个 worker）：

```powershell
$env:ASSET_BASE_URL = 'http://127.0.0.1:5173'
python -m uvicorn orchestrator.main:app --host 127.0.0.1 --port 8000
```

打开另一个 PowerShell 窗口，在仓库根目录运行：

```powershell
node frontend/server.mjs
```

浏览器访问 http://127.0.0.1:5173。选择 JPG/PNG/WebP，点击上传，然后选择适读年龄并开始生成。后端重启后需重新上传。

前端代理默认只监听本机 127.0.0.1:5173，转发 `/api`、`/previews`、`/json`、`/audios`、`/videos` 到本机 8000；无需浏览器跨域或更改后端 CORS。如果更换端口，请设置前端 `PORT`、后端 `ASSET_BASE_URL` 为相同实际地址；可用 `BACKEND_URL` 修改代理目标。此开发服务器不带鉴权，不应暴露到公网。

## 行为说明

使用后端返回的 `page_id` 和 `job_id`。根据 `poll_after_ms` 顺序轮询（当前 2 秒），请求不重叠，终态停止。停止等待不取消后端任务；网络错误或等待 5 分钟后可继续查询。仅按返回的非空 `video_url` 播放；音频为静音样本。错误显示业务消息，并在联调信息中记录接口、错误码和 trace_id；网络失败没有业务错误码。

`page_no` 当前按 Mock 实现限制为 1–99；仅调用单页生成。生成完成后再次点击会创建新任务。代码不包含 ASR、QA 或真实模型接入。
