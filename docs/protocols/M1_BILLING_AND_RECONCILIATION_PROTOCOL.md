# P1 M1可信账单与预算对账

Version: 1.0
Status: PROPOSED
Date: 2026-11-17 (Asia/Hong_Kong)

本轮用户授权设计和离线实现；等待ChatGPT独立审核后冻结。冻结公共API和M1/M2 V1.0优先。本文件不是生产许可。

## P1-01 Attempt生命周期

复用原Authority：RESERVED→SUBMITTED，reservation同时UNKNOWN；可信整笔终态后DONE/SETTLED；RESERVED可CANCELLED/RELEASED。recover可将SUBMITTED标UNKNOWN。业务Job done不是财务DONE。

## P1-02 预算预留

原Authority.begin唯一分配，原总额15000 CNY分不变；整数，禁止按模块/币种分账绕限。

## P1-03 预算提交

原submit绑定原始Story bytes SHA256，幂等同字节；提交不是扣费，未知金额不猜。

## P1-04 预算释放

仅原cancel允许的RESERVED可释放；释放失败先对照权威状态；UNKNOWN绝不因M3取消/日志/错误文本释放。

## P1-05 UNKNOWN

保留全部原held；Replacement拒绝ATTEMPT_UNRESOLVED；禁止换request_id绕过或自动重投。

## P1-06 可信证据

本版本只实施显式local/offline_test的OfflineSettlementAdapter；使用M1现有OfflineKMS签名域M1-OFFLINE-SETTLEMENT-v1，密钥不交M3。真实供应商验证是外部依赖。

## P1-07 JSONL

每行严格UTF-8 JSON，重复键/浮点/未知字段拒绝；完整换行后才消费，尾部半行留待追加；上限64KiB/行，超长或截断前缀检测后fail-closed。

## P1-08 标识和绑定

Evidence字段精确为version,mode,event_id,project_id,attempt_id,result_sha256,actual_fen,receipt_id,outcome；version=1.0，mode=offline_fixture，outcome=SETTLED；非空ID≤128，SHA小写hex64，actual原生int 0..15000。Signed envelope={payload,key_id,signature}。

## P1-09 M3线索

M3原回执形状保持；先验证Attempt ID/project/page/job/resultSHA与账本，budget_release_error作为待处理线索；M3日志绝不是签名结算证据。

## P1-10 幂等消费

持久inbox以event_id唯一，记录规范payload hash；同ID同hash重放，异hash冲突隔离且不改原事件；receipt唯一由原账本再防重。ACK仅为收件状态，重放仍由原Authority.settle核验资金终态，不能用ACK代替原账本。

## P1-11 冲突

错误project/attempt/resultSHA/签名/金额/receipt拒绝，原预算不动；日志审计原因不含token或原私有字节。

## P1-12 消费者

M1-owned ReconciliationConsumer先持久PENDING，再原Authority.settle，再ACK；不维护第二套资金余额。

## P1-13 恢复

崩溃在settle后ACK前：重放相同receipt/amount利用原settle幂等；PENDING重启recover，错误隔离；游标在事件处理完成后推进，重复读取安全。

## P1-14 游标

源ID由可信调用者指定；持久offset及已消费前缀SHA；文件前缀变化/截断拒绝重置。无可信证据仅观察并审计，不自动资金操作。

## P1-15 整笔终态

本新PROPOSED离线profile明确仅整笔最终结算：actual≤原reservation；原settle将reservation完整SETTLED，未使用部分不再held。不实施旧Generation DRAFT部分结算条款；旧DRAFT未激活，生产部分结算待另行版本。

## P1-16 审计/异常

inbox/游标/audit SQLite synchronous FULL；Authority自身审计和anchor保留。坏行隔离并记摘要；无账单保持UNKNOWN；运行时异常保持PENDING供恢复。

## P1-17 责任

M1签证据/消费/恢复；M3只产回执。M2无资金权限。PROPOSED实现仅离线，禁止自动接生产账单。

## P1-18 测试向量

P1-V01正常/重复；V02异值冲突；V03签名和SHA错误；V04 UNKNOWN无证据；V05 settle后崩溃恢复；V06半行/前缀篡改/释放失败。
