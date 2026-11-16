任务 M1-M3-IMPLEMENTATION-001；2026-11-16，Asia/Hong_Kong。

状态：CI_ONLY / M1_SIGNOFF_PENDING / ARCHITECTURE_DECISION_REQUIRED。

# M1 Runtime 来源与装配

团队 remote：https://github.com/liushizhang32-source/space.git。Git fetch 因连接重置失败；GitHub API branches 独立读取确认 dev 为 0dc2844f910d0e37ae3ef0253d7838dea1f61bfb，feature/m1-generation-integration-v2 不存在，因此由该最新已验证 SHA 创建独立 worktree/分支，未覆盖已有工作。原 M3 709155cb4eb146c298434a1c01c11de9c7e3e96d 已在该 dev 祖先链，参考候选 ebcaef48f4e8f1ab8c6eee978b4eab4ff405b22b。

来源 ZIP：space-m1-m2-v12-supervisor/reports/M1_DOC_P2_20261114/M1_OFFLINE_INTEGRATION_KIT_V0_8_1.zip。

- ZIP SHA256：5cfbbbebbdcb16aefb52c0e634291f06d929c5d778594f74cd5e9c0df957dad1。
- Manifest SHA256：1b246055eb49630cee0ae86173028635dc8c79f8d94198a67c225efaf78ff0ab。
- 本次核验 ZIP CRC、201 个 manifest 条目与全部文件 SHA256，29 个 Runtime 文件：integration_reference 6、vision_supervisor 20、poc_security 3。
- 完整逐文件指纹：runtime-source-verification.json。源码工作区 HEAD 不能代表这些原为 untracked 的 Runtime；以已锁定 ZIP 为来源。
- 不纳入旧 poc_security/authority.py、gateway.py、binding.py、ledger.py 等包外文件，未从历史版本补齐第二套 Authority。

前置交付依据：reports/M1-M3-RUNTIME-001/M1_M3_DEPENDENCY_AUDIT.md、M1_CI_RUNTIME_HANDOFF.md；依赖草稿 PR #11 的版本 085a3069a31ef28a2716986b879f7707530b702d。它们明确 M1_SIGNOFF_PENDING，本次未把候选署名冒充批准。

因此停止正式 Runtime 装配。新功能分支没有 Runtime 三目录；只在外部 CI_ONLY 副本内按 ZIP bytes 装配。使用相同 Authority/Gate/SharedFences，不改核心、Token 或账本。生产代码及迁移后的 vendor 测试统一全限定 orchestrator.vendor.member3_v116.agents.generation.*；没有 sys.path 拼接或 sys.modules 别名。团队旧 conftest 的原有测试路径设施未改动；新 M1 fixture 去除了旧 sys.path 注入。

依赖环境使用既有受锁定 CI 测试环境（CPython 3.12.14，pydantic 2.14.1，cryptography 50.0.2，rfc8785 0.1.4），不把它等同独立包 2.14.3 环境。新回归以真实离线 Authority 验证消费者；77 项额外 Runtime 边界测试明确保留 5 项失败。依赖声明和包来源来自 M1；本任务没有为测试修改 M1 的配置规则。

无生产凭证、无收费模型调用。测试进程及其子进程继承 sitecustomize 网络审计，远程 DNS/connect 拒绝，只允许本机 loopback；显式 silent TTS、模板 Story、真实本地 ffmpeg/ffprobe。
