# M2 单次 Worker 接口说明（V1.2 适配版）

本文件描述 M2 交给 M1 Supervisor 拉起的**单次进程**接口。它对应
`docs/M1_TO_M2_V1.2_WORKER_HANDOFF.md` 里的候选协议 `m1-vision-worker/0.1`，
**不是公共 API 更新**，也不改变冻结的 C1/C2（`docs/API_v1.0.md`）。

## 1. 边界：谁负责什么

| 能力 | 归属 | M2 的实现状态 |
|---|---|---|
| 30 秒硬墙、进程树终止、`wait` 回收 | M1 | **不做**，M2 进程内没有任何整页计时器 |
| 重试（≤2 attempt）与 1 秒退避 | M1 | **不做**，M2 不重试、不 sleep |
| Job/Page 状态机、generation fencing | M1 | **不做**，M2 只回显 identity |
| 单次 OCR / 单次 VLM | M2 | 本进程只跑一个 stage，跑完即退出 |
| 输入过滤（类型/体积/像素/动图） | M2 | `src/vision/input_guard.py` |
| 安全判定 fail-closed | M2 | `src/vision/safety.py` + 解析层 `parse_safety` |
| 视觉实体 Sidecar | M2 | `src/vision/refs.py`（`vision_refs/0.1`） |
| 产物落盘、SHA256 绑定 | M2 | 先写产物，最后写 `result.json` |

M2 不提供 HTTP 服务、不监听端口、不创建线程池、不写全局状态文件。

## 2. 入口

```text
[解释器绝对路径] [模块根]/scripts/m2_vision_worker.py [request.json 绝对路径]
```

- 参数**恰好一个**：request 文件；多一个少一个都按坏请求退出（退出码 2）。
- 工作目录由 M1 指定为该 attempt 的私有目录；`outputs`、`result_path`
  都是**相对这个目录**的路径。
- 进程读完请求、跑完一个 stage、写完结果后自行退出；退出前不等待任何后台线程。

Windows 参考命令（真实模型时）：

```powershell
C:\...\paperbook-ai\.venv\Scripts\python.exe ^
  C:\...\paperbook-ai\scripts\m2_vision_worker.py ^
  C:\...\attempt-7f3a\request.json
```

## 3. 请求（`m1-vision-worker/0.1`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `protocol` | string | 必须是 `m1-vision-worker/0.1` |
| `job_id` | string | 原样回显 |
| `page_id` | string | `{book}_{page}`，如 `book01_p01` |
| `generation_id` | string | 原样回显 |
| `input_revision` | int ≥ 0 | 原样回显 |
| `epoch` | int ≥ 0 | 原样回显 |
| `attempt_id` | string | 原样回显 |
| `fencing_token` | string | 原样回显；M2 不校验其新鲜度（M1 负责） |
| `stage` | `"ocr"` \| `"vlm"` | 一个进程只跑一个 |
| `image_path` | 绝对路径 | 必须存在且通过 `input_guard` |
| `result_path` | 相对路径 | 默认 `result.json` |
| `outputs` | object | OCR：`{"c1": rel}`；VLM：`{"c2": rel, "sidecar": rel}`；三者必须互不相同、不得等于 `result_path`、不得已存在 |
| `inputs` | object，**VLM 必填** | `{"c1": rel, "c1_sha256": hex64, "image_sha256": hex64}` |

路径规则：必须是相对路径、不含 `..`、解析后仍在 attempt 目录内；任一段是符号链接/junction
也直接拒绝。校验发生在**跑模型之前**，返回 `code=9001` + 退出码 2，不触碰文件系统。

### VLM 必带的 C1（V1.2.1 P1-5）

VLM 阶段**不再允许**进程内补跑 OCR。请求必须带：

1. `inputs.c1`：M1 校验过的那份 C1 文件（相对 attempt 目录）；
2. `inputs.c1_sha256`：该文件**原始字节**的 SHA-256；
3. `inputs.image_sha256`：本次图片原始字节的 SHA-256。

Worker 会校验：C1 字节哈希、`page_id`、`book_id/page_no`、`status ∈ {ok,empty}`、
`image_width/height` 与当前图片一致、图片字节哈希一致。任一不符 → `9001`（不重试）。
这样旧 revision、跨页 C1、被替换的图片都无法混进同一次 attempt。

## 4. 输出

先完整落盘产物（C1 / C2 / sidecar），**最后**写 `result.json`，然后退出。
M1 在整棵进程树退出后才读，因此不需要额外同步。

```json
{
  "protocol": "m1-vision-worker/0.1",
  "identity": {"job_id": "...", "page_id": "...", "generation_id": "...",
               "input_revision": 1, "epoch": 1, "attempt_id": "...",
               "fencing_token": "..."},
  "code": 0,
  "msg": "ok",
  "artifacts": {"c2": "json/book01_p01_vlm.json",
                "sidecar": "json/book01_p01_vlm.vision_refs.json"}
}
```

失败时 `code` 非零、`msg` 为字符串、附 `transient` 布尔；`artifacts` 通常为空。
可选的 `detail` 是**诊断信息**，不是契约字段，M1 可以只记录不解析：
| 场景 | `detail` |
|---|---|
| 安全拦截 | `{"verdict": {"pass": false, "reasons": [...], "source": "..."}}` |
| OCR 无字 | `{"empty": true}` |
| 超量拒绝 | `{"kind": "ocr_blocks"\|"ocr_chars"\|"objects", "actual": N, "limit": M}` |
| 置信度缺失 | `{"confidence_missing": N}` |

| 退出码 | 含义 |
|---:|---|
| 0 | `code == 0`，产物已完整落盘 |
| 1 | 已写出 `result.json` 的阶段失败（如 1004/2001/2002/3004/9001） |
| 2 | 请求本身非法（`code=9001`），也已尽量写 `result.json` |

