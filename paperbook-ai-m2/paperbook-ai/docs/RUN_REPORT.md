# 实际执行报告（隔离自检 + 公共 Schema 校验）

> 本文件是**实跑记录**，不是操作手册。手册见 [ISOLATED_TEST.md](ISOLATED_TEST.md)。
> 执行日期：2026-11-07（Asia/Shanghai）。原始日志在 `docs/logs/`。

## 0. 交付标识

| 项 | 值 |
|---|---|
| 交付物 | `paperbook-ai-m2.zip`（87+ 文件） |
| ZIP SHA256 | 见提交消息（本文件无法自指所在 ZIP 的哈希） |
| Git commit | **无**——本机未安装 git，分支 `zhc-1` 尚未推送；以 ZIP 为唯一权威版本 |
| 源码树清单 | `docs/logs/manifest.txt`（逐文件 SHA256，打包前生成） |

## 1. 环境

```
os: Microsoft Windows 10.0.26200
python: Python 3.12.14
pydantic: 2.14.2
pillow: 13.0.0
numpy: 2.3.5
paddleocr: 3.7.0
paddlepaddle: 3.3.1
ollama: ollama version is 0.40.15
```

完整输出：`docs/logs/env.log`。

> 说明：本轮三条命令中，只有第 1 条会 import Paddle（`test_paddle_normalize` 走假引擎），
> 不加载模型、不联网；第 2、3 条完全离线。

## 2. 命令与退出码

| # | 命令 | 退出码 | 日志 |
|---|---|---|---|
| 1 | `.venv\Scripts\python.exe tests\run_all.py` | **0** | `docs/logs/tests.log` |
| 2 | `.venv\Scripts\python.exe scripts\isolated_check.py` | **0** | `docs/logs/isolated.log` |
| 3 | `validate_with_orchestrator.py --repo-root <仿真仓> --from samples\example` | **0** | `docs/logs/schema_positive.log` |
| 4 | 同上两条负例：缺 `vlm.json` / 注入多余字段 | **1 / 1**（预期失败） | `docs/logs/schema_negative.log` |
| 5 | **GitHub Actions（真实公共模型）** | **0** | 见第 5 节 |

## 3. 实际输出

### 3.1 单元测试（命令 1，退出码 0）

```
86 passed, 0 failed
```

### 3.2 隔离自检（命令 2，退出码 0）

```
==================================================================
视觉模块 · 隔离自检（无网络 / 无模型 / 临时目录）
临时目录：...\paperbook-ai\data\_isolated_<uuid>
==================================================================
[PASS] 01 正常页产出 ocr.json + vlm.json  ocr=ok vlm=ok
[PASS] 02 stub 的 safety 必须是 false（打桩≠已审查）  safety=false + stub_mock
[PASS] 03 无字页 → ocr empty 且 page_confidence=0  empty/0
[PASS] 04 OCR 崩溃 → failed 文件 + 错误日志  code=2001
[PASS] 05 VLM 崩溃 → 不产出 vlm.json + 日志  code=2002
[PASS] 06 VLM 返回 None → 9002，不算成功  code=9002
[PASS] 07 畸形 OCR 数据不中断流水线  blocks=2
[PASS] 08 EXIF=6 图片：image_width 是文件尺寸  800x600
[PASS] 09 safety 缺失/未知 → 判不安全  fail-closed
[PASS] 10 超过 99 块 → 截断而不是整页失败  99
[PASS] 11 省略 safety 参数 → 构造即报错  TypeError
[PASS] 12 目录里没有残留的 vlm.json 失败文件  ok/empty only
[PASS] 13 HTTP 超时包装链 → 错误码 2002  URLError(timeout) → 2002
------------------------------------------------------------------
13/13 通过
```

第 13 项的做法：把 `urllib.request.urlopen` 替换成抛 `URLError(socket.timeout(...))`，
调用真实 `QwenVlBackend._post`，捕获 `VlmTimeout` 后经 `pipeline._stage_error` 断言错误码为 `2002`。
**这是源码路径的真实执行，不是文字声明。**

### 3.3 公共 Schema（命令 3，退出码 0）

```
[INFO] 公共 Schema 根目录：...\.pkg\fake_space
[INFO] pydantic=2.14.2
[INFO] OCRData ← ...\.pkg\fake_space\orchestrator\schemas\ocr.py
[INFO] VLMData ← ...\.pkg\fake_space\orchestrator\schemas\vlm.py
[INFO] 待校验 2 页

[PASS] book01_p01 ocr.json  status=ok
[PASS] book01_p01 vlm.json  status=ok
[PASS] exif01_p01 ocr.json  status=ok
[PASS] exif01_p01 vlm.json  status=ok

结论：2 页全部通过公共 Schema 校验
```

**重要限定**：这里用的是**仿真公共模型**（`extra="forbid"`、`status: Literal["ok","empty"]`），
不是联合仓库里的真实 `OCRData/VLMData`。目的有两个：

