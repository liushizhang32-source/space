# M2 → M1 字段兼容对照表（V1.2.5，候选，待 M1 签认）

> 口径：左列是 M2 **实际输出**（本机运行 `docs/samples/sidecar_example.json` 可复核），
> 右列是 M1 Worker Handoff / Gate 的**期望**。状态只有三种：
> `一致`＝字段名与类型都对齐；`待确认`＝M2 已按 Handoff 实现但未经 M1 校验器实跑；
> `不一致`＝当前明确对不上，需要改某一方（M2 不会要求 M1 放宽 Gate）。

## 1. Worker 请求/响应（`m1-vision-worker/0.1`）

| 字段 | M2 实际 | M1 期望 | 状态 |
|---|---|---|---|
| `protocol` | `"m1-vision-worker/0.1"` | 同 | 一致 |
| `identity` 七元 | `job_id/page_id/generation_id/input_revision/epoch/attempt_id/fencing_token` 逐项回显 | 逐项一致 | 一致 |
| `stage` | `"ocr"` / `"vlm"` | 同 | 一致 |
| 成功 `code` | `0` + `artifacts` | 同 | 一致 |
| OCR 成功 `artifacts` | `{"c1": "json/<page>_ocr.json"}` | 只需 c1 | 一致 |
| VLM 成功 `artifacts` | `{"c2": …, "sidecar": …}` 恰好两项 | 恰好两项 | 一致 |
| 失败 | `code!=0` + `msg` + `transient` | 同 | 一致 |
| 400 类 | `1004`（超量）、`1006`（输入不合法） | Handoff 未定义 1006 | **待确认** |
| 安全 | `3004` + `detail.verdict` | 3004 = blocked | 一致（detail 为附加字段） |
| OCR 无字 | `code=0` + C1 `status=empty` | 允许 | 一致 |
| 不完整模型输出 | `2001` + `transient=true` + `model_output_incomplete` | 2001 可重试 | 一致 |

## 2. C1 输入（VLM 阶段）

| 字段 | M2 要求 | M1 是否提供 | 状态 |
|---|---|---|---|
| `inputs.c1` | 必填，相对路径 | Handoff 未定义该字段（原协议没有"上一阶段路径"） | **待确认（需 M1 加字段或约定固定路径）** |
| `inputs.c1_sha256` | 必填，64 hex，比对原始字节 | 同上 | **待确认** |
| `inputs.image_sha256` | 必填，比对原图字节 | 同上 | **待确认** |
| `page_id` 绑定 | C1 内 `page_id` 必须等于请求 `page_id` | — | 一致 |
| `input_revision` | 目前只在 identity 回显，**未参与 C1 校验** | 期望绑定 revision | **不一致（M2 未实现 revision 校验，需 M1 说明 revision 与 C1 的关系）** |

## 3. Sidecar（`vision_refs/0.1`，候选）

| 字段 | M2 实际 | M1 Gate 期望 | 状态 |
|---|---|---|---|
| 顶层 `schema_version` | `"vision_refs/0.1"` | 同 | 一致 |
| 顶层 `contract_status` | `"candidate"` | Gate 未识别该字段 | **待确认（附加字段是否允许）** |
| `identity` | 嵌套对象（7 项） | Handoff 写 identity 为 7 项 | **待确认（嵌套 vs 扁平）** |
| 顶层扁平镜像 | `job_id`…`fencing_token` 再写一遍 | 未定义 | **待确认（兼容用，若 Gate 拒绝未知字段需删除）** |
| `c2.sha256` | 原始落盘 C2 字节 SHA256 | 同 | 一致 |
| `c1_sha256` | C1 原始字节 SHA256 | Handoff 未列 | **待确认** |
| `source.component_mode` | `"real"` / `"mock"` | Handoff 写 `source_mode` | **不一致（字段名不同）** |
| `source.model_ref` | 如 `qwen2.5vl:3b` | 同 | 一致 |
| `source.prompt_sha256` | 有 | 同 | 一致 |
| `source.evidence_ref` | 等于 `c2.relative_path` | 同 | 一致 |
| `observations[].object_id` | 取自 C2，校验页前缀 | 同 | 一致 |
| `appearance.clothing` | 恒 `null` | 允许 `str \| null` | 一致 |
| `appearance.visible_features` | 恒 `[]` | 数组 | 一致 |
| `confidence` | `{value, kind, calibrated:false}` | 同形态 | 一致 |
| `confidence.kind` | `model_estimate` / `unavailable` | 同 | 一致 |
| `identity_status` | 恒 `unknown` | 仅 `unknown/ambiguous` | 一致 |
| `canonical_id` 等 | 未定义 | Handoff 明确 M2 不得定义 | 一致（未定义） |

## 4. 环境变量 allowlist