`code=0` 却非零退出，或非零 `code` 却零退出，都会被 M1 判为协议违规。

## 5. 错误码

| code | 含义 | transient | M1 是否重试 |
|---:|---|---|---|
| 1004 | 输入超量（体积/像素/块数/字数/objects） | false | 否 |
| 1006 | 输入类型不支持（PDF/SVG/动图/损坏） | false | 否 |
| 2001 | 模型调用失败 | true | 是（msg 含 safety 时除外） |
| 2002 | 超时 | true | 是 |
| 2004 | 后端初始化/配置失败 | true | 是 |
| 3004 | 安全拦截 / 安全结论缺失 | false | 否 |
| 9001 | 契约/请求/产物非法 | false | 否 |

M2 自己**不重试**，`transient` 只是给 M1 的建议位。3001 不用于 VLM；
OCR 无字按成功处理（`status=empty` 的合法 C1，`code=0`）。

## 6. 安全语义（fail-closed）

只有同时满足下面三条才发布 C2：

1. 后端 `VlmResult.safety_pass is True`（**原生布尔**；`"true"`、`1` 都不算）；
2. `safety_flags` 是 `list[str]` 且没有任何非空元素；
3. `safety_source == "model"`（stub 或补出来的结论一律不可信）。

否则 `safety.evaluate_vlm_safety` 返回不通过，Worker：

- 返回 `code=3004`，`transient=false`；
- **不写 C2、不写 sidecar**，目录里除 `result.json` 外没有别的产物；
- M1 据此把 Page 置 `blocked`，不调 M3、不发布。

解析层还有一层兜底：模型输出缺 `safety` / 不是对象 / `pass` 不是布尔时，
`parse_safety` 直接给 `pass=false, flags=["safety_missing"]`（V1.2.1 起细分为
`safety_pass_missing`/`safety_pass_not_true`/`safety_flags_not_list` 等），同样落到 3004。
因此不存在“模型没给安全结论就默认安全”的路径。

## 7. Sidecar（`vision_refs/0.1`）

样例：`docs/samples/sidecar_example.json`；对应 C2：`docs/samples/c2_example.json`。

绑定规则：

- `identity` 七项与请求逐项一致（含 `attempt_id`），同时以**扁平镜像**再写一份到顶层
  （兼容只读顶层的校验器；签认后二选一）；
- `contract_status: "candidate"`：明确标记“候选协议、未经三方签认”，M1 可据此拒绝接线；
- `c1_sha256`：M1 传入的那份 C1 的**原始字节**哈希（与 `inputs.c1_sha256` 相同）；
- `c2.sha256` = **落盘 C2 原始字节**的 SHA-256，M2 写完后读回计算，不重排 JSON；
- `c2.relative_path` 就是请求里的 `outputs.c2`；
- `observations[]` 与 C2 `objects[]` 一一对应，`observation_id` 为 `obs_001` 起，
  `object_id` 必须存在于本页 C2（跨页 id 会直接构造失败）；
- `confidence`：0<value≤1 用 `{"value":…, "kind":"model_estimate", "calibrated": false}`，
  缺失/0 用 `{"value":null, "kind":"unavailable", "calibrated":false}`；
  bool/NaN/字符串一律按“缺失”处理，不猜；
- `appearance.clothing` 当前恒为 `null`（模型不给服装），类型声明为 `str | null`；
- `identity_status` 固定 `unknown`，**M2 不定义 canonical/character 身份**；
- `source.component_mode`：`real`（真实后端）或 `stub`（打桩）；
  `prompt_sha256` 取实际使用的提示词模板哈希，stub 时为占位值。

> 该 schema 是 M1 交接的**候选协议**，字段名/路径在接线前需三方确认；
> M2 不把它当公共契约，也不写进 C1/C2。

## 8. 环境变量（M1 allowlist 必须放行）

M1 只继承 allowlist 环境。真实模型至少需要：

| 变量 | 用途 |
|---|---|
| `VISION_OCR_BACKEND` | `stub` / `paddle` |
| `VISION_VLM_BACKEND` | `stub` / `http` |
| `QWEN_VL_BASE_URL` / `QWEN_VL_MODEL` / `QWEN_VL_API_KEY` | VLM 端点 |
| `QWEN_VL_MAX_TOKENS` / `QWEN_VL_TIMEOUT` | 生成上限与**后端**超时 |
| `PADDLE_PDX_CACHE_HOME` / `PADDLE_OCR_LANG` / `PADDLE_OCR_MKLDNN` | PaddleOCR 缓存与推理 |
| `M2_MAX_OCR_BLOCKS` / `M2_MAX_OCR_CHARS` | 超量阈值（默认 99 / 20000，超了返回 1004 而不是截断） |
| `M2_VLM_EXEC` | `inproc`（默认）或 `subprocess`（VLM 跑在子进程，可被杀树回收） |

注意：

- **不要**放行 `VISION_EMIT_EXTRA`——它会给 C1/C2 追加 `producer/error` 字段，
  与“原始字节快照”的比对口径不一致；
- `QWEN_VL_TIMEOUT` 建议设成小于 M1 的 30 秒（例如 25），让超时以 2002 结构化返回；
  即使不设，M1 的硬墙也会杀进程树，只是拿不到 `result.json`。

## 9. 本版明确不做的事

- 不做重试/退避（M1 做）；
- 不做 30 秒墙钟与进程树回收（M1 做）；
- 不写 `data/json`、`data/logs`（只写 attempt 目录内的 `outputs`/`result.json`）；
- 不提供常驻 HTTP Sidecar（旧的 `sidecar.py` 已弃用，见交付说明）。
