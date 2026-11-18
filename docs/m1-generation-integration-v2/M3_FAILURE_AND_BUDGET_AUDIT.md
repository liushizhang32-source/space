任务 M1-M3-IMPLEMENTATION-001；2026-11-16，Asia/Hong_Kong。

状态：CI_ONLY / M1_SIGNOFF_PENDING / ARCHITECTURE_DECISION_REQUIRED。

# 失败、预算与回执

| 边界 | 预算处理 | 回执/发布 |
| --- | --- | --- |
| 授权读取/原图不一致/Story/TTS安全失败 | 确认未提交，可 release | blocked/failed；release_error 独立保留；不发布 |
| Story文件缺失/OSError | release RESERVED | 固定公共错误文本；内部记录异常；保留 attempt |
| 读取Story后、submit前取消 | release RESERVED | cancelled 内部回执；不提交、不发布 |
| submit开始后响应失败/异常 | submission_started=True；不 release | UNKNOWN + attempt/request_id，对账；不自动重试、不换键 |
| submit成功后TTS产物检查/视频安全blocked/发布完整性失败 | 不 release，M1可信对账 | 元信息不丢失；不向公共响应新增预算字段 |
| 提交后cancel/force | drain真实worker；UNKNOWN继续持有 | 禁止旧任务发布；保留预算与hash |
| release拒绝 CORRUPT/MAINTENANCE/CLOCK_ROLLBACK | M1ReleaseError | budget_release_error、ERROR日志、内部对账队列与JSONL |
| release意外异常/响应丢失 | 不假定释放成功 | RELEASE_UNCERTAIN；保留预算错误，不吞BaseException |
| 已撤销/换代 | TOKEN_REVOKED/STALE_ATTEMPT 幂等终态 | 延续既有M1会话语义 |

PageRunResult.to_dict() 明确保留 generation_mode/error/status/budget_release_error/m1_attempt_id/m1_result_sha256；视频 blocked 直接返回同样保留元数据。

Session 在调用 submit 前设置 submission_started，响应丢失时即使 submitted=False，收尾也不会错误释放。不可再对该 Session submit；查询/对账属于 M1，M3 没有 settle 方法、不重新签Token、不重造 lineage。request_id 由一次 job/page 稳定生成，内部不自动重试。M1 authority 对未决 attempt 的准入仍是最终裁决。

Member3Jobs 在 worker drain 后统一收尾，m1_receipts 保存每job/page内部回执；m1_reconciliation 保留释放失败或 UNKNOWN，并将所有回执持久写入私有 .member3/m1-reconciliation.jsonl。业务 error 只更新 error，不覆盖预算错误。审计写入失败会记录异常且保留内存队列；正式M1持久对账服务接管未被宣称完成。

公共 Job/PageData/冻结Schema没有改动，内部预算字段未新增到公共响应。普通业务API error沿用既有字段，Story读取异常使用固定消息防止路径泄露。私有审计不记录 service token/attempt token。

修复过程原始证据保留：第一次 focused 运行因审计dict重复page_id导致终态丢失，手动终止该诊断运行（无完整JUnit，不冒称通过）；第一轮完整回归222 PASS/2 FAIL，原因是本地测试Session不具备M1收尾方法；限定真实M1会话后原断言通过。最终227项JUnit独立保留。