| 变量 | 用途 | 建议 |
|---|---|---|
| `VISION_OCR_BACKEND` / `VISION_VLM_BACKEND` | 后端选择 | 允许 |
| `QWEN_VL_BASE_URL` / `QWEN_VL_MODEL` / `QWEN_VL_API_KEY` / `QWEN_VL_MAX_TOKENS` / `QWEN_VL_TIMEOUT` / `QWEN_VL_EXPLAIN_TOKENS` | 模型端点与额度 | 允许（KEY 由 M1 注入） |
| `PADDLE_PDX_CACHE_HOME` / `PADDLE_OCR_MODEL_DIR` / `PADDLE_OCR_LANG` / `PADDLE_OCR_MKLDNN` / `PADDLE_OCR_ORIENTATION` / `PADDLE_OCR_DET_MODEL` / `PADDLE_OCR_REC_MODEL` | 本地 OCR | 允许 |
| `M2_MAX_OCR_BLOCKS` / `M2_MAX_OCR_CHARS` / `M2_VLM_EXEC` / `M2_BACKEND_CANCEL_URL` | 限额与执行模式 | 允许（D02 前用默认值） |
| `VISION_EMIT_EXTRA` | 追加 `producer/error` | **禁止**（会让 C1/C2 多出未知字段） |
| `HTTPS_PROXY` / `HTTP_PROXY` | 出网 | 由 M1 决定 |

## 5. 需要 M1 明确答复的四个问题

1. VLM 阶段如何拿到上一阶段 C1？是加 `inputs` 字段，还是约定固定相对路径？
2. `identity` 在 sidecar 里应该是嵌套还是扁平？Gate 是否拒绝未知字段（`contract_status`、扁平镜像、`c1_sha256`）？
3. `source_mode` 的准确命名与取值集合？
4. `input_revision` 与 C1 的绑定规则（C1 里没有 revision 字段，M2 只能校验"文件名 + page_id + sha256"）。

## V1.2.6 追加：clothing 与 c1_binding 映射（待 M1 确认）

| 字段 | M2 输出（V1.2.6） | M1 Gate 期望 | 状态 |
|---|---|---|---|
| `observations[].appearance.clothing` | 默认**省略键**（未知）；识别到则写字符串 | 不接受 `null` | 待确认“缺省=未知”是否合法 |
| 同上（显式 null） | `M2_SIDECAR_CLOTHING=null` 时写 `null` | 当前不接受 | 仅作兼容预留，默认不启用 |
| `source.component_mode` | `fixture` / `stub` / `real` | 同名三态 | 已对齐，待确认枚举 |
| `inputs.c1` | 允许绝对路径（推荐）或相对路径 | 基准为绝对路径 | 已支持绝对路径 |
| `c1_binding` | 顶层对象：`job_id/page_id/generation_id/input_revision/epoch/attempt_id` + `c1_sha256` | 基准同名 | 待确认字段名与嵌套位置 |
| identity | 请求顶层七元、result 嵌套七元、sidecar 顶层七元镜像 | 同名 | 已对齐 |
| revision 绑定 | C1 原始字节 SHA256 + job/page/generation/revision/epoch | 同名 | 已实现 |

需要 M1 回答：①省略 `clothing` 键是否等于“未知”且被接受；②`c1_binding` 的准确字段名/位置；③`inputs.c1` 是否强制绝对路径；④`component_mode` 枚举是否完全一致。

已由证据包（HEAD `0dc2844f…`）核定，V1.2.6 末版结论：

| 字段 | M2 实现 | M1 实际 | 结论 |
|---|---|---|---|
| `inputs.c1` | 绝对路径（`worker.py:470`） | 绝对路径（`supervisor.py:283`） | ✅ 对齐，相对路径仅兼容 |
| `c1_binding` | `{identity: 七元, sha256, image_sha256}`（`worker.py:496`） | 同名嵌套（`supervisor.py:283`） | ✅ 对齐；只比共享五元 |
| `image_sha256` | 请求顶层优先（`worker.py:291`） | 请求顶层（`supervisor.py:274`） | ✅ 对齐 |
| identity 结构 | 请求顶层 / result `identity` / sidecar 顶层 | 同三处（`gate.py:101-103`） | ✅ 对齐 |
| `source.component_mode` | `fixture`/`stub`/`real`（`worker.py:327`） | 同名三态（`gate.py:115`） | ✅ 枚举一致，判定口径待确认 |
| `observations[].appearance.clothing` | 默认省略键；显式字符串才写 | `clothing` 若存在必须是 `str` | ⚠️ 省略键合法；"缺省=未知"语义待联合签认 |
| `confidence.calibrated` | 恒 `false`（布尔） | 必须 `bool`（`gate.py:146`） | ✅ 对齐 |
| `c2.relative_path` | 强制 `json/<page>_vlm.json`（`worker.py:775`） | 同名固定（`gate.py:111`） | ✅ 对齐 |
| `prompt_sha256` | real：SYSTEM+USER 拼接；fixture/stub：常量 | 64 hex 字符串 | ✅ 格式对齐，语义待确认 |
| `evidence_ref` | C2 相对路径 | 非空字符串 | ✅ 格式对齐，语义待确认 |
| `contract_status`/`c1_sha256` 等额外键 | 保留 | Gate 不拒绝未知键 | ✅ 不影响放行 |

仍需 M1 回答：①"省略 `clothing`"是否作为最终"未知"语义；②`component_mode` 的判定依据（后端名 vs 注册表）；③`prompt_sha256`/`evidence_ref` 的确切定义。详见 `docs/M2_V1.2.6_M1_GATE_COMPAT.md` 第 6 节。
