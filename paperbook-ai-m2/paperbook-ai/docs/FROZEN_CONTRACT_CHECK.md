# C1 / C2 冻结字段对照（V1.2 Worker 版）

本文件用于回答一个问题：**V1.2 的 Worker 有没有改动冻结的 C1/C2？**
结论：没有。Worker 只是换了一个调用方式，产物仍由 `src/vision/contracts.py`
里同一组构造函数生成；`contracts.py` / `validate.py` / `pipeline.py` 与 V1.1.1
交付包**逐字节相同**（见第 4 节哈希）；`preprocess.py` / `writer.py` 在 V1.2.1
增加了“内存字节解码”和“独占写”参数，但**字段与 JSON 形状未变**。

## 1. C1（`{page_id}_ocr.json`）

| 字段 | 类型 | V1.0 冻结 | 本版行为 |
|---|---|---|---|
| `schema_version` | string | `"1.0"` | 不变 |
| `book_id` | string | 书籍 id | 由 `page_id` 前缀解析 |
| `page_id` | string | `{book}_{page}` | 原样 |
| `page_no` | int | 页码 | 由 `page_id` 解析 |
| `status` | string | `ok` / `empty` / `failed` | Worker 只产出 `ok` / `empty`（失败走 2001/2002/9001，不写 C1） |
| `image_width` / `image_height` | int | **原图像素** | 预处理的 `PageImage` 原尺寸 |
| `text_blocks[]` | array | 见下 | 同一构造函数 |
| `page_confidence` | float | 0..1，按字符数加权 | 不变 |
| `elapsed_ms` | int | ≥0 | 本次 OCR 耗时 |

`text_blocks[]`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `block_id` | string | `{page}_t01` 起，连续重编号 |
| `order` | int | 1 起（V1.0 已有，未改） |
| `text` | string | 去首尾空白，空串不产出 |
| `bbox` | int[4] | 原图像素、x2/y2 开区间、夹到图内 |
| `confidence` | float | 0..1，四位小数 |

## 2. C2（`{page_id}_vlm.json`）

| 字段 | 类型 | V1.0 冻结 | 本版行为 |
|---|---|---|---|
| `schema_version` | string | `"1.0"` | 不变 |
| `book_id` / `page_id` / `page_no` | — | 同 C1 | 同 C1 |
| `status` | string | **只有 `ok` / `empty`** | 只有 `ok` / `empty`；安全拦截返回 3004，**不写文件** |
| `image_width` / `image_height` | int | 原图像素 | 不变 |
| `description` | string | 一句话画面描述 | 不变 |
| `objects[]` | array | 见下 | 不变 |
| `scene_tags` | string[] | ≤4 个中文关键词 | 不变 |
| `safety` | object | `{"pass": bool, "flags": string[]}` | 只在 `pass is True` 且 `flags` 为空时发布 |
| `elapsed_ms` | int | ≥0 | 本次 VLM 耗时 |

`objects[]`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `object_id` | string | `{page}_o01` 起 |
| `label` | string | 中文具体名词 |
| `bbox` | int[4] | 同 C1 坐标口径 |
| `confidence` | float | 0..1 |

## 3. 明确没有做的事

- 没有给 C1/C2 增加 `blocked` 状态（M1 用 3004 + Page blocked 表达）；
- 没有增加 `character_id` / `canonical_id` / `refs` 字段（这些在 **sidecar** 里，见
  `docs/samples/sidecar_example.json`，且明确是私有协议候选）；
- 没有增加 `attempt_id` / `generation_id` 到 C1/C2（identity 只在 `result.json`
  与 sidecar 里回显）；
- `producer` / `error` 字段仍受 `VISION_EMIT_EXTRA=1` 控制，默认不写；
  M1 的 allowlist **不应**放行该变量，否则产物字节会与“无附加字段”的验收口径不同。

## 4. 字节级证据

| 文件 | SHA-256（V1.1.1 交付包 = 本版） |
|---|---|
| `src/vision/contracts.py` | `a143a6b72604c36471961c5ef2ce630b20fdd3f1e32353b33562c9a231042756` |
| `src/vision/validate.py` | `a9c85fda970ecd8e0dd53cda3b8c7b561bc6ade02c3414bd24b49f7985b4fe26` |
| `src/vision/preprocess.py` | `689dba755a4a0f8e5317a045a6a8d7e16187e931cdee93e8481d4501db2ba89c`（V1.2.1 新增 `data=` 参数，字段不变） |
| `src/vision/writer.py` | `9ff50bc11b5b9dc3984d8bc2946b7b12ba8a37338bdf3cceb306ab5063bef59a`（V1.2.1 新增 `write_json_exclusive`） |
| `src/vision/pipeline.py` | `f746aec990d0134e106a33dcff4b9cc0ac2a4988a65962830ce488c87add2596` |

复现命令（在模块根）：

```powershell
Get-FileHash src\vision\contracts.py -Algorithm SHA256
```

对照对象：`paperbook-ai-m2-v1.1.1-revised.zip`（SHA256
`4FCCCCA4C49FA0DA0E940CECAFBD69164A0FCE19279CA7E8AA5DDC2812E536C8`）
内同名文件。

## 5. 公共 Schema 校验

Worker 产物仍可用真实公共模型验证：

```powershell
python scripts\validate_with_orchestrator.py --repo-root <space 仓库根> --from <产物目录>
```

CI 里同一脚本已在 V1.1.1 上跑过 2 页 4 产物（`[PASS]`×4）。本版没有改 C1/C2 生成逻辑，
因此不需要新的 Schema 结论；M1 联调时应再跑一次以确认“经 Worker 落盘的字节”同样通过。

