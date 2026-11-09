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
| `tests/test_public_checker.py` | 校验器回归（`SCHEMA_REPO_ROOT` 必填）；第七轮后扩到 32 项 |
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
- 理由（承认上一版判断错误）：契约要求 bbox 是**原图像素整数**，`1.0` / `True` / `"1"` 都不该通过；
  只测 `1.5` 区分不了 strict 与 lax —— `1.5` 在两种模式下都被拒，等于把“识别宽松取整”的能力让掉了。
  至于公共模型到底是 `StrictInt` 还是普通 `int`，第一次 CI 给出了答案，见 §8.6。
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

> 说明：本机没有 pytest、也没有真实 `orchestrator/schemas`，上表的严格整数项用**本地仿真契约**（StrictInt 语义 + 递归 bbox 检查）验证“检查器会正确判失败”；真实公共模型下的 118 项由 CI 执行，日志见 Actions artifact `m2-check-logs`。

### 8.5 F04 / F05 文档与边界

- F04：`examples/consume_vision.py` 头部改成明确的**草稿**声明——缺 `StoryData` 必填字段（至少 `model`），
  不得当正式 C3 交付；M2 的交付边界仍是 `*_ocr.json` / `*_vlm.json`。
- F05：`docs/ISOLATED_TEST.md` 统一口径——`run_all` = 旧 86 项（不需要 pytest）、
  `pytest tests` = 全量（86 + 检查器回归 32 = **118**）、隔离自检 = 13；
  退出码 2 表示**未验证**，CI 里任何非零退出都算失败，不存在“退出 2 但 CI 绿”。

### 8.6 首次 CI 复盘：仓库里的公共模型其实是“宽松 int”（2026-11-09）

commit `650c30e`（分支 `zhc`）第一次跑新版门禁，结果 **失败**：
`6 failed, 102 passed in 1.64s`。

失败的 6 项全部是严格整数用例，报错都是 `assert 0 == 1`（检查器放行）：

```
FAILED tests/test_public_checker.py::test_non_strict_integer_bbox_is_failure[1.0-ocr]
FAILED tests/test_public_checker.py::test_non_strict_integer_bbox_is_failure[1.0-vlm]
FAILED tests/test_public_checker.py::test_non_strict_integer_bbox_is_failure[True-ocr]
FAILED tests/test_public_checker.py::test_non_strict_integer_bbox_is_failure[True-vlm]
FAILED tests/test_public_checker.py::test_non_strict_integer_bbox_is_failure['1'-ocr]
FAILED tests/test_public_checker.py::test_non_strict_integer_bbox_is_failure['1'-vlm]
```

`1.5` 的 2 项（OCR / VLM 各 1）**通过**（被正确拒绝）。这个组合说明一件事：
`zhc` 分支 Head 上的 `orchestrator/schemas` 里 bbox 是**普通 `int`**，pydantic
宽松模式把 `1.0`、`True`（→1）、`"1"`（→1）静默接受，只拒绝带小数的 `1.5`。
本机 pydantic 2.14.2 可复现同样行为：

```
1.0  -> ACCEPT [1, 10, 20, 30]
1.5  -> REJECT  int_from_float
True -> ACCEPT [1, 10, 20, 30]
'1'  -> ACCEPT [1, 10, 20, 30]
```

需要把两个 Git 版本分开看，不能混为一谈：

| 来源 | bbox 类型 | 说明 |
|---|---|---|
| `zhc` 分支 Head（push 触发的那次 CI） | 普通 `int`（宽松） | 本节的 6 红就发生在这里 |
| `dev` 与 PR #3 的合并预览（`pull_request` 触发） | **`StrictInt`** | 评审直接读取合并预览树确认 |

所以准确说法是：**旧 `zhc` Head 上的公共模型是宽松 `int`**；当前稳定的 `dev`
公共模型已经是 `StrictInt`。两者是不同 Git 版本的文件，不能用前者推断后者。
M1 不需要、也不应该为了适配旧分支去改冻结的 Schema。

