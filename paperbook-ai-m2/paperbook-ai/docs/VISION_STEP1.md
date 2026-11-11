# 成员2 · 视觉模块 · 第一步交付说明

> ⚠️ **历史文档**：记录第一步（契约层）的交付。部分行为已在第二/三轮修订中变更：
> VLM 阶段失败**不再写 `vlm.json`**、附加字段默认关闭、CLI 新增退出码 5。
> 以 [TEST_REPORT.md](TEST_REPORT.md) 和 [INTEGRATION.md](INTEGRATION.md) 为准。

> 对齐 `docs/API_v1.0.md`（ZSZB-API-1.0，冻结）。本文件只解释"第一步做了什么、怎么验收、下一步接什么"。

## 1. 为什么第一步是契约层，不是模型

API 文档把模块间通信定成了**文件契约**（§1.12）：

```
{DATA_DIR}/json/{page_id}_ocr.json   成员2 写，成员3 读
{DATA_DIR}/json/{page_id}_vlm.json   成员2 写，成员3 读
```

这意味着 M1 的编排、M3 的 Story 在等的是**两个文件**，不是两个模型。
如果先花三天调 PaddleOCR 再对契约，M1/M3 会空转三天；反过来，先把契约打通，
他们当天就能联调，模型随时可换。

所以第一步交付的是：**一个能产出合规 JSON 的流水线 + 可插拔后端 + 校验与单测**。

## 2. 交付清单

| 文件 | 作用 |
|---|---|
| `contracts/ocr.schema.json` | C1 的 JSON Schema（供外部工具 / 评委查） |
| `contracts/vlm.schema.json` | C2 的 JSON Schema |
| `src/vision/ids.py` | book_id / page_id / block_id / object_id 规则 |
| `src/vision/contracts.py` | 两份文档的构造器：bbox 裁剪、编号、status、置信度加权 |
| `src/vision/preprocess.py` | EXIF 矫正、长边限制、**工作副本缩放与坐标还原** |
| `src/vision/pipeline.py` | 单页：图 → OCR → VLM → 原子写两份文件 |
| `src/vision/validate.py` | 无依赖契约校验（CI 与本地都跑） |
| `src/vision/backends/` | `stub` / `paddleocr` / `qwen2.5-vl(http)` 三个后端 |
| `tests/` | 18 条用例：ID、bbox、缩放还原、失败降级、空页、未知字段 |
| `.github/workflows/ci.yml` | push 即跑契约测试（CPU，无需模型） |

## 3. 验收标准（均已通过）

```bash
python run.py --image samples/demo_page.png --book-id book01 --page-no 1
# → contract : ok
python tests/run_all.py
# → 18 passed, 0 failed
```

- [x] 文件名严格为 `{page_id}_ocr.json` / `{page_id}_vlm.json`
- [x] `schema_version=1.0`，`page_no` 为整型，`page_id` 与 `book_id` 一致
- [x] bbox 为整数、左上原点、`x2/y2` 不含端点、落在图内
- [x] `order` 从 1 连续，`block_id`/`object_id` 与 `order` 对齐
- [x] 无字页 → `status=empty`（**不是 failed**，走 §1.14 无字模式）
- [x] 模型异常 → `status=failed` + `error{code:2001}`，**文件照样落盘**
- [x] 大图缩放后 bbox 仍落在原图坐标系
- [x] 未知字段不报错（符合"消费方忽略未知字段"）

## 4. 两个设计决定（需要团队知会）

1. **附加字段改为默认关闭**。`producer` 与 `error` 曾无条件写入，与公共 Schema 冲突；
   现改为设 `VISION_EMIT_EXTRA=1` 才附加，交付文件字段与 C1/C2 完全一致。
   排障时打开即可看到后端名与错误原因。

2. **VLM 的 bbox 只作参考**。
   Qwen2.5-VL 的 grounding 不稳，第二步起应改成"检测模型给框 + VLM 给 label"。
   现在的结构已经留好位置：换 `VlmBackend` 实现即可，`contracts` 不动。

## 5. 下一步（按优先级，含验收）

| # | 任务 | 命令/产出 | 验收 | 建议日期 |
|---|---|---|---|---|
| 1 | 接 PaddleOCR 真模型 | `pip install paddleocr paddlepaddle`；`--ocr-backend paddle` | 6 本绘本每页出 `status=ok`，肉眼比对 3 页文字 | 11/5–11/6 |
| 2 | 建 OCR 评测 | `eval/ocr_eval.py`：字符准确率（1-CER） | 出一张 per-page 表格，标出 badcase | 11/6 |
| 3 | 接 Qwen2.5-VL | vLLM 起服务，`QWEN_VL_BASE_URL=...`；`--vlm-backend http` | JSON 解析成功率 ≥95%，`objects` 有中文 label | 11/7–11/8 |
| 4 | 物体库预建 | `GroundingDINO/YOLO-World` + `SAM2` 离线跑每页，存 mask+label | 每页 ≥3 个可点物体，人工抽检 20 页 | 11/9–11/10 |
| 5 | 点读接口 `/tap` | 输入图/帧 + 坐标 → 命中物体 → 讲解 | 命中率 ≥90%，单次 <1.5s | 11/11–11/12 |
| 6 | 视频帧模式 | 关键帧 + ByteTrack，坐标映射 | 播放中点任意物体可识别 | 11/13 |
| 7 | 准确率报告 | Top-1、拒答率、延迟 P50/P95 | 写进 `eval/report.md`，供说明书"测试结果" | 11/14 |

**风险与兜底**

- `paddlepaddle` 在 Python 3.12 / Windows 上可能没有 wheel：用 3.10/3.11 的 venv；
  若仍装不上，退化方案是"让 Qwen2.5-VL 直接读文字"（同一 HTTP 后端，换 prompt），
  OCR 后端再加一个 `vlm` 实现即可，契约不变。
- 企业赛统一云 GPU：现在就把模型路径、`DATA_DIR`、`ASSET_BASE_URL` 全部走环境变量，
  已按 §1.16 落进 `.env.example`，迁移时只改 env。

## 6. 给 M1 / M3 的对接说明

- **M1**：只读 `data/json/{page_id}_{ocr|vlm}.json`，用 `status` 判 `ok` / `empty` / `failed`；
  不要因为 `failed` 就中断整页，按 §1.7 三级状态表走降级（`partial` + `no_ocr`）。
- **M3**：`ocr.json` 的 `text_blocks` 已按阅读顺序排好；`vlm.json` 的 `objects` 带
  `object_id`，可直接写进 `story.json` 的 `highlight_object_ids`。
