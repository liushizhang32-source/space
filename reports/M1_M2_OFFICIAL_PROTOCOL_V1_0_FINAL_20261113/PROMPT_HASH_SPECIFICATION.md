# 确定性 Final Prompt Hash

协议：M1_M2_OFFLINE_PROTOCOL_V1.0 · FROZEN · OWNER_APPROVED · 2026-11-13

仅限 Fake/Stub 离线接口。协议冻结不等于代码符合性验收；禁止本任务改核心源码、联调或发布 dev。


F05 正式输入是实际提交给 Provider Adapter 的最终有序消息列表，而非模板或 HTTP 请求。每项精确 {role, content}，两个字段按 role 后 content 固定顺序；本 V1.0 记录文本消息，role/content 都为有效 Unicode 原生字符串，role 是实际非空角色，不擅自改写或限制成不真实的角色。content 包含全部模板替换结果和实际文本参数，可空且不 trim、不做 NFC/NFD 规范化、不改变 CR/LF或消息顺序。

固定序列化：UTF-8，无 BOM；ensure_ascii=false，separators=(',',':')，allow_nan=false；数组顺序原样，字段顺序固定 role,content；采用 JSON 标准必要转义；拒绝未配对 surrogate、重复键、额外字段、非字符串、NaN/Infinity。输入列表非空。禁止用 system+LF+user 拼接替代列表（旧草案已被本批准补充取代）。对这些精确 bytes 做 SHA256 得小写64 hex，与 Sidecar.source.prompt_sha256 相同。

本 V1.0 附件通过独立受信 evidence manifest 记录 message_index、原始二进制 SHA256、媒体类型/引用和消息关联，不把二进制放入 prompt hash，也不添加 public C1/C2 或 Sidecar wire 字段。多模态非文本 content 形状当前未定义，不能静默转成字符串；如需新的 content 类型必须升版和重新签认。附件示例是合成 Hash bytes，不是真实绘本/可解码图片。

Prompt Template Hash 只哈希模板；Final Prompt Hash 只哈希上述最终消息；Provider Request Hash 若另记则哈希最终请求 envelope 并单独命名，不能代用。API Key/Token/Secret 不进入消息、证据或日志；测试不读取实际秘密。不得声称算法能识别任意自由文本中的秘密，调用方负责在提交前阻止秘密进入 prompt。

Hash 证明范围止于应用交给 Adapter 的精确有序消息。SDK 后续不可观察转换、Provider 内部处理和真实调用都不由此证明。fixture/stub 没有调用时标记 adapter_invoked=false；不得把保存消息示例当提交回执。prompt fixture 可复算，含尾部空格和换行以证明无 trim。现 M1 fixture hash(no model)、Gate 只验格式，M2 _prompt_sha256 哈希模板或 b'stub'，皆不满足正式语义，记 P1。


## 规范性授权与实现证据

[APPROVAL](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/OWNER_EXECUTION_ORDER.txt:1) — 已粘贴的文本.txt L1–884；SHA256 `a83d0b03e66c95279bdf11d511723c2eb1d710b4f5873f68c81365e651aa079f`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F01,F02,F03,F04,F05,F06,F07,F08

[SIDECAR](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/gate.py.txt:96) — orchestrator/services/vision_supervisor/gate.py L96–154；SHA256 `c041a06a1b5529c31ce9dd537a917472c74d2622c865b3e305b77b2d56f4e6cc`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F04,F05,F06

[M2_PROMPT](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:313) — src/vision/worker.py L313–318；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F05

[M2_RENDER](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/backends/qwen_vl.py.txt:244) — src/vision/backends/qwen_vl.py L244–250；SHA256 `a284b32db90843a70d9bdfc3927e0459cf6ffef1444551932a32964e9b71fa19`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F05

[FIXTURE](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/tests/fixtures/m1_vision_worker.py.txt:11) — orchestrator/tests/fixtures/m1_vision_worker.py L11–97；SHA256 `08532caad6169d0cbe2b66c1f0c6f4e3e04d19f64523a63973ff0518a267a084`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F03,F05,F07
