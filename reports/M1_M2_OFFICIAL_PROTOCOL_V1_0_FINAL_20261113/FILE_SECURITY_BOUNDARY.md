# 文件安全与 TOCTOU 边界

协议：M1_M2_OFFLINE_PROTOCOL_V1.0 · FROZEN · OWNER_APPROVED · 2026-11-13

仅限 Fake/Stub 离线接口。协议冻结不等于代码符合性验收；禁止本任务改核心源码、联调或发布 dev。


F03 正式要求。M1 授权的根来源于受信 attempt 分配，不从 M2 自报路径推导。M2 输入 c1 必须是绝对的本次根/c1.json；图像也来自该根。先做词法校验（拒绝 ..、非法盘符/ADS、分配外路径），然后解析真实路径并按路径组件边界确认位于根；不可使用字符串前缀。

检查根及每一级组件，拒绝 symlink；Windows 拒绝未经授权 Reparse Point/Junction。本离线 profile 没有授权 Reparse allowlist，故所有遇到的 Reparse Point 均拒绝。不可把最终文件 is_symlink 检查替代祖先组件检查。输出不允许逃逸、路径碰撞或复用别的 attempt。

通过 OS no-follow/open-relative 或具有等效保证的受信句柄流程打开文件；验证句柄对应的普通文件身份（Windows volume/file ID 或 Unix device/inode）、授权根和组件，记录链接计数。硬链接必须证明单一受授权文件身份且 nlink=1；无法证明则拒绝/明确不支持平台。尽量同一已验证句柄读取与计算原始字节 SHA256；本 profile 必须消费这次读取的 bytes，禁止验证后重新按路径打开另一个文件。

读取前后核对句柄身份、大小/元数据及必要的父目录/路径映射，检测验证后替换；采用锁定、共享模式或等效机制防止写入与替换，证明 bytes 对应受信不可变快照。若属性不可靠或无法给出等效安全证明，fail closed，不声称 TOCTOU 已防护。路径验证、真实路径、句柄验证、原字节 Hash、TOCTOU 分为五层分别记录验收；Hash 只证明所读 bytes，不证明路径/来源可信。

C1/image Hash 与 snapshot/binding 相等，C1 五元与当前任务相同，OCR attempt/token 与 M1 快照台账相同；OCR/VLM 分别由 M1 创建新 identity，不强行要求相等。拒绝跨 page/revision/generation/epoch 或旧 OCR attempt。M2 单凭可整体伪造 JSON 无法自行认证新鲜度，依赖 M1 可信通道和台账。禁止扫描更新 C1、跨 attempt 取文件及 VLM 隐式补 OCR。

当前 M1 confined_file 有 resolve/链接/硬链接检查，但 stat 后 read_bytes 重新按路径读取，没有完整同句柄替换防护证据；M2 _resolve_c1_path 未证明授权根约束和祖先所有 Reparse/句柄/TOCTOU。均为 P1 实现差异。本文定义规范；本轮仅词法/静态案例，没有真实 OS 安全验收。


## 规范性授权与实现证据

[APPROVAL](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/OWNER_EXECUTION_ORDER.txt:1) — 已粘贴的文本.txt L1–884；SHA256 `a83d0b03e66c95279bdf11d511723c2eb1d710b4f5873f68c81365e651aa079f`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F01,F02,F03,F04,F05,F06,F07,F08

[PATH](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:175) — orchestrator/services/vision_supervisor/supervisor.py L175–193；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03

[REQUEST](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/supervisor.py.txt:263) — orchestrator/services/vision_supervisor/supervisor.py L263–415；SHA256 `a1eae38fa596af02d20430718721e15febbc625efffb79daf8412b22098adf35`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F02,F03,F07,F08

[BOUND_C1](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M1/orchestrator/services/vision_supervisor/gate.py.txt:29) — orchestrator/services/vision_supervisor/gate.py L29–44；SHA256 `c041a06a1b5529c31ce9dd537a917472c74d2622c865b3e305b77b2d56f4e6cc`；checkout `C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor`；branch `integration/m1-m2-v12-supervisor`；HEAD `0dc2844f910d0e37ae3ef0253d7838dea1f61bfb`；章节 F03

[M2_C1_PATH](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:470) — src/vision/worker.py L470–493；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F03

[M2_BINDING](C:/Users/16173/Documents/ChatGPT/人工智能+/space-m1-m2-v12-supervisor/reports/M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/locked_sources/M2/src/vision/worker.py.txt:496) — src/vision/worker.py L496–565；SHA256 `7d5c9ba336dda9c0d7af491cfb78d93c61302b8632d4bad2d81774a8dfed6ba0`；checkout `UNKNOWN / archive or user attachment`；branch `UNKNOWN`；HEAD `UNKNOWN`；章节 F02,F03