1. 证明校验器本身能用（能拿到模型、能打印真实文件路径、能判正负例）；
2. 提前暴露"多余字段会被严格模型拒绝"的问题——正是靠它发现旧产物残留 `producer`。

真实公共模型的结论仍需在联合仓库里跑一次（命令见第 5 节）。

### 3.4 负例（命令 4，退出码 1）

往 `book01_p01_vlm.json` 注入 `"future_field": true`：

```
[PASS] book01_p01 ocr.json  status=ok
[FAIL] book01_p01 vlm.json
       1 validation error for VLMData
       future_field
         Extra inputs are not permitted [type=extra_forbidden, ...]
[PASS] exif01_p01 ocr.json  status=ok
[PASS] exif01_p01 vlm.json  status=ok

结论：1 个产物不符合公共 Schema
```

## 4. 本轮修复的三处缺口

| 缺口 | 处理 |
|---|---|
| 旧包没有 `scripts/isolated_check.py` | 本包已包含；`docs/logs/isolated.log` 是它跑出来的 |
| 第 13 项只是声明 | 已在本包执行，日志见 3.2；附 `URLError(timeout)` 构造方式 |
| 手册默认读 `data/json`、样本在 `samples/example` | 校验器新增 `--from <扁平目录>`，可直接读 `samples/example/`；手册补了样本准备说明 |

样本准备的两种方式（任选）：

```powershell
# A. 直接读 samples/example（推荐，无需拷贝）
python scripts/validate_with_orchestrator.py --repo-root C:\code\space --from samples\example

# B. 拷到 data/json 再按目录校验
mkdir data\json -Force
copy samples\example\*.json data\json\
python scripts/validate_with_orchestrator.py --repo-root C:\code\space --all
```

## 5. 真实公共模型校验：已在 GitHub Actions 跑通（2026-11-08）

仓库 `liushizhang32-source/space`，分支 `zhc`，PR #3，workflow run `m2-vision-checks #2`，结论 **Success (18s)**。

关键日志（runner 上的真实文件路径，不是仿真）：

```
[INFO] 公共 Schema 根目录：/home/runner/work/space/space
[INFO] pydantic=2.14.3
[INFO] OCRData ← /home/runner/work/space/space/orchestrator/schemas/ocr.py
[INFO] VLMData ← /home/runner/work/space/space/orchestrator/schemas/vlm.py
[INFO] 待校验 2 页

[PASS] book01_p01 ocr.json  status=ok
[PASS] book01_p01 vlm.json  status=ok
[PASS] exif01_p01 ocr.json  status=ok
[PASS] exif01_p01 vlm.json  status=ok

结论：2 页全部通过公共 Schema 校验
```

同一 run 里另外两步也是绿的：`86 passed, 0 failed`、`13/13 通过`（当时 workflow 用 `run_all.py`）。
原始日志可在该 run 的 **Artifacts → m2-check-logs** 下载（tests.log / isolated.log / schema.log）。

本地复跑（任意环境）：

```powershell
git clone https://github.com/liushizhang32-source/space.git C:\code\space
cd C:\code\space
python paperbook-ai-m2\paperbook-ai\scripts\validate_with_orchestrator.py `
    --repo-root . --from paperbook-ai-m2\paperbook-ai\samples\example
