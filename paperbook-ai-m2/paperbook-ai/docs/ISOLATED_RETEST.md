# 隔离复测报告（V9 复审后，2026-11-09）

> 目的：在不依赖联合仓库、不联网、不加载真实模型的前提下，验证交付包
> `paperbook-ai-m2.zip` 能否独立跑通，并逐项记录退出码。
> 这是**执行记录**，不是测试手册；手册见 `docs/ISOLATED_TEST.md`。

## 一、被测对象

| 项 | 值 |
|---|---|
| 包 | `paperbook-ai-m2.zip` |
| 文件数 | 98（97 个内容文件 + `docs/logs/manifest.txt`） |
| 字节数 | 1,014,261 |
| SHA-256 | `7C04701C9DB3F2188DD72CD1D0F28C7CC323424F987F6C75ACD821934242356B` |

## 二、隔离条件

| 项 | 做法 |
|---|---|
| 代码 | 解压到独立目录，与工作区、联合仓库无共享路径；`PYTHONPATH` 只指向包内 `src` |
| 网络 | `HTTP_PROXY` / `HTTPS_PROXY` 指向 `http://127.0.0.1:9`，任何外呼立即失败 |
| 模型 | 全程 `--ocr-backend stub --vlm-backend stub`，不加载 PaddleOCR、不调用 Ollama |
| 数据 | `DATA_DIR` 指向隔离目录内的空目录，不读工作区 `data/` |
| 解释器 | 本机 venv 的 `python.exe`（3.12.14）；只借用解释器与已装依赖，不借用任何代码 |

## 三、步骤与结果

| # | 检查 | 命令 | 退出码 | 结果 |
|---|---|---|---|---|
| 0 | 包结构 | `dir` 一级目录 | 0 | 与源码树一致，无 `.venv`/`models`/`data`/`.env` |
| 1 | 单元测试 | `python tests/run_all.py` | 0 | **86 passed, 0 failed** |
| 2 | 隔离自检 | `python scripts/isolated_check.py` | 0 | **13/13 通过** |
| 3 | 环境自检 | `python scripts/check_env.py` | 0 | 依赖 OK；后端为 stub；`DATA_DIR` 可写；冒烟 1 页 ok |
| 4 | CLI 全流程 | `python -m vision.cli --image samples/demo_page.png --book-id iso01 --page-no 1 --ocr-backend stub --vlm-backend stub --strict` | 0 | 产出 `iso01_p01_ocr.json`（460 B）、`iso01_p01_vlm.json`（769 B） |
| 5 | 产物契约自检 | 包内 `vision.validate` + 逐字段断言 | 0 | **15/15 通过**（见下） |
| 6 | 提示词版本 | 检查 `src/vision/backends/qwen_vl.py` | 0 | 含 `"label": "兔子"` 与“不要照抄上面示例里的词” |
| 7 | 清单核对 | 逐文件重算 SHA-256 | 0 | 清单 97 项，**0 项不符**（跑完后目录内会多出 `data/`、`__pycache__`、`tests/.tmp` 等运行产物，未计入清单） |

### 第 5 步的 15 条断言

```
[PASS] OCR page_id 与文件名一致
[PASS] VLM page_id 与文件名一致
[PASS] OCR status 合法  ok
[PASS] VLM status 合法（仅 ok/empty）  ok
[PASS] 两文件 book_id/page_no 一致
[PASS] 两文件 image_width/height 一致
[PASS] 尺寸等于原图  1240x1754
[PASS] OCR bbox 全为整数且在原图内  1 块
[PASS] VLM bbox 全为整数且在原图内  2 个物体
[PASS] OCR block_id 唯一
[PASS] VLM object_id 唯一
[PASS] VLM safety 是显式布尔  {'pass': False, 'flags': ['stub_mock']}
[PASS] 内部校验器接受 OCR
[PASS] 内部校验器接受 VLM
[PASS] 内部校验器拒绝 VLM status=failed
```

> `safety.pass=False, flags=['stub_mock']` 是 stub 后端的打桩行为，用于证明
> “安全字段必须是显式布尔、缺失不会被当成安全”；真实判定由模型给出。

完整输出见 `docs/logs/isolated_retest.log`。

## 四、这次复测覆盖不到什么（如实列出）

| 项 | 原因 | 由谁覆盖 |
|---|---|---|
| `pytest` 全量 118 项 | 本机未安装 pytest，且离线无法安装 | GitHub Actions（run #19 / #20 已实测 `118 passed`） |
| 真实公共 Schema 校验 | 隔离目录里没有 `orchestrator/schemas` | CI 的 `Public Schema gate`（2 页 4 产物 `[PASS]`） |
| OCR / VLM 的真实质量 | 故意不加载模型 | 真实绘本首跑记录（`docs/RUN_REPORT.md` §9），仅证明跑通、不构成准确率 |
| 并发与超时 | 单页串行执行 | `tests/test_pipeline.py` 与 `isolated_check.py` #13 |

## 五、V9 指出的唯一未闭环项

V9 复审指出：包内 `src/vision/backends/qwen_vl.py` 含两处提示词修改
（示例词改为“兔子”、新增“不要照抄上面示例里的词”），而那次 CI 跑的是仓库里
**没有这两处修改**的旧文件，因此“源码 51/52 一致”。

本复测第 6 步确认包内确实是修改后的版本。要把证据链闭合，需要把这个文件本身
提交进 `zhc` 分支，让 CI 覆盖到同一份字节；提交后的 run 号会补记到
`docs/RUN_REPORT.md` §8.7。

## 六、复现命令（Windows PowerShell）

```powershell
# 1) 解压到独立目录
Expand-Archive paperbook-ai-m2.zip -DestinationPath .\retest
cd .\retest\paperbook-ai

# 2) 断网 + 只用包内代码
$env:PYTHONPATH = "$PWD\src"
$env:HTTP_PROXY = $env:HTTPS_PROXY = "http://127.0.0.1:9"
$env:DATA_DIR   = "$PWD\..\data"

# 3) 三条主检查
python tests\run_all.py
python scripts\isolated_check.py
python scripts\check_env.py

# 4) 单页全流程（stub）
python -m vision.cli --image samples\demo_page.png --book-id iso01 --page-no 1 `
  --ocr-backend stub --vlm-backend stub --strict
```
