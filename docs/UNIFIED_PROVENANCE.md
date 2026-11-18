# 版本来源和兼容边界

REAL-MODEL-FINAL-INTEGRATION-001从PR12准确Head
`aa78ed1f239316cf5dfb85a5b5273755a73dbacc`建立独立本地分支
`feature/real-model-final-integration-001`，非强制快进更新同一个PR12远端分支。
不覆盖旧unified工作树。M2原子树不变，复用其Qwen安全解析器；M1仍是原Authority，
仅显式开发profile与同锚日志等变更列入PROPOSED源码after SHA，原before和source-audit不动。
新增代码、协议P5、独立UI及新测试均独立列明；所有执行结果以本轮最终tested_commit为准。

2026-11-17从GitHub实际读取：

|来源|准确Commit|用途|
|---|---|---|
|最新dev|0dc2844f910d0e37ae3ef0253d7838dea1f61bfb|从该点建立integration/m1-m2-m3-unified-001|
|main|009d9ed7875ef71b95a6582600ecea89cc98cfa8|受保护，不修改|
|PR7已合并|709155cb4eb146c298434a1c01c11de9c7e3e96d|既有M3集成基础，已在dev历史|
|M1 PR11 Draft|0e69fdf4a501f7c9d9003c8ac1735ce17bc10222|M1 Runtime002、原29文件/完整242来源；不是正式签认|
|M2 PR9|418bd0acd22e842e86623ad20e275dc9b5102555|保持原paperbook-ai-m2子树，不重写其输出或测试|
|M3 PR10|ebcaef48f4e8f1ab8c6eee978b4eab4ff405b22b|旧版本与真实缺包CI失败历史|
|M3 v2分支|af7a128e77490bdbd2d667eb3720102e23355a6b|M1消费/Session/UNKNOWN等原255项来源|
|本地TTS修复|36675ccbbc34aed0a0cb49190de7e620da08281c|独立工厂blocked安全修复|
|R3离线集成|3c523be86ad2671b02b2a15898bf3d9741ead062|实际M2进程与原联合44项|
|R4协议候选|5b83d9d400d7aae810694ba6d62c50d0615f2fb8|PROPOSED协议、对账、私有授权、Runtime 27+2精确变更|

没有盲合旧PR10覆盖v2。独立分支在最新dev上合入审查过的R4历史，再按当前任务整改。
未提交的旧工作树不覆盖。M1正式source-audit和原SHA清单保留不动；两个已说明的
Runtime变更由独立PROPOSED/CI_ONLY清单绑定before/after；冻结102文件原字节与Git blob
有测试保护。新M1发布适配复用原Authority，不改预算/冻结wire。

公共API/Schema、原15000分上限、UNKNOWN未解决拒绝Replacement/保留预算不变。
原266历史XML的来源缺口仍UNVERIFIED；当前261和新增真实CLI测试是新证据。
原UNKNOWN四项3PASS/1FAIL=LEGACY_EXPECTATION_CONFLICT，不静默改绿。
运行结果以每次准确Head和前后源码SHA为准；旧提交的绿色CI不算新候选结果。
