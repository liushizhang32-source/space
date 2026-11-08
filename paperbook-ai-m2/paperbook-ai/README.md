# 纸书智伴 · paperbook-ai

第二届北京市大学生"人工智能+"创新大赛 · "纸书智伴"赛题。
纸质绘本 → OCR/VLM 理解 → 互动故事与视频 → 语音/触控问答。

## 当前进度

| 模块 | 负责人 | 状态 |
|---|---|---|
| Orchestrator / HTTP 路由 | M1 | 待启动 |
| **视觉（ocr.json / vlm.json）** | **M2** | **契约层完成；PaddleOCR + 本地 Qwen3-VL 均已接真；批量评测就绪（9 页 100% 成功、99.6% 字准确率）** |
| Story / TTS / Video | M3 | 待启动 |
| 前端 / ASR / QA | M4 | 待启动 |
| 评测 / 合规 | M5 | 待启动 |

## 快速开始（视觉模块）

> **环境要求：Python 3.10–3.12。不要用 3.14** —— paddlepaddle 目前没有 cp314 的 wheel，
> 装了也跑不起来。本机已建好 `.venv`（Python 3.12，不入库），PyCharm 指到
> `paperbook-ai\.venv\Scripts\python.exe` 即可。

```bash
# 0) 配置：复制后按需改（.env 不入库）
copy .env.example .env          # 默认已设 VISION_OCR_BACKEND=paddle

# 1) 环境自检（Python/依赖/后端/DATA_DIR/冒烟一次看完）
python scripts/check_env.py

# 2) 造一张示例绘本页（不需要真实素材）
python scripts/make_demo_page.py

# 3) 跑一页，产出 data/json/{page_id}_ocr.json 与 _vlm.json
python run.py --image samples/demo_page.png --book-id book01 --page-no 1

# 4) 跑测试（无需 pytest）
python tests/run_all.py
```

**后端由 `.env` 决定**，不用每次传参：

| 想做什么 | 改什么 |
|---|---|
| 用真实 PaddleOCR | `VISION_OCR_BACKEND=paddle` |
| 临时退回打桩 | `--ocr-backend stub`，或改 `.env` |
| 后端没装好、演示不能崩 | 默认自动回退 stub 并打印警告；要它直接报错就加 `--strict` |
| 用 Qwen2.5-VL | 配好 `QWEN_VL_BASE_URL` 后 `VISION_VLM_BACKEND=http` |

接真实模型见 [docs/OCR_SETUP.md](docs/OCR_SETUP.md)。

期望输出：

```
page_id   : book01_p01
ocr.json  : data\json\book01_p01_ocr.json  [ok] blocks=1 conf=0.99 0ms backend=stub
vlm.json  : data\json\book01_p01_vlm.json  [ok] objects=2 0ms backend=stub
contract  : ok
```

## CI（GitHub Actions）

仓库**根目录**需要有 `.github/workflows/m2-vision-checks.yml`。
本包里的 `paperbook-ai/.github/workflows/m2-vision-checks.yml` 只是同一份文件的副本，
**放在模块目录里不会触发**，必须放到仓库根（`space/.github/workflows/`）。

它跑三步，任一失败即变红：

| 步骤 | 命令 | 覆盖 |
|---|---|---|
| 1 | `python -m pytest tests -q` | 94 条；`SCHEMA_REPO_ROOT` 指向仓库根，用**真实**的 `orchestrator/schemas` |
| 2 | `python scripts/isolated_check.py` | 13 项隔离自检（含超时→2002 映射） |
| 3 | `validate_with_orchestrator.py --repo-root . --from samples/example` | 公共 Schema 验收：缺文件、坏 JSON 都算失败 |

依赖由 `requirements-test.txt` 提供（`-r requirements.txt` + pytest + opencv-headless）。
本地没装 pytest 时用 `python tests/run_all.py`（86 条，零第三方依赖）。

## 物体索引与点读

点读不能每次都调 VLM（本地 13 s/页），所以拆成"离线建库 + 在线查表"：

```bash
# 建库：读 data/json/*_vlm.json，写 data/index/{page_id}.json（毫秒级，不调模型）
python scripts/build_index.py

# 点读：坐标 → 命中物体 + 讲解，实测 0.01 ms
python scripts/tap_demo.py --page-id book01_p01 --x 660 --y 700
python scripts/tap_demo.py --page-id book01_p01 --probe   # 5x5 网格看覆盖面
```

命中规则：先找包含该点的 bbox（含 12px 容差），多个命中取面积最小的；
没命中则取最近的物体中心（阈值 = 对角线 6%），照顾小朋友点偏。

### 精分割（可选，点得更准）

