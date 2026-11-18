# P5：本机真实模型工作流扩展 1.0

Status: PROPOSED

仅实现用户 REAL-MODEL-FINAL-INTEGRATION-001 明确授权的本机开发接入与离线验收，不激活 Generation 旧 DRAFT，不修改冻结 M1/M2 V1.0 的102个文件，不签认生产身份、KMS或真实账单。P1—P4 保持 PROPOSED。

|条款|规范|实现 / 验证|
|---|---|---|
|P5-01|默认 Authority 继续拒绝云端 Provider。仅可信本机装配显式启用 local_cloud；生产构造仍拒绝。|integration_reference/authority.py；test_cloud_profile_is_explicit_and_does_not_activate_original_runtime|
|P5-02|CloudWorkflowAttempt 是整本书执行计划的 Attempt，与旧 Story GenerationAttempt 不混用。result_sha256 绑定批准计划，不冒充最终故事 SHA。最终媒体另行登记。|bailian/authority.py、engine.py；单/多页 E2E|
|P5-03|始终调用原 Authority.begin/submit/cancel/totals。全部模型、任务、问答共享固定项目及15000分上限。不得另建余额表。|test_second_job_cap_cannot_multiply_project_budget|
|P5-04|报价绑定书页 SHA、顺序、输入版本、模型、地域、价格目录和到期时间。必须有 Key、素材云端传输同意、账户权限确认及费用上限。|test_dispatch_requires_key_consent_exact_quote_and_cap|
|P5-05|先预留；本地失败且尚未提交时仅由原 cancel 释放 RESERVED。在首个收费请求前，同一 M1 事务冻结计划并持久记录 DISPATCHING，再发请求。|test_local_failure_before_first_paid_dispatch_releases_only_reserved|
|P5-06|提交后即 UNKNOWN，原 submit 的不可释放语义不变。HTTP错误、取消、用量、费用估算均不是账单。fixture结算和fixture证明不得套用到dashscope Attempt。没有可信真实账单适配器时不开放结算HTTP。|test_cancel_pending_wan_waits_and_cannot_release_unknown；test_cloud_attempt_cannot_use_fixture_billing_or_provenance|
|P5-07|每个付费步骤具有持久唯一键。POST不自动重试。DISPATCHING/UNKNOWN 没有可用结果时阻止重放。已获得 Wan Task ID 只轮询/下载原任务。|test_uncertain_paid_post_never_retries_on_resume；test_actual_wan_task_id_recovers_without_paid_resubmission|
|P5-08|全部素材、产物及日志元数据沿用原 Authority 的 grants、tokens、current、assets、签名、共享锚；cloud_documents 是同库受锚保护的工作流元数据，无第二套授权表。授权后才选择返回字节；不挂载私有目录。|test_anchor_detects_journal_tampering；HTTP私有字节与静态绕过测试|
|P5-09|M1 可信续期保持原身份、输入 SHA、current fence、grants、key 状态。仅过期可续，撤销不可续。启动时不重新授予已撤销权限。|test_lease_renewal_preserves_identity_and_fences；test_revoked_lease_cannot_renew_after_expiry|
|P5-10|开始 Attempt 后整本输入不可改排；新版本须重新上传、报价。C1/C2/C3 均使用未改动的冻结业务 Schema。父任务撤销同时阻断问答派生产物。|test_book_input_revision_is_frozen_after_attempt；test_voice_question_uses_real_decoding_and_mock_asr_then_agent|
|P5-11|取消停止后续付费提交，等待当前网络请求和本地进程树退出；Wan仅PENDING可远端取消，不声称RUNNING已取消退款。关停保留原Task ID供恢复。|原 M1 WindowsTree；pending取消与重启恢复测试|
|P5-12|Studio 使用 HttpOnly/SameSite=Strict 本机所有者会话、CSRF、Origin/Host、CSP及请求大小限制。Key仅后端内存/显式环境变量，不进日志、Git、localStorage或业务响应。|test_key_never_echoed_or_persisted_to_authority_or_frontend；HTTP安全测试|
|P5-13|本地 OCR、图像和媒体必须真实执行。云端Mock仅限显式测试注入，UI无法切换到Mock；费用与真实模型验收分开。|test_native_and_browser.py；native工厂参数不经HTTP暴露|
|P5-14|C1/C2输入归属、结构化安全结论和逐页完整性必须校验。视频必须来自Wan，不得以静态图或静音替代。CosyVoice音频要实际解码、非静音；产物完整解码通过才发布。|test_unsafe_or_wrong_identity_never_publishes；test_local_media_rejects_silence_and_nonvideo|
|P5-15|Studio为独立本机入口，原成员四文件及A4/A5主应用接口不覆盖。新问答接口采用同意/预算前置流程；Qwen-Plus不假装接受音频，语音由qwen3-asr-flash转换。|docs/REAL_MODEL_STUDIO.md、OFFICIAL_MODEL_CATALOG.md；voice question测试|
|P5-16|准确提交上执行本地和GitHub回归，保存SHA、XML、日志、截图和输入。真实云端与音色质量仍WAITING_FOR_KEY，PR保持Draft，PRODUCTION_READY=NO。|scripts/run_real_model_acceptance.py；独立CI|

本机开发签名材料仅支撑持久身份，不能称为生产KMS。数据库和锚同时被整体回滚的风险仍沿用原Runtime说明；没有可信外部高水位时不宣称生产抗回滚。

账单接管责任仍由M1/账户管理员承担：DashScope响应usage只有用量，API Key本身不保证提供可验证的人民币账单。当前实现有意保持UNKNOWN，原离线结算器禁止结算dashscope Attempt。后续接入官方可信账单来源必须独立审核，不能人工填一个费用就调用settle。
