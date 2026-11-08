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
| 4 | 同上，但注入一个多余字段 | **1**（预期失败） | `docs/logs/schema_negative.log` |

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

## 5. 在真实联合仓库上跑（待队长执行）

```powershell
git clone https://github.com/<组织>/<仓库>.git C:\code\space
cd paperbook-ai
python scripts/validate_with_orchestrator.py --repo-root C:\code\space --from samples\example
```

判读：

- 退出码 `0` → 公共 Schema 通过；
- 退出码 `1` → 字段不匹配，输出会指出具体字段（把这行发我即可修）；
- 退出码 `2` → 没找到 `orchestrator/schemas/ocr.py`，属于**未验证**。

## 6. 本次执行未覆盖

- 真实 PaddleOCR / 真实 VLM 的推理质量与耗时；
- 真实授权绘本；
- 同页并发；
- 阶段硬超时（编排层职责）；
- 真实公共模型（需联合仓库，见第 5 节）。
