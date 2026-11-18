# 统一装配架构

2026-11-18增加[真实模型工作室](REAL_MODEL_STUDIO.md)，独立入口`orchestrator.bailian_app`。
以下保留原离线装配及其冻结接口边界；不把其中的fixture/silent当成真实模型。

```mermaid
flowchart LR
 UI[本机页面 / 上传PDF与多页] --> M1[原M1 Authority / 统一150元 / Token与计划]
 M1 --> OCR[真实本地PaddleOCR与OpenCV]
 OCR --> VLM[云端Qwen3-VL / 冻结C1-C2]
 VLM --> Story[Qwen-Plus / 全书故事与分镜 / C3]
 Story --> TTS[CosyVoice3 / 单一官方女声]
 TTS --> Wan[Wan I2V / 按实测配音时长 / 持久Task ID]
 Wan --> Media[FFmpeg连续时间轴 / 中文字幕 / 完整解码]
 Media --> Pub[M1同库私有资产 / 会话授权 / 播放下载]
 M1 --> Journal[原锚保护cloud_documents / UNKNOWN / 不重放POST]
 Q[当前页文字或语音问题] --> ASR[可选Qwen-ASR]
 ASR --> Agent[Qwen-Plus Agent]
 Agent --> TTS
```

新profile复用原Authority的授权、账本、资产BLOB、签名/锚和WindowsTree进程监管。
原`settle`不接受dashscope的fixture账单；实际账务保持UNKNOWN。新元数据没有第二套权限或余额。
输入开始Attempt后不可改排；引用准确的book/job/generation/input_revision和页SHA。详见P5。

```mermaid
flowchart TD
  Capture[冻结 Capture HTTP] --> Store[M1持有的图片与页面元数据]
  Store --> Owner[OfflineAssembly / 唯一服务实例]
  Owner --> M2[DurableSupervisor启动真实M2 CLI / fixture模型]
  M2 --> Gate[M1 Gate / hash / identity / SharedFences]
  Gate --> Session[M1授权Session / 原预算账本]
  Session --> M3[Story / TTS / Video]
  M3 --> Permit[M1最终发布事务]
  Permit --> Assets[同Authority登记私有资产]
  Assets --> HTTP[有凭据的资产HTTP访问]
  M3 --> Jobs[Job状态与检查点]
  M3 --> Observe[M3回执仅为观察线索]
  Evidence[签名Offline Settlement证据] --> Consumer[M1对账消费者]
  Observe --> Consumer
  Consumer --> Ledger[原Authority.settle / UNKNOWN保护]
```

原离线装配入口是`orchestrator/local_runtime.py`；不导入测试 rig。
`tools/runtime/m2_entry.py` 只将已提交 M2 包加入隔离解释器，再调用其原 `main`，
不伪造输出、不重建 Worker。真实后端不在冻结 V1 Worker 的许可范围。

M3 输入从 M1 Session 授权读取；授权前不读取本地 OCR/VLM 或捕获图片作为替代。
生成前保留捕获图片 SHA，和 M1 已授权原图核验。Story 在 M1 提交后不改字节。
TTS 只执行一次，后续 Jobs TTS stage 验证；Video 深度解码与元数据检查后发布。
M1 原 `_bound` / grant / token / current / upstream fence 验证和最终复制位于同一
Authority 事务内，防止撤销与发布之间的跨进程窗口。没有第二套权限系统。

私有资产读取前后授权、文件 SHA、Windows 固定句柄继续生效。静态别名先从令牌
选出精确 Asset ID，再核对 job/project/path，最后仍调用同一个 M1 `read`。
同一 Job 多页共享音频名也不发生跨 Attempt 混用。生产多实例/分布式存储未宣称完成。

Job 和页面检查点是本地业务状态，不是资金账本。重启中断状态转 cancelled，不做
自动重投或预算退款。M1 UNKNOWN/SharedFences/durable stage 状态保持原语义。
唯一发布指的是单服务实例、原 current/fences 和同步最终发布；文件复制不是跨文件
事务，异常可留未登记私有碎片，但不会发有效新 URL，不能作为已完成产物访问。

原 MOCK 分支为公共 API 回归保留；旧非 M1 的 M3 演示仅允许显式 local+offline_mock。
这是历史兼容用途，不能在 dev/production 或 blocked 模式绕过 M1。
