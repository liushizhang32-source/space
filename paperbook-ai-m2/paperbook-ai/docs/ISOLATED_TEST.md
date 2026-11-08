# 隔离独立测试 · 操作手册

> 对应第四轮审查结论 A：可进入**隔离、无网、临时目录**的独立测试。
> 本手册的脚本不联网、不调模型、不依赖 Paddle/torch。

## 1. 测试前提（重要）

| 项 | 要求 | 原因 |
|---|---|---|
| 网络 | **断开或不可达** | 证明没有偷偷调外部服务 |
| DATA_DIR | 用临时目录，不碰正式 `data/` | 避免污染与旧产物干扰 |
| 日志原文 | 不设 `VISION_LOG_VERBOSE` | 默认日志只记异常类型，便于检查是否含敏感内容 |
| 并发 | 单进程、同页串行 | 模块内不加锁，靠编排层串行 |
| 依赖 | 仅 `Pillow` / `NumPy` | OCR/VLM 真模型不参与本轮 |

## 2. 一条命令

```powershell
cd paperbook-ai
python scripts/isolated_check.py
```

它会自己建一个 `data/_isolated_<uuid>/` 临时目录，跑完自动删除（`--keep` 可保留）。

**不需要** `.env`、不需要安装 Paddle、不需要 Ollama。

## 3. 预期输出

```
==================================================================
视觉模块 · 隔离自检（无网络 / 无模型 / 临时目录）
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

退出码 `0` = 全过；`1` = 有失败项（脚本会打印失败项与原因）。

## 4. 每项在验什么

| # | 验的东西 | 对应问题 |
|---|---|---|
| 01 | 两阶段产物齐全、字段集合与契约一致 | C1/C2 主路径 |
| 02 | 打桩结果显式 `safety=false` | R02 安全默认 |
| 03 | 无字页 `empty` 且置信度为 0 | C1 条件约束 |
| 04 | OCR 崩溃仍有 `failed` 契约 + 日志 | R01 |
| 05 | VLM 崩溃不写文件、超时映射 2002 | R03 / N01 |
| 06 | 后端返回 None 判失败（9002） | R03 |
| 07 | 畸形 bbox/inf/非字符串不中断 | R01 |
| 08 | EXIF 坐标系是文件原始像素 | M2-03 |
| 09 | 安全字段缺失/未知 → 不安全 | R02 |
| 10 | 超 99 块截断而非整页失败 | M2-06 |
| 11 | 省略 `safety_pass` 直接 TypeError | R02 |
| 12 | 失败不产出 `status=failed` 的 vlm 文件 | F01 |
| 13 | HTTP 超时包装链正确映射 2002 | N01 |

## 5. 公共 Schema 兼容性（需联合仓库）

隔离自检只验内部契约。要验公共 Pydantic 模型，**有联合仓库的 GitHub 地址就够了**：

```powershell
# 1) 拿到联合仓库
git clone https://github.com/<组织>/<仓库>.git C:\code\space

# 2) 直接读包里自带的样本目录（不用拷来拷去）
python paperbook-ai\scripts\validate_with_orchestrator.py `
    --repo-root C:\code\space `
    --from samples\example
```

`--from` 用于**扁平目录**（文件直接叫 `{page_id}_ocr.json` / `{page_id}_vlm.json`），
`samples/example/` 正是这种结构。

产物在正式数据目录（`data/json/`）时改用：

```powershell
python scripts/validate_with_orchestrator.py --repo-root C:\code\space --all
python scripts/validate_with_orchestrator.py --repo-root C:\code\space --page book01_p01
```

> **样本准备**：`samples/example/` 的 4 个 JSON 由当前代码生成（无 `producer` 等附加字段）。
> 用自己的产物时，先 `python run.py --image ... --book-id ... --page-no ...` 再 `--all`。
> **别拿旧产物去验**——早期文件可能残留 `producer`，严格模型会直接拒绝。

输出会打印 `pydantic 版本` 与两个模型的**实际文件路径**，确认不是导入到了别处：

```
[INFO] 公共 Schema 根目录：C:\code\space
[INFO] pydantic=2.14.2
[INFO] OCRData ← C:\code\space\orchestrator\schemas\ocr.py
[INFO] VLMData ← C:\code\space\orchestrator\schemas\vlm.py
[PASS] book01_p01 ocr.json  status=ok
[PASS] book01_p01 vlm.json  status=ok
```

判定：

- 退出码 `0`：公共 Schema 通过；
- 退出码 `1`：产物不符合公共模型（会打印具体字段错误）；
- 退出码 `2`：**拿不到公共模型 = 未验证**，不算通过。

> ⚠️ **先重新生成产物再验**：早期跑出来的 `vlm.json` 可能残留 `producer` 字段，
> 严格（`extra="forbid"`）的公共模型会直接拒绝。用当前代码重跑一次即可：
> `python run.py --image samples/demo_page.png --book-id book01 --page-no 1`

## 6. 本手册**不覆盖**

- 真实 PaddleOCR / 真实 VLM 的质量与耗时；
- 真实绘本（授权样本）；
- 并发写同一页；
- 阶段硬超时（由编排层的 timeout 决定，模块只做单次 HTTP 超时）；
- 联合仓库里其它依赖（本脚本只用到 pydantic 与两个 schema 模块）。

## 7. 失败排查

| 现象 | 可能原因 |
|---|---|
| `03` 失败 | `empty` 页的 `page_confidence` 被改成非 0 |
| `05` 失败且 code=2001 | 超时异常链断了：检查是否有人把异常重新包成无 `__cause__` 的新异常 |
| `08` 失败 | `image_width/height` 取了摆正后尺寸，而不是文件尺寸 |
| `12` 失败 | 有失败页写下了 `status=failed` 的 vlm.json（违反 VLMData 枚举） |
