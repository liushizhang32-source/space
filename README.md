# 纸书智伴：M1 / M2 / M3 与真实模型工作室

## iPad / Safari / PWA 入口

双击 `INSTALL.bat` → `START_IPAD_SERVER.bat`，按电脑显示的二维码、家庭证书指纹和设备配对引导连接iPad。
完整中文说明：[使用说明_iPad.md](使用说明_iPad.md)。儿童界面与家长Key/费用配置分离；无Key可上传、真实OCR与明确MOCK演示。
真机证书信任需在iPad手动完成；不关闭防火墙、不自动开放公网。

M1 负责授权、预算、任务与资产；M2 负责视觉；M3 负责故事、TTS 和视频。
公共 API / C1 / C2 / 冻结 M1–M2 V1.0 保持不变。新增 P1–P5 仍为
**PROPOSED**，未激活 Generation DRAFT，也未获得生产准入。

## 真实模型工作室（本轮入口）

```powershell
./scripts/install_all.ps1
./scripts/start_system.ps1
```

打开 http://127.0.0.1:8765，在配置区输入百炼Key，再上传图片/PDF、多页排序、选择年龄、
查看费用并确认生成。真实本地PaddleOCR/OpenCV/FFmpeg；云端Qwen3-VL-Plus/Qwen-Plus/
CosyVoice3/Wan由M1统一预算和授权。Key仅后端内存；全项目150元；提交未知不自动退款重发。
界面没有假成功模式。当前真实云端质量仍待Key后验证，PRODUCTION_READY=NO。

完整操作、成员四接入、取消/恢复及测试见[工作室说明](docs/REAL_MODEL_STUDIO.md)、
[官方型号与价格](docs/OFFICIAL_MODEL_CATALOG.md)、[P5开发扩展](docs/protocols/M1_LOCAL_CLOUD_WORKFLOW_PROTOCOL.md)。
原离线入口与测试继续保留，以下为其兼容说明。

## 原离线装配（兼容与冻结接口回归）

原有显式 **Windows 本地离线装配**：实际调用已提交的 M2 CLI，
视觉模型使用 fixture；M3 默认模板 Story + silent 音频 + 真实 ffmpeg 视频。
可将 TTS/LLM HTTP 客户端接入本地服务做接口验收，但这不证明真实模型质量。
冻结 Worker 禁止真实后端，不能把 fixture 切换成 real 来冒充验收。

## 安装和启动

Windows CPython 3.12、ffmpeg/ffprobe、可读取的中文字体是明确依赖。
在仓库根目录安装；不依赖任何开发机的绝对路径或未提交测试模块。

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r orchestrator/tests/requirements-unified-test.txt
$env:FFMPEG_PATH = 'C:/tools/ffmpeg/bin/ffmpeg.exe'
$env:FFPROBE_PATH = 'C:/tools/ffmpeg/bin/ffprobe.exe'
$env:VIDEO_FONT = 'C:/Windows/Fonts/msyh.ttc'
$env:DATA_DIR = './local-data'
$env:M1_DEPLOYMENT_ENV = 'local'
$env:M1_LOCAL_RUNTIME = 'offline_fixture'
.venv/Scripts/python -m uvicorn orchestrator.local_runtime:create_local_app --factory --host 127.0.0.1 --port 8000
```

不要把该服务绑定公网。一次数据目录只允许一个 HTTP 服务实例；原默认
`orchestrator.main:app` 继续保留冻结 MOCK API 联调用途，不代表三模块正式装配。
数据目录中的 `.m1-state`、`.orchestrator` 是本地状态，不能发布为静态目录。
`.m1-state/test-key.seed` 仅是离线测试密钥，绝不能当生产身份或 KMS 使用。

## 调用和产物访问

使用原 `/api/v1/capture` 上传图片，再用 `/api/v1/generate` 创建任务，轮询
`/api/v1/jobs/{job_id}`。M1 真正启动 M2 子进程，经 Gate、Session 后交给 M3；
M3 不读取本地 OCR/VLM 输入作为授权替代品。

任务返回的私有 Story / Video URL 需要 M1 短期凭据。可信本机操作者在相同
`DATA_DIR` 与显式离线配置下运行：

```powershell
.venv/Scripts/python -m orchestrator.local_runtime asset-credentials --job '<实际job_id>'
.venv/Scripts/python -m orchestrator.local_runtime totals
```

前一个命令输出每个 Asset ID、SHA256、URL 和请求 Headers，包含短期测试凭据，
不要复制到公开日志。HTTP 不提供匿名发 Token 接口。Story 内音频 URL 的别名同样
经过同一 M1 Authority 验证，不会裸挂本地文件。缺少授权仍拒绝读取。

重启恢复页面和 Job 查询；中断任务记为 cancelled，不自动重投。财务状态以 M1
为准：业务 done 不等于账单 SETTLED。未决 UNKNOWN 持续保留预算并拒绝 Replacement；
不会为了演示清空账本。真实供应商证据尚未接入，离线签名适配不能冒充真实结算。

## 配置语音及故事服务

`M3_TTS_ENGINE=silent|http`；http 需要显式 `M3_TTS_HTTP_URL`，可选
`M3_TTS_API_KEY`。`M3_LLM_BASE_URL` / `M3_LLM_MODEL` / `M3_LLM_API_KEY` 显式传给
成员三配置，不再被适配层清空；未配置时仍使用模板，不伪装成模型。
本离线装配只允许 loopback 服务，禁止通过 offline_fixture profile 调用外部收费服务。
TTS HTTP 音频经过 MIME、格式、真实解码及 SHA 校验后才发布。接口测试的本地 sine
音频只证明客户端与合成链路，不是可验收的真人语音质量。

## 验证

```powershell
.venv/Scripts/python -B scripts/run_full_offline_acceptance.py --phase full --output 'C:/evidence/new-run'
```

输出必须在源码工作树外，工作树必须 clean 且已经提交。已有输出日志拒绝覆盖。
每组保存 Commit、Git Status、全部 tracked 文件前后 SHA、命令、日志和 JUnit。
原九组团队 CI 不降低，新 Unified Acceptance 在 Windows 对准确 PR Head 执行完整
M1/M2/M3、协议、安全、真实 TCP HTTP、重启及媒体链；CI 要求零 skip。
源树与测试集有重叠，不把各组数量相加成项目总通过数。

详见 [架构与边界](docs/UNIFIED_ARCHITECTURE.md)、[独立 M3 审查](docs/M3_UNIFIED_REVIEW.md)、
[来源及兼容](docs/UNIFIED_PROVENANCE.md)、[部署限制](docs/UNIFIED_DEPLOYMENT.md)、
[协议注册表](docs/protocols/PROTOCOL_REGISTRY.md)。GitHub Actions 保存原始验收工件。
尚有真实 OCR/VLM、供应商结算、正式签认/审核条件；没有满足这些条件前不合并 dev，
不自动修改 main/dev 保护、不强推、不把 CI_ONLY 标成 PRODUCTION_READY。