**处理方式（不改公共 Schema）：** 在检查器里加了一层与模型无关的严格整数预检
`_strict_int_bbox_errors()`：对 `text_blocks[].bbox` 与 `objects[].bbox` 逐个元素判
`isinstance(v, bool) or not isinstance(v, int)`，命中即 `[FAIL]`，不再让模型去兜底。
这样不论公共模型将来收紧还是保持宽松，我们的门禁都能稳定拒绝 `1.0 / True / "1"`。

**复测（本机）：**

| 用例 | 结果 |
|---|---|
| 宽松仿真模型（`_lax.py`，行为同上）+ 干净样本 | `2 页、4 个产物全部通过`，rc=0 |
| 同上，bbox[0] 改为 `1.0` / `1.5` / `true` / `"1"` | 4 种都 `[FAIL] … 坐标类型不符合契约`，rc=1 |
| 严格仿真契约（`.tmpcheck\space`）干净样本 / `1.0` | rc=0 / rc=1（行为一致） |
| `python tests/run_all.py` | `86 passed, 0 failed` |
| `python scripts/isolated_check.py` | `13/13 通过` |

> 给队长的提示：**旧 `zhc` Head** 对 bbox 是宽松 `int`，跨模块传来的 `1.0`
> 或 `"1"` 会被静默取整成 `1`，`True` 会变成 `1`；当前 `dev` 已是 `StrictInt`，
> 不需要改动冻结 Schema。M2 侧无论公共模型松开还是收紧，门禁都按严格整数验收。

### 8.7 修复后的 CI 结果链（2026-11-09）

| run | 触发 | 结果 | 说明 |
|---|---|---|---|
| #13 | push `26cba5a` | 红（`6 failed, 102 passed`） | 修复文件被传到 `space/paperbook-ai/paperbook-ai-m2/paperbook-ai/`，根模块没被改到；见下方“上传路径坑” |
| #15 | push `232bc14` | **绿（23s）** | 文件落到正确的 `paperbook-ai-m2/paperbook-ai/`；`pytest` 全绿（含 32 项检查器回归），`Public Schema gate` 通过 4 个产物 |
| #17 | push `8ef045f7125fa95de729e3e1f93451047dd9980d` `Delete paperbook-ai directory` | **绿（23s）** | 删除误传残片后仍全绿，证明清理没有破坏门禁 |
| #18 | PR #3 synchronize | **绿（25s）** | PR 侧同样通过 |

> **上传路径坑（已记入交接注意）**：GitHub 的 “Upload files” 页面路径是**相对你当前所在目录**的。
> 当时浏览器停在 `space/paperbook-ai/`，拖入 `paperbook-ai-m2` 后文件落成
> `space/paperbook-ai/paperbook-ai-m2/paperbook-ai/...`，列表显示的 `/paperbook-ai-m2/...`
> 也是相对路径，看起来完全正确。结果 CI 读的仍是仓库根那份旧代码，于是同一批 6 条红重复出现。
> 判断办法：提交前确认浏览器面包屑在**仓库根**（只显示 `space /`），列表路径与仓库树逐级对得上。
> 该残片已在本轮删除（commit `8ef045f7125fa95de729e3e1f93451047dd9980d`），根目录现在只有 `.github/`、`docs/`、
> `orchestrator/`、`paperbook-ai-m2/`、`README.md`。

**run #17 的 `Record schema provenance` 原始输出**（对应 commit `8ef045f7125fa95de729e3e1f93451047dd9980d`）：

```
[INFO] commit=8ef045f7125fa95de729e3e1f93451047dd9980d
[INFO] ref=refs/heads/zhc event=push
Python 3.12.16
（两行 sha256sum 输出：orchestrator/schemas/ocr.py、vlm.py）
```

