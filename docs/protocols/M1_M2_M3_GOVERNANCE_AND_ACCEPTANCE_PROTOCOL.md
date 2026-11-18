# P4 治理和验收

Version: 1.0
Status: PROPOSED
Date: 2026-11-17 (Asia/Hong_Kong)

本轮用户授权设计和离线实现；等待ChatGPT独立审核后冻结。冻结公共API和M1/M2 V1.0优先。本文件不是生产许可。

## P4-01 责任

M1安全/预算/资产权威，M2视觉Worker，M3Generation/媒体；ChatGPT独立技术审核和正式合并审批。

## P4-02 协议版本

本P1–P4均v1.0/PROPOSED；实现离线候选获本轮用户授权，不等于协议已冻结或生产获准。

## P4-03 冻结

冻结M1/M2 V1.0原字节和Schema不变；生成的frozen副本102文件hash受测试保护。

## P4-04 修改审批

普通保守技术选择本轮自主；冻结冲突先记录不改；新PROPOSED由ChatGPT审查后方可升FROZEN。

## P4-05 Git

新独立worktree和功能分支；保护既有工作树。原协议补全轮次不push/PR；后续统一集成任务已明确授权推独立集成分支、创建指向dev的统一PR。该授权不允许强推main、修改保护、绕过审核或在门槛未齐时合并。

## P4-06 指纹

完整测试前后记录Commit、status、所有已跟踪源码和测试SHA256；clean已提交Head；结果与最终准确Head绑定。

## P4-07 JUnit

原case身份/数量/failure/error/skipped逐节点统计；保留原始日志与命令，合并JUnit不重复计数；重叠套件不相加成总通过数。

## P4-08 离线

统一scripts入口执行M1、M2、M3、P1/P2/P3/P4、联合与九组团队检查；fixture标签不改为real。

## P4-09 真实验收

真实模型/结算/身份/语料质量必须另有版本、授权、原始证据；未测明确NOT_RUN。

## P4-10 PR审阅

统一集成候选可建Draft PR供独立审核，绑定准确Head/Base/完整Diff和原始证据；真实验收/签认未齐时不能标合并就绪，不把旧CI归新Head。

## P4-11 合并

只有ChatGPT明确MERGE_APPROVED+PR编号+准确Head+目标分支，才执行对应合并；不伪造审核。

## P4-12 合并后

核查真实Merge SHA/目标分支/后CI/发布工件并更新MASTER；本轮不执行。

## P4-13 生产

MERGE_READY与PRODUCTION_READY独立；不得启用生产密钥/KMS/付费模型/部署，离线PASS不推导生产PASS。

## P4-14 测试向量

P4-V01注册表/版本/状态/schema/trace完整；V02冻结hash；V03源码MATCH/JUnit；V04不伪造批准，历史UNKNOWN3/1保持。
