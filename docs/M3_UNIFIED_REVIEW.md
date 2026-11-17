# M3 独立技术审查和整改

审查基于远端 PR #10 `ebcaef48f4e8f1ab8c6eee978b4eab4ff405b22b`、v2
`af7a128e77490bdbd2d667eb3720102e23355a6b`，以及本地R4安全候选。

|发现|整改和证据|
|---|---|
|PR10五个M1测试收集失败|该Head缺真实integration_reference包；保留原日志，集成M1完整Runtime与依赖，既有五个测试不删不skip|
|适配层强制silent，忽略配置语音服务|增加显式M3_TTS配置，实际TCP HTTP测试验证请求、原音频字节、解码、合成及授权访问；不是仅检查调用次数|
|配置LLM路径被清空|显式M3_LLM配置进入成员三Settings，缺配置标模板；离线装配只允许本地服务，真实质量未验证|
|无M1 Session可进入固定视觉演示|限制为local+offline_mock；dev/production/blocked请求无M1一律拒绝，目标私有文件不打开|
|OCR/VLM stage先宣告完成，M1会话到Story才创建|将M1监管的真实CLI/Gate/Session前移至输入阶段；M3只拿授权bytes，校验捕获原图SHA|
|最后复制缺少独立的权威撤销复核|新增M1-owned发布事务，复用原_bound/current/grant/upstream；测试在render后撤销但Job未取消时仍不可发布|
|只有测试装配，没有可启动统一服务|新增显式Windows离线factory入口、声明依赖、操作说明；HTTP测试不注入测试rig|
|Job/页面只在内存|仅新装配启用原子检查点，重启查询恢复；活动任务不自动复跑，UNKNOWN预算不释放|
|取消期间M2进程未收到M3标志|支持新factory取消回调，M1撤销上游并负责终止/回收；M3仍等待真实Future结束才清理|
|同Job多页相同音频路径可造成别名歧义|用原访问token绑定的Asset ID解析，再核对path/project/job，保持同Authority授权|

保留必要的成员三实现与历史API，因为已有原255项和媒体/安全测试验证了其可复用部分；
没有保留一套新的替代Story/TTS/Video算法。LLM质量和真实TTS音色需要真实模型环境及语料
验收，本轮本地HTTP音频是明确的接口夹具。模板输出不作为儿童内容质量的最终签认。
取消后等待真实线程/子进程，UNKNOWN预算不能以cancel/force为由释放；部分媒体失败继续按
冻结no_audio/no_video降级，不伪造全绿。最终独立审阅和正式P1–P4冻结仍待完成。