```

## 6. 本次执行未覆盖

- 真实 PaddleOCR / 真实 VLM 的推理质量与耗时；
- 真实授权绘本（Schema 校验只覆盖 2 页合成样本）；
- 同页并发；
- 阶段硬超时（编排层职责）；
- 更复杂的版式（多栏、旋转、密集文字）。

## 7. 应用评审修复文件后的变化（2026-11-08）

从 `MEMBER2_FIXED_FILES/` 应用了：

| 文件 | 变化 |
|---|---|
| `scripts/validate_with_orchestrator.py` | **校验器改为验收语义**：缺 `ocr`/`vlm` 任一文件、坏 JSON、`checked==0` 均退出 1 |
| `tests/test_public_checker.py` | 校验器回归（`SCHEMA_REPO_ROOT` 必填）；第五轮后扩到 22 项 |
| `requirements-test.txt` | pytest + `opencv-python-headless==5.0.0.93` |
| `.github/workflows/m2-vision-checks.yml` | 改用 `pytest tests`，公共校验作为硬门禁（`set -euo pipefail`） |

本地已验：`run_all` 86 passed、隔离自检 13/13、严格校验器对样本 2 页 4 产物全 PASS；
缺文件与坏 JSON 两种情形均退出 1。

### 7.1 CI 实跑结果（run #5，分支 `zhc`，19s，全绿）

| 步骤 | 实际输出 |
|---|---|
| `Install test dependencies` | 8–10s 通过 → `opencv-python-headless==5.0.0.93` 在 Linux **有 wheel** |
| `Unit and checker regressions` | **`94 passed in 2.09s`**（`SCHEMA_REPO_ROOT=/home/runner/work/space/space`，Python 3.12.16） |
| `Isolated check` | 0s 通过（13/13） |
| `Public Schema gate` | `pydantic=2.14.3`；`OCRData ← .../orchestrator/schemas/ocr.py`；`VLMData ← .../orchestrator/schemas/vlm.py`；`[PASS]` × 4；**`结论：2 页、4 个产物全部通过公共 Schema 校验`** |

同一提交在 PR #3 上触发的 run #6（`pull_request` synchronize，17s）同样全绿，PR 显示 `2/2` 检查通过。

## 8. 第五轮评审（V5）修复：F01–F05（2026-11-09）

V5 结论 B，两条主要问题：**严格整数负例被弱化**（1.0 → 1.5）、**批量枚举只扫 OCR 且不核对身份/尺寸**。
本轮按 F01–F05 逐条改，没有修改公共 Schema、没有新增公共字段。

### 8.1 F01 严格整数负例恢复并扩展

- `tests/test_public_checker.py` 恢复 `1.0`，保留 `1.5`，并按 OCR / VLM 两侧参数化加入 `True`、`"1"`；
  共 `2 × 4 = 8` 项。断言仍是“检查器必须退出 1”。
- 理由（承认上一版判断错误）：公共坐标是 `StrictInt`，`1.0` 本来就该被拒；
  只测 `1.5` 无法区分 strict 与 lax —— 宽松模型会收下 `1.0`、`True`、`"1"`，
  而 `1.5` 在两种模式下都被拒，等于把“识别旧宽松模型”的能力让掉了。
- 现在把“实际用的是哪版契约”写进证据：`validate_with_orchestrator.py` 打印
  `OCRData ← <路径>  sha256=<文件 SHA>`、`VLMData ← …`；workflow 新增
  `Record schema provenance` 步骤，打印 `commit=<git rev-parse HEAD>`、`ref/event`、Python 版本，
  并 `sha256sum orchestrator/schemas/ocr.py orchestrator/schemas/vlm.py`，写入 `m2-logs/provenance.log` 并随 artifact 上传。

### 8.2 F02 枚举改为 OCR/VLM 并集

- `_page_ids()` 同时 glob `*_ocr.json` 与 `*_vlm.json` 取前缀并集；
  `--all`（`data/json`）与 `--from`（扁平目录）都走它。
- 只有 VLM 的页现在会被枚举出来，随后因缺 OCR 判 `[FAIL]`，不再被静默跳过。

### 8.3 F03 文件名 / 配对身份 / 尺寸一致性

逐页新增三类检查（都在公共模型校验之后）：

1. 内容 `page_id` 必须等于文件名前缀，否则 `[FAIL] <page> <kind>.json 内容 page_id='…' 与文件名不一致`；
2. 成对时核对 `book_id`、`page_no`、`image_width`、`image_height` 两侧一致；
3. 任一侧缺失或校验失败时不做配对比较（避免级联噪声）。

### 8.4 本机复测（严格整数仿真契约 + 真实样例数据）

| 用例 | 命令 | 结果 |
|---|---|---|
| 成功样本 | `validate_with_orchestrator.py --repo-root .tmpcheck\space --from samples\example` | `2 页、4 个产物全部通过`，rc=0 |
| 混合目录缺 OCR | 同上，目录含 book01 成对 + 只有 `book02_p01_vlm.json` | `[FAIL] book02_p01 ocr.json 不存在`，rc=1 |
| 混合目录缺 VLM | 只有 `book02_p01_ocr.json` | `[FAIL] book02_p01 vlm.json 不存在`，rc=1 |
| 文件名与内容不符 | vlm 内容改成 `page_id=book02_p01` | `[FAIL] … 与文件名不一致`，rc=1 |
| 配对尺寸不符 | vlm `image_width` 1240→1241 | `[FAIL] … image_width 不一致：ocr=1240 vlm=1241`，rc=1 |
| 严格整数 | bbox[0] = 1.0 / 1.5 / true / "1" | 4 种都 `[FAIL]`，rc=1 |
| 旧 runner | `python tests/run_all.py` | `86 passed, 0 failed` |
| 隔离自检 | `python scripts/isolated_check.py` | `13/13 通过` |

> 说明：本机没有 pytest、也没有真实 `orchestrator/schemas`，上表的严格整数项用**本地仿真契约**（StrictInt 语义 + 递归 bbox 检查）验证“检查器会正确判失败”；真实公共模型下的 108 项由 CI 执行，日志见 Actions artifact `m2-check-logs`。

### 8.5 F04 / F05 文档与边界

- F04：`examples/consume_vision.py` 头部改成明确的**草稿**声明——缺 `StoryData` 必填字段（至少 `model`），
  不得当正式 C3 交付；M2 的交付边界仍是 `*_ocr.json` / `*_vlm.json`。
- F05：`docs/ISOLATED_TEST.md` 统一口径——`run_all` = 旧 86 项（不需要 pytest）、
  `pytest tests` = 全量（86 + 检查器回归 22 = **108**）、隔离自检 = 13；
  退出码 2 表示**未验证**，CI 里任何非零退出都算失败，不存在“退出 2 但 CI 绿”。
