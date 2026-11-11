# 视觉模块 · 独立运行方法

> 面向验收：不需要中枢、不需要 TTS、不需要前端，单独验证 OCR 与 VLM。

## 0. 环境

```powershell
cd paperbook-ai
.venv\Scripts\python.exe -V          # 3.12.x
.venv\Scripts\python.exe scripts/check_env.py
```

`check_env.py` 会打印 Python 版本、PaddleOCR / VLM 可用性、`DATA_DIR` 可写、冒烟结果。
**OCR 依赖**：`paddleocr` + `paddlepaddle`（模型缓存在 `models/.paddlex`）。
**VLM 依赖**：任意 OpenAI 兼容端点（本机 Ollama 或云 vLLM），由 `.env` 配置。

## 1. 只跑 OCR

```powershell
.venv\Scripts\python.exe run.py `
  --image samples/demo_page.png `
  --book-id book01 --page-no 1 `
  --only ocr
```

产出：`data/json/book01_p01_ocr.json`（**不会**生成 `_vlm.json`）。

## 2. 只跑 VLM

VLM 需要 VLM 服务已启动（`.env` 里的 `QWEN_VL_BASE_URL`）：

```powershell
.venv\Scripts\python.exe run.py `
  --image samples/demo_page.png `
  --book-id book01 --page-no 1 `
  --only vlm
```

产出：`data/json/book01_p01_vlm.json`。此时 `ocr_text` 为空，模型只看图。

**失败时不会产出这个文件**（公共 `VLMData` 没有 `failed` 枚举），而是：

- 退出码 **5**；
- 错误详情写 `data/logs/{page_id}_vlm.error.json`；
- 删除同名旧文件，避免读到上次的过期结果。

## 3. 两个一起跑（默认）

```powershell
.venv\Scripts\python.exe run.py --image samples/demo_page.png --book-id book01 --page-no 1
```

## 4. 输出在哪、长什么样

```
data/json/{page_id}_ocr.json    C1 契约（OCR 失败时为 status=failed）
data/json/{page_id}_vlm.json    C2 契约（只有 ok / empty）
data/logs/{page_id}_{stage}.error.json   阶段失败详情
```

字段严格按公共 Schema，**不含** `producer` / `error` 等附加字段。
本地排障需要时，设 `VISION_EMIT_EXTRA=1` 才会附加（默认关闭）。

```powershell
$env:VISION_EMIT_EXTRA="1"
.venv\Scripts\python.exe run.py --image ... --only ocr
```

## 5. 用公共 Schema 验证

在联合仓库里（能 import 到 `orchestrator.schemas`）：

```powershell
.venv\Scripts\python.exe scripts/validate_with_orchestrator.py --page book01_p01
```

判定合格要**同时**满足：

1. 脚本退出码为 **0**（不是只看某一行 `[PASS]`）；
2. 所选阶段的产物全部通过：`--only ocr` 至少 `ocr.json` 通过，`--only vlm` 至少 `vlm.json` 通过，默认两者都要通过。

如果 import 不到公共模型，脚本会打印 `[UNVERIFIED]` 并返回**退出码 2**——
表示"未验证"，**不会**退回内置校验充当通过。

## 6. 关键环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `VISION_OCR_BACKEND` | `paddle` / `stub` | `paddle` |
| `VISION_VLM_BACKEND` | `http` / `stub` | `http` |
| `QWEN_VL_BASE_URL` | OpenAI 兼容端点 | 空（不可用则回退 stub） |
| `QWEN_VL_MODEL` | 模型名 | `qwen3-vl:4b` |
| `VISION_EMIT_EXTRA` | 是否附加 producer/error | `0` |
| `DATA_DIR` | 产物根目录 | `./data` |

## 7. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `[WARN] OCR 后端不可用 … 用 stub 输出` | 没装 paddleocr | 装依赖，或加 `--strict` 让错误暴露 |
| `vlm.json` 不存在、退出码 5 | VLM 服务没起 / 思考链吃光预算 | 看 `data/logs/{page}_vlm.error.json`；`curl .../v1/models`；调大 `QWEN_VL_MAX_TOKENS` |
| 输出含 `producer` | 设了 `VISION_EMIT_EXTRA=1` | 验收前取消该变量 |
| bbox 看着"错位" | 图片带 EXIF 方向 | 属正常：坐标为**原图文件像素**，见测试报告 EXIF 项 |
