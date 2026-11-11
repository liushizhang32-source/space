# M1 Supervisor 联调报告（M2 侧，V1.2）

日期：2026-11-11　　对应交接：`docs/M1_TO_M2_V1.2_WORKER_HANDOFF.md`

## 0. 结论先说

- M2 侧**已完成单次 Worker 适配**：入口、请求/响应、identity 回显、3004 安全门禁、
  sidecar 绑定、路径约束都可以被 M1 直接拉起。
- **尚未与真实 M1 Supervisor 联调**：本机没有 `space-m1-m2-v12-supervisor` 工作区，
  也没有在 M1 的 Job Object / cgroup 里跑过；本节所有“已测”都是本机进程边界测试。
- 因此本报告只声明“M2 侧就绪”，**不声明“联调通过”**。联调结论要等 M1 起进程后由双方共同签。

## 1. 协议对照

| 交接要求 | M2 实现 | 状态 |
|---|---|---|
| 一次进程只跑一个 stage | `worker.main` 读一个 request，只走 `ocr` 或 `vlm` 分支 | ✅ |
| 入口形态 `[解释器, 入口, request.json]` | `scripts/m2_vision_worker.py <request.json>` | ✅ |
| 请求字段 `m1-vision-worker/0.1` | 全部解析，缺字段 → 9001/退出 2 | ✅ |
| identity 七项逐项回显 | `result.json.identity` 与请求比对 | ✅ |
| 先落产物、最后写 `result.json` | `_finish` 在所有产物写完后调用 | ✅ |
| OCR artifacts = `{c1}` | `{"c1": "json/<page>_ocr.json"}` | ✅ |
| VLM artifacts = `{c2, sidecar}` | 恰好两项，缺一即失败 | ✅ |
| 成功 `code=0` 且退出 0 | `EXIT_OK=0` | ✅ |
| 失败非零 code + 字符串 msg + `transient` | 2001/2002/3004/9001 均带 `transient` | ✅ |
| 3001 只表示 OCR 无字 | 本实现用 `code=0` + 合法空 C1，不发 3001 | ✅（等价） |
| 3004 表安全拦截 | `safety.evaluate_vlm_safety` 不通过 → 3004、不写 C2/sidecar | ✅ |
| 不在 M2 做重试/超时/状态机 | `worker.py` 无 sleep、无 retry、无计时器 | ✅ |
| 不包装共享 HTTP Sidecar | 旧 `sidecar.py` 弃用，未随包交付 | ✅ |
| 路径必须在 attempt 目录内 | `_resolve_under` 拒绝绝对路径/`..`/越界 | ✅ |

## 2. 本机实测矩阵

| 场景 | 后端 | 结果 | 证据 |
|---|---|---|---|
| OCR 成功（mock） | `VISION_OCR_BACKEND=stub` | exit 0，`c1` 落盘 | `docs/logs/worker_smoke_ocr.log` |
| VLM 安全拦截（mock） | `VISION_VLM_BACKEND=stub` | exit 1，`code=3004`，**无 C2 文件** | `docs/logs/worker_smoke_vlm.log` |
| OCR 成功（真实模型） | PaddleOCR PP-OCRv5 mobile | exit 0，3 块，page_conf 0.9925，8.3 s | `docs/logs/worker_smoke_ocr_real.log` |
| VLM 成功（真实模型） | `qwen2.5vl:3b`（ollama） | exit 0，1 物体，`safety.pass=true`，10.6 s，sidecar sha 与 C2 字节一致 | `docs/logs/worker_smoke_vlm_real.log` |
| 单元/回归 | — | **97 passed, 0 failed** | `docs/logs/worker_tests.log` |
| 真实 M1 Supervisor 拉起 | — | **未执行** | 本机无 M1 工作区 |
| 30 s 墙钟 / 进程树 kill | — | **未执行**（M1 侧证据见其报告 S02/S03） | — |
| 取消 / 过期 generation / 并发 | — | **未执行** | — |
| M3 消费 refs、URL 发布 | — | **未执行** | — |

## 3. 需要 M1 确认的四件事

### 3.1 VLM 阶段的 OCR 文本从哪来（最重要）

交接文档的请求字段里没有“上一阶段 C1 路径”。当前实现：

1. 有 `inputs.c1` → 读它取文字；
2. 没有 → 在 VLM 进程内**再跑一次 OCR**（不写 C1）。

