# 最终验收报告 — M1-M2-PROTOCOL-FINAL-001

2026-11-13（Asia/Hong_Kong）。**M1_M2_OFFLINE_PROTOCOL_V1.0 已按项目负责人本次明确授权形成唯一正式协议，FROZEN / OWNER_APPROVED。代码符合性：BLOCKED，未开展实际联调。**

|验收项|结果|
|---|---|
|A F01–F08|全部 OWNER_APPROVED，依据随包原始执行令及 Hash；不是伪造个人数字签名。|
|B 三项补充|文件安全/TOCTOU、确定性最终消息JSON、跨进程持久化两次Attempt已全部进入正式规范和Gap/静态测试。|
|C 协议冻结|FROZEN；原草案/决策包保持原样，正式目录是唯一新规范位置。|
|D 范围|只限Fake/Stub离线接口；真实模型/收费POC/生产/dev均不授权。|
|E M1差异|见Gap G01–G10及G15/G16/G17：strict Gate/Result、同句柄TOCTOU、持久Stage总计数、精确2004子类型等仍需整改/证据。|
|F M2差异|见G11–G18：输入严格性、旧binding/path边界、Sidecar额外键、模板hash、detail、错误策略、SDK路径/来源范围待验。|
|G Profile A后续条件|协议/整改基准已齐备；当前存在P1差异，尚不具备直接进入实际接口联调的准入条件。|
|H Profile B|独立保留，精确LEASE配对和FakeProvider，未拼接成统一链。|
|I 文件安全/TOCTOU|仅规范定义和静态案例；未证明真实OS属性实现，不冒称字符串/resolve检查已防竞态。|
|J 两次Attempt持久化|仅规范与纯参考状态演算；现M1每次run内存loop不满足跨进程总计数；LEASE台账也不等于该保证。|
|K JSON/静态验证|168项通过、0失败（75项契约/纯校验 + 93项正式补充/追溯检查）。正例接受、反例拒绝；不等于M2兼容或持久化行为测试。|
|L ZIP/Manifest|封包阶段检查CRC、路径、文件数、Manifest、内外原字节一致；精确结果由封包stdout返回。MANIFEST覆盖本目录全部文件，排除其自身，ZIP位于本目录外以避免自引用。|
|M 九个checkout|branch/HEAD/staged/unstaged/untracked快照保全；只排除本次精确新目录的新增untracked项。42份来源+批准附件Hash核对，旧决策包所有文件与三原ZIP保留。未声称逐字节扫描九个checkout所有其他未跟踪内容。|
|N 阻断|协议交付无阻断；代码符合性/文件OS安全/持久化计数/M5证据登记/实际M2入口兼容仍阻断执行准入。|

[完整Gap Register](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/CONFORMANCE_GAP_REGISTER.md) 含18项（16项P1接口准入差异、2项P2范围/来源限制）；不是发现16个已复现生产漏洞。P0事故在本静态范围未确认。每项区分源码事实与未验证能力，附责任方、后续整改、锁定证据及验收案例。

[SOURCE_LOCK.json](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/SOURCE_LOCK.json) 含43条（36份M1来源、6份M2归档源码/文档、1份用户批准令）；M2仍archive-only，checkout/branch/HEAD/tracked无证据则UNKNOWN/null，未冒用其他仓库。[SOURCE_TRACEABILITY.md](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/SOURCE_TRACEABILITY.md) 的42组行段根据锁定源码AST/文本锚重新生成。

输入完整性：决策ZIP `cb92be5dd6e1151ba5372d592ddd0f727a0ec1f14e8b062fa8a09b6666b6f61c`；M1 ZIP `8d79406711b4619e5c2dcd2e0917f6c6668e58cb5f8e08c626d9590ae5a61bcf`；M2 ZIP `3446b03bae8993a21e5cbff5f2ae639d8a4c43bfb08ca003f35b2957d6c1e505`。三包CRC、90/90/179 Manifest匹配，决策ZIP内外文件一致。没有同名旧包替代。

F05正式冻结输入是有序role/content列表，固定字段顺序无空白JSON、UTF-8无BOM、拒绝无效Unicode，不trim；不再沿用草案system+LF+user拼接。Hash只证明应用交给Adapter的消息，示例adapter_invoked=false。附件独立Hash及message_index关联；不声称provider/SDK内部未改变消息。

F04当前M5独立登记机制未完成，因此没有calibrated=true已验证正例，旧玩具校准示例未沿用。所有本轮估计示例calibrated=false；true自述/玩具证明被负例拒绝，未伪造M5评测。

2004规则：typed cancellation无retry；仅数值+transient不够。当前锁定M1没有精确子类型登记，本V1.0允许的2004标识集合为空，fail closed；后续增列须按签认变更流程。9001不重试的公共原文冲突保存在独立ERRATA，公共冻结原件未改。

验证限制：标准库校验器只支持实际生成Schema使用的keyword子集，并用上下文规则补充Hash/身份/路径/证据。不是独立完整JSON Schema引擎。Pydantic模型及Gate.refs仅纯校验，不导入/启动Supervisor、Worker、Core、供应商。新Schema与实际被验证的内部contract视图一致。持久化/并发/崩溃案例仅纯参考状态序列，未创建运行库或模拟真实M1重启。

输出仅本次新目录及同名最终ZIP。未安装依赖、未调用模型/供应商、未处理真实儿童绘本、未修改核心业务/公共Schema/API、未stage/commit/merge/push/创建PR。dev推送：无。到此停止，不自动开展后续接入。
