# 启动、恢复和正式交付限制

2026-11-18新增本机真实模型开发入口：`scripts/install_all.ps1`、`scripts/start_system.ps1`，
仅监听127.0.0.1:8765。所有工具在隔离环境，固定跨目录M1本地账户，Key仅内存、费用上限显式确认。
操作与恢复见[工作室说明](REAL_MODEL_STUDIO.md)。不部署生产，真实云端质量待Key后验收。

原README中的Windows本地离线启动必须显式设置M1_LOCAL_RUNTIME=offline_fixture、
M1_DEPLOYMENT_ENV=local；内部强制blocked资产模式。不能以此配置部署生产或公网服务。
Linux默认API/成员三媒体回归继续用于兼容测试，M1冻结固定句柄和Job Object运行时仍需Windows。

依赖在requirements-unified-test.txt及原模块requirements中声明。ffmpeg、ffprobe、中文字体
均通过环境变量显式配置；脚本不再回退到开发机reports/.venv等路径。Windows CI从官方
固定Commit下载免费Noto字体并校验SHA；Chocolatey提供ffmpeg，原九组CI媒体探针保持。

数据目录包含捕获图片、业务状态和M1权威SQLite/retained.anchor。保留整个目录原位重启，
不移动单独数据库绕过路径绑定。不能同时运行两个HTTP实例。重启时业务活动Job记录取消，
提交后Attempt转UNKNOWN；没有可信证据就继续held。原子业务JSON不是可信资金凭证。
真实供应商账单、生产身份/KMS、高水位恢复服务、分布式存储和真实模型合同未启用。

GitHub统一PR指向dev；main/dev保护不修改。API返回protected=true，但保护细则GET当前404，
不能据此推断可绕过required reviews。正式D1/D2/D3、PROPOSED审核/冻结、真实OCR/VLM质量
与结算仍是合并条件；没有满足条件就保持Draft，不合并。需要明确PR、Head和目标的最终审核。

CI测试类型：原Schema/API/M1/M2/M3/Orchestrator/生命周期/并发/HTTP/边界完整执行；新统一
装配对准确Head运行真实TCP HTTP、配置服务、媒体、权限、重启、原生OpenCV及多页测试。
本地服务夹具和silent TTS不作为真实语音/OCR/VLM模型验收证据。所有失败日志保留。