方案 2 在真实模型下要多吃 8–11 秒（拉丁文页曾到 23 秒），30 秒预算会被挤压。
**建议 M1 在协议里加显式字段**（或约定 `inputs.c1` 为必填）。在确认前，
联调请务必带上 `inputs.c1`。

### 3.2 环境变量 allowlist

M1 只继承 allowlist。真实模型至少需要放行：
`VISION_OCR_BACKEND`、`VISION_VLM_BACKEND`、`QWEN_VL_BASE_URL`、`QWEN_VL_MODEL`、
`QWEN_VL_API_KEY`、`QWEN_VL_MAX_TOKENS`、`QWEN_VL_TIMEOUT`、
`PADDLE_PDX_CACHE_HOME`、`PADDLE_OCR_LANG`、`PADDLE_OCR_MKLDNN`。

**不要放行 `VISION_EMIT_EXTRA`**：它会给 C1/C2 追加 `producer/error`，改变产物字节。

### 3.3 相对路径会跟着 cwd 漂移

`PADDLE_PDX_CACHE_HOME=./models/.paddlex` 在 M1 的 attempt cwd 下会指错地方。
Worker 已做兜底：启动时把 `PADDLE_PDX_CACHE_HOME`、`PADDLE_OCR_MODEL_DIR`
的相对值锚到模块根，并在未设置时把 `MPLCONFIGDIR` 指到 `models/.mplconfig`。
即便如此，**建议 M1 仍传绝对路径**，避免两个进程各解释一次。

### 3.4 被硬墙杀掉时没有 `result.json`

M1 30 秒终止进程树时，Worker 来不及写 `result.json`。这是预期行为：
M1 应按“超时 2002、可重试”处理，而不是按协议违规。
`QWEN_VL_TIMEOUT` 建议设 25 秒，让超时尽量以结构化 2002 返回。

## 4. 建议的联调顺序

1. **S-OCR-mock**：`VISION_OCR_BACKEND=stub`，验证入口/identity/artifacts/退出码；
2. **S-VLM-block**：`VISION_VLM_BACKEND=stub`，验证 3004 且 Page blocked、零下游；
3. **S-OCR-real**：PaddleOCR，验证 30 秒内正常退出与 C1 字节；
4. **S-VLM-real**：`qwen2.5vl:3b` + `inputs.c1`，验证 C2 + sidecar + sha 绑定；
5. **S-timeout**：注入 sleep 后端（M1 侧 fixture），验证 30.0 s 杀树、2002、无残留；
6. **S-fencing**：旧 generation 结果不得覆盖新产物（M1 侧校验）；
7. **S-refs**：M1 计算 C2 原始字节 sha256 与 sidecar 比对；篡改一位应拒绝；
8. **S-cancel**：取消后不允许再发布。

M1 交接文档提到的 S01–S18 未在文档里逐条列出，以上 8 项覆盖其核心断言；
若 M1 有正式清单，按清单逐条补测并回填本表。

## 5. 边界声明

- 本报告**没有**修改 M1 监管核心、没有改冻结 API、没有提交 Git；
- 所有“真实模型”结论只针对本机 `qwen2.5vl:3b` + PaddleOCR CPU，不代表云端或 Linux；
- 测试不依赖真实密钥（stub 路径不读 `QWEN_VL_API_KEY`）。

## 6. V1.2.1 追加（2026-11-11）

本轮把交接文档里“需 M1 确认”的四件事收敛成硬约束：

1. **VLM 请求必须带 `inputs.c1` + `c1_sha256` + `image_sha256`**，进程内补跑 OCR 的兜底已删除；
   缺任一项直接 `9001`（不重试）。M1 需要在 VLM attempt 的请求里补后两个哈希。
2. **`outputs.c1/c2/sidecar` 与 `result_path` 必须互不相同**，且不得已存在；
   Worker 在跑模型前检查，冲突即 `9001` + 退出码 2。
3. **allowlist 追加**：`M2_MAX_OCR_BLOCKS`、`M2_MAX_OCR_CHARS`、`M2_VLM_EXEC`（可选）。
   仍然禁止 `VISION_EMIT_EXTRA`。
4. **sidecar 标记 `contract_status: "candidate"`**；M1 校验器在签认前应拒绝把它当公共契约。

联调 8 步不变，但 S-VLM-real 的请求体要补两个哈希；S-refs 增加一条
“`c1_sha256` 与 M1 传入值一致”的断言。