> 两个 schema 文件的 SHA-256 **不在这里手工转录**：上一版文档里的哈希是照着截图
> 手抄的，字符有错位（评审 R7-04 已指出）。权威值以 run #17 页面底部
> `Artifacts → m2-check-logs` 里的 `provenance.log` 为准，逐字节复制。
> 本包附带的 `docs/logs/` 里不含该文件（它只存在于 CI 产物中）。

这五行就是“CI 到底验了哪一版公共契约”的硬证据：commit 固定、Python 版本固定、
两个 schema 文件的 SHA-256 固定。评审若要复现，只要 checkout 这个 commit，
`sha256sum orchestrator/schemas/{ocr,vlm}.py` 对得上即可。

## 8.8 第七轮评审（V7）四项修复（2026-11-09）

V7 结论 B，确认 F01–F05 已落实，另提 4 项收尾。逐条处理如下。

| 编号 | 问题 | 修复 | 本机证据 |
|---|---|---|---|
| R7-01 | 检查器遇 `[]`、`null` 等非对象 JSON 会抛未处理异常 | `validate_with_orchestrator.py` 在 `json.loads` 后加 `isinstance(doc, dict)` 守卫，判 `[FAIL] … 顶层不是 JSON 对象（list）` 后 `continue`，不计入成功 | `[]` → rc=1，无 Traceback；同目录好页仍 `[PASS]` |
| R7-02 | 文件名错配负例被公共模型提前拒绝，没覆盖到新增检查 | 新 helper `repage()` 把文档整体改成另一页（含 `block_id`/`object_id` 前缀），内容自洽、只与文件名不符 | book02 内容存成 `book01_p01_vlm.json` → rc=1，打印 `与文件名不一致` |
| R7-03 | 缺 README 要求复制的 `.env.example` | 补回 `.env.example`（全 stub 默认、真实后端注释、无密钥）；README 同步说明 | 文件 902 B，`VISION_OCR_BACKEND=stub` |
| R7-04 | 提交号、指纹、版本说明有笔误 | `8f045f1` → 完整 `8ef045f7…`；provenance 两行 SHA 不再手抄，改指 artifact；`1.5` 项数 4→2；补 Head(int) / dev(StrictInt) 对照 | 见 §8.6、§8.7 |

回归：`tests/run_all.py` 86 passed、`scripts/isolated_check.py` 13/13、仿真契约 2 页 4 产物 rc=0；
校验器回归由 22 项增至 32 项（全量 118）。

## 9. 真实绘本首跑（2026-11-09，本机）

> 目的：把“只在合成样本上验过”的缺口补上。本节只证明**流水线在真实页面上跑通**，
> 不构成准确率结论（见 9.4 的取样限制）。

### 9.1 输入

| 项 | 值 |
|---|---|
| 文件 | `data/books/demo01/p01.png` |
| 实际格式 / 尺寸 | WEBP（按内容识别），1080 × 1080 |
| 大小 | 286,966 B |
| 来源 | 电商页面的书内页照片（仅本机自测，未进 git、未进交付包） |

注：扩展名是 `.png`、内容是 WEBP。PIL 按文件头识别，能正常读；下游产物里的
`image_width/height` 取自实际解码尺寸。

### 9.2 命令

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m vision.cli `
  --image data\books\demo01\p01.png --book-id demo01 --page-no 1 `
  --ocr-backend paddle --vlm-backend http --strict --data-dir data
