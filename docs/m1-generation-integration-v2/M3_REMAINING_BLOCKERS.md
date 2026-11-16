任务 M1-M3-IMPLEMENTATION-001；2026-11-16，Asia/Hong_Kong。

状态：CI_ONLY / M1_SIGNOFF_PENDING / ARCHITECTURE_DECISION_REQUIRED。

# 剩余阻塞与交付边界

1. M1 Runtime 权威签认仍缺失。V0.8.1 源包可逐字节验证，但依赖 PR #11 尚未得到 M1 签认/合并。正式 feature 树没有复制 Runtime 三目录；它们仅出现在外部 CI_ONLY 装配目录。
2. M1/团队配置冲突 ADR-CI-001 仍存在。本次原始 M1 integration_reference 测试 77 项中 72 passed / 5 failed：deployed dev/production/unknown 的 offline_mock 应拒绝但未拒绝（3 项）；dev/production 的 blocked 模式缺 asset_mode（2 项）。完整日志/JUnit 保留在 BOUNDARY_LOG.txt / BOUNDARY_RESULTS.xml，未删除测试、未降低断言，未修改冻结 M1/M2 或擅自修改安全配置。
3. 正式 M1 Session provider 的所有权、Gate/SharedFences 替换规则及批准依赖装配尚待 M1。实现提供受控 app factory 的注入接口；CI fixture 用原版 M1 Authority/Gate/SharedFences/open_session 验证实际 HTTP Jobs 链。没有实现生产 Session 创建服务，不提供 HTTP token 输入或自造 Authority。
4. 团队既有 CI 的 member134 原始计数与 Runtime 导入需在依赖签认后适配。当前普通 dev/feature 本身不含 M1 库，不能直接声称新增 M1 测试在团队生产树可运行；此次隔离装配与日志不冒充远程 GitHub CI 通过。
5. Production HTTP、身份/KMS、可信结算/持久化对账消费者、生产部署和 DRAFT 审批均不在本任务中被激活。内部 reconciliation 字典与持久 JSONL 提供回执入口，正式 M1 对账 worker/处理人接管仍需 M1。

依据用户的“外部依赖无法完成，提交已完成部分和精确阻塞报告，不得为了创建 PR 绕过阻塞”，本次提交独立 M3 实施代码与真实证据，不创建 PR，不合并、不发布、不声称 Production Runtime Ready。功能分支推送结果另见 GIT_DELIVERY.json。下一步由 M1 签认依赖并解决 ADR-CI-001，再跑同一真实链和 CI；不能把 227 项绿色替代这 5 项失败。
