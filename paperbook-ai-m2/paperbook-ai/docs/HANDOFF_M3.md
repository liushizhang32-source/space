# 给 M3 的交接说明：视觉产物怎么用、LLM/TTS 接在哪一层

日期：2026-11-10　维护：M2（视觉）

## 一、一句话结论

M2 这一层已经跑**真实模型**并产出契约文件；现在默认链路里的「模板 Story + silent TTS」是**编排层 Adapter 的占位实现**，不是视觉层没接。接真实 LLM/TTS 要改的是 Adapter 及其开关，视觉产物不需要改。

## 二、这批数据怎么来的

- 命令：`python eval/run_batch.py --input data\books\batch01 --out eval\batch01c --with-vlm`
- OCR：PaddleOCR PP-OCRv5 mobile（CPU），单页 0.4–2.4 s（正常绘本页约 1 s）
- VLM：本地 Ollama `qwen2.5vl:3b`，OpenAI 兼容接口，单页 2–3 s
- 四页：英文绘本正文页、暗光夜景页、无字横图、中世纪拉丁文印刷页
- 结果：3 页 `ok` + 1 页 `empty`，0 失败；两页有手写真值，字准确率 97.33%

## 三、产物契约（M3 只需要认这三个路径）

| 文件 | 内容 | 谁写 |
|---|---|---|
| `data/json/{page_id}_ocr.json` | C1：`text_blocks[]`（text/bbox/confidence） | M2 |
| `data/json/{page_id}_vlm.json` | C2：`description`、`objects[]`（label/bbox/confidence）、`scene_tags`、`safety` | M2 |
| `data/logs/{page_id}_{stage}.error.json` | 失败详情：`stage`、`code`、`message`、`elapsed_ms` | M2 |

约定：

- `page_id` 形如 `book01_p03`；`block_id`/`object_id` 前缀与 page_id 一致。
- bbox 是**原图像素**，`x2`/`y2` 为开区间；已处理 EXIF 旋转与工作副本缩放。
- `status`：OCR 允许 `ok` / `empty` / `failed`；VLM 只有 `ok` / `empty`。
- `empty` 是**正常结果**（无字绘本），不是失败；失败不写 C2 文件，只写 error.json。
- 错误码：`2001` 模型失败、`2002` 超时、`9001` 契约校验失败、`9002` 后端返回 None。

## 四、质量边界（本轮实测，别过度承诺）

- 正常绘本页 OCR 逐字基本正确（两页 CER 0.021 / 0.036）；暗底页会多出 1–2 个假字块（如「大」）。
- 无字页正确返回 `empty`。
- 超纲输入（哥特体拉丁文）会 `ok` 但文本不可用，VLM 还会硬套「儿童绘本」语义——产品侧需要按语言/置信度兜底。
- VLM 标签偏泛（两个框都叫「人物」），且没有物体级真值，只能定性判断「能不能用」。
- 这四页里只有两页有 CER 真值，97.33% 不能外推成整书准确率。

## 五、分层：谁依赖谁

```
图片 ──[M2 OCR]──> C1 文字 ─┐
     └─[M2 VLM]──> C2 画面 ─┴─> [编排层 Adapter] ─> 故事/讲解文字 ─> [TTS] ─> 音频
                                      ↑
                              LLM（或模板）在这里
```

| 环节 | 真实产出需要 | 现在默认链路 | 「不接」发生在哪 |
|---|---|---|---|
| 文字来源（画面/台词） | M2 的 C1/C2 | **已真实**：PaddleOCR + 本地 VLM | 不在这一层 |
| 故事/讲解文字 | LLM（或高质量模板） | 模板 Story | 编排层 Adapter（硬编码，不读 `LLM_*`） |
| 声音 | 真实 TTS 服务 | silent TTS | 编排层 TTS Adapter（不读 `TTS_HTTP_URL`） |
| 测试确定性 | — | mock | 集成层/CI（真实服务只应在演示开关下开） |

四句判断：

1. 不是视觉层不接——M2 侧真实模型已跑通并出契约文件。
2. 不是契约层不接——C1/C2 已冻结并通过公共 Schema；C3（StoryData）仍是草稿，缺 `model` 字段。
3. 是编排层默认路径不接——mock Adapter 显式构造「模板 Story + silent TTS」。
4. 现在不接是**工程决策**（契约还在审、TTS 未选型、成本/密钥/可复现性），不是能力缺失。

## 六、M3 接入检查清单

接 LLM/TTS 时，请保持这三条不变，否则问题会串层：

- [ ] 视觉产物只读：不要改 `data/json/*.json` 的字段名或 bbox 语义。
- [ ] 失败要能区分层：OCR/VLM 失败看 `data/logs/*.error.json` 的 `code`；不要把「视觉失败」当成「LLM 写得不好」。
- [ ] 真实服务加开关：默认仍走 mock，演示环境用环境变量打开；密钥只进本机 `.env`，不进仓库。

需要向 M2 确认的只有两类：

- C1/C2 字段是否够用（例如需不需要 `language`、`reading_order`、物体置信度分级）。
- 单页预算：VLM 正常 2–3 s，超纲页可到 24 s；阶段超时建议 ≥60 s。

## 七、联调测试建议

1. **固定输入做 golden**：用 `samples/example/` 的两页产物跑通「读 C1/C2 → 生成 → 落盘」，不依赖模型在线。
2. **真实服务单开一条**：`LLM_*` / `TTS_HTTP_URL` 只在这条链路生效，CI 不跑。
3. **降级路径要测**：LLM 超时、TTS 失败时，是否还能返回文字 + 静音，而不是整页 500。
4. **不要用真实模型做单测断言**：模型输出不稳定，断言只能落在契约字段和状态码上。

## 八、复现命令

```powershell
cd paperbook-ai
$env:PYTHONIOENCODING="utf-8"
& .venv\Scripts\python.exe eval\run_batch.py --input data\books\batch01 --out eval\batch01c --with-vlm
& .venv\Scripts\python.exe tests\run_all.py
```

产物：`eval/batch01c/report.md`（统计）、`eval/batch01c/REVIEW.md`（逐页复盘）、`data/json/*.json`（C1/C2）。