```

`--strict`：后端不可用即失败，不回退 stub。

### 9.3 结果

| 阶段 | 结果 | 耗时 |
|---|---|---|
| OCR（PaddleOCR PP-OCRv5 mobile） | `status=ok`，8 个文本块，平均置信度 0.97 | 3,710 ms |
| VLM（`qwen2.5vl:3b`，Ollama） | `status=ok`，3 个 objects，`safety.pass=true` | 2,815 ms |
| 契约自检 | `contract: ok`，进程退出码 0 | — |
| 公共 Schema 校验 | 1 页 2 产物 `[PASS]`，rc=0 | — |

OCR 识别到的正文（原样）：

```
兔妈妈又说：“现在已经
很晚了，你必须要睡觉了。”
小兔子摇晃着脑袋说：
“为什么我要睡觉呢？”
```

另外 3 个块是钟面数字 `3` / `6` 和左边缘被裁掉的残句（`色了。` / `妈，我`），
与 9.4 的裁切说明一致。

VLM 产物：`description=小兔子和兔妈妈在餐桌前讨论睡觉时间`，objects 为
`兔子 [259,402,580,1032]`、`兔子 [691,179,1080,1032]`、`花 [442,389,562,582]`
（坐标已换算回原图像素）。

### 9.4 取样限制（不能当准确率）

这张图是**电商详情页里的方形截图**，不是整页扫描：

- 左右被裁，句子首尾缺失（所以出现 `色了。` 这种残句）；
- 右下角有 `post.smzdm.com` 水印，可能被识别成噪声字符；
- 页面有透视和反光，不是标准扫描条件。

因此本节只能作为“真实图片能跑通 + 产物结构正确”的证据。要出准确率数字，
需要整页扫描图 + 人工转写 GT，再走 `eval/metrics.py` 的 CER 流程。

### 9.5 首跑暴露的两个真问题（已修）

**问题 1：`qwen3-vl:4b` 是思考型模型，结构化输出不稳定。**
首次用默认 `qwen3-vl:4b`（`QWEN_VL_MAX_TOKENS=4000`）时 VLM 阶段失败：

```
[STAGE] vlm 失败 code=2001 36179ms
data/logs/demo01_p01_vlm.error.json:
{"page_id":"demo01_p01","stage":"vlm","code":2001,"message":"RuntimeError","elapsed_ms":36179}
```

直接调用后端拿到真实原因：`VLM 只返回了思考内容、正文为空`（36 秒全花在思考上）。
把 token 加到 8000 后，时好时坏——一次能出正文但 `VLM 返回非 JSON`，另一次仍然为空。
结论：思考型模型不适合这里的“短 JSON、低延迟”场景。

处理：`.env` 默认模型改为 `qwen2.5vl:3b`（非思考型），同一页 JSON 解析成功、耗时
2.8 s；`qwen3-vl:4b` 保留为质量对照选项，但需要更大 token 且结果不稳定。

**问题 2：VLM 把 prompt 里的示例值原样抄了出来。**
改模型后第一次输出 `objects` 只有 1 个，`label` 竟是 `中文通用名词`——正是 prompt
格式示例里的占位词，模型直接照抄。同时 `safety` 缺失，被 fail-closed 判成
`{"pass": false, "flags": ["safety_missing"]}`（这个行为是对的，但等于每页都不安全）。

处理（`src/vision/backends/qwen_vl.py`）：

- 示例改成具体值 `"label": "兔子"`；
- 规则 4 明确写“写画面里真实存在的东西……**不要照抄上面示例里的词**”。

复跑后 objects 变成 `兔子 / 兔子 / 花`，`safety.pass=true`，`flags=[]`。

### 9.6 回归

改动只动了 prompt 文案，未动解析与契约逻辑：

- `tests/run_all.py` → **86 passed, 0 failed**；
- 真实页两件产物过严格仿真契约：`结论：1 页、2 个产物全部通过公共 Schema 校验`（rc=0）。

### 9.7 下一步

1. 换整页扫描/正拍图重跑，确认 bbox 与文字完整性；
2. 覆盖不同版式（纯图页、满字页、大标题页、深色页）各 1–2 页，记录 `status` 与耗时波动；
3. 有 GT 的页跑 `eval/run_batch.py` + `eval/metrics.py` 出 CER；
4. 真实页结果稳定后，再把 §9 升级为“真实绘本评测”，并注明样本量。