```bash
# 默认 GrabCut：CPU 约 0.2s/页，轮廓写进索引
python scripts/build_masks.py --page-id book01_p01 --image samples/demo_page.png \
                              --preview data/masks_p01.png
```

有了轮廓后，命中判定从「矩形」变成「形状」：点在树 bbox 的空白角上会正确返回 miss，
而不是误判成树。

`--segmenter sam2` 可用 SAM2（更准），但**需要 GPU**：本机装的是 CPU 版 torch，
单页要十几分钟，只在企业赛云机上才划算。

## 验收相关文档

| 文档 | 内容 |
|---|---|
| [docs/STANDALONE.md](docs/STANDALONE.md) | 独立运行：只跑 OCR / 只跑 VLM / Schema 校验 |
| [docs/TEST_REPORT.md](docs/TEST_REPORT.md) | 第一轮验收问题的修复与测试报告 |
| [docs/INTEGRATION.md](docs/INTEGRATION.md) | 给 M1/M3/M4 的对接说明 |

> 产物默认**不含** `producer` / `error`（保持与契约字段一致；按 §1.2.5 未知字段本应被忽略）；
> 排障时设 `VISION_EMIT_EXTRA=1` 才会附加。

## 对接其他模块

给 M1 / M3 / M4 的说明见 **[docs/INTEGRATION.md](docs/INTEGRATION.md)**，含字段语义、
空值处理、验收清单。两个可直接跑的示例：

```bash
python examples/consume_vision.py --page book01_p01          # M3：读产物 → story 草稿
python examples/consume_tap.py   --page book01_p01 --x 660 --y 700   # M4：点读 → /qa 响应
```

## 点读评测（触控万物识别）

```bash
# 真值来自 samples/books_demo/*/pXX.gt.json（绘图代码生成，与 VLM/索引无关）
python eval/tap_eval.py --gt-dir samples/books_demo --index-dir data/index --out eval
```

产出 `eval/tap_report.md`：检出率、Top-1（**含漏检** / **仅已检出**两档）、
错判率、背景误触率、延迟分布。

真实绘本需要人工标注同格式真值：

```json
{"page_id": "book01_p01", "objects": [{"label": "兔子", "polygon": [[x, y], ...]}]}
```

### 难例实验（2026-11-06）

```bash
python scripts/make_hard_page.py   # 水彩纹理 + 9 物体 + 遮挡 + 气泡文字
```

| 版本 | 召回 | Top-1 | 背景误触 |
|---|---|---|---|
| 旧 prompt（最多 6 个，明确排除"背景"） | 6/9 | — | — |
| **新 prompt**（太阳/云/房子也要列） | **9/9** | 98.9% | 16.7% |

结论：漏检的主因是 **prompt 把太阳/云/房子当"背景"排除了**，不是模型看不见。
代价是输出变长，单页 VLM 约 20–26 s，`QWEN_VL_MAX_TOKENS` 需提到 4000。

## 批量评测

```bash
# 真实绘本：图片放 samples/books/book01/p01.jpg，真值放同名 .txt
python eval/run_batch.py --input samples/books --out eval

# 合成演示数据（仅验证流程，不能当真实准确率）
python scripts/make_demo_books.py
python eval/run_batch.py --input samples/books_demo --out eval
```

产出 `eval/report.md`（总览 / 按书 / 最差页面 / 失败清单）和 `eval/results.json`（逐页明细）。
指标：成功率、单页耗时（均值/中位/P95）、字准确率（1−CER）。

## 目录

```
contracts/          ocr / vlm 的 JSON Schema（与 docs/API_v1.0.md 同源）
src/vision/
  ids.py            ID 规则（§1.2.2）
  contracts.py      ocr.json / vlm.json 构造器（§1.12 C1/C2）
  preprocess.py     图片加载、EXIF、缩放与坐标还原
  pipeline.py       单页流水线：图 → 两份契约文件
  validate.py       契约校验（不依赖第三方库）
  writer.py         原子写盘（§1.15 存储规范）
  backends/         stub / paddleocr / qwen2.5-vl(http)
tests/              无 pytest 也能跑
scripts/            示例页生成等工具
docs/               接口文档与阶段说明
```

## 换真模型

```bash
# OCR：PaddleOCR
pip install paddleocr paddlepaddle
python run.py --image x.jpg --book-id book01 --page-no 1 --ocr-backend paddle

# VLM：vLLM 起 OpenAI 兼容服务后
export QWEN_VL_BASE_URL=http://127.0.0.1:8100/v1
python run.py --image x.jpg --book-id book01 --page-no 1 --vlm-backend http
```

契约冻结规则：只许新增可选字段，禁止改名/改类型/改必填性（见 `docs/API_v1.0.md`）。
