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

> ✅ 2026-11-08 已在 `space` 仓库 GitHub Actions 用**真实** `orchestrator/schemas` 跑通：
> 2 页 4 个产物全部 PASS（详见 [RUN_REPORT.md](RUN_REPORT.md) 第 5 节）。
> 下面是本地复跑方式。

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

- 退出码 `0`：公共 Schema 通过（且**所有**被检查的产物都在）；
- 退出码 `1`：产物不符合公共模型，或缺文件/坏 JSON（会打印具体原因）；
- 退出码 `2`：**拿不到公共模型 = 未验证**，不算通过。

> ⚠️ 校验器按**验收**标准执行：`ocr.json` 与 `vlm.json` **缺一个就算失败**。
> 运行阶段 VLM 失败不产出文件是合法的（见 INTEGRATION），但那页不要放进验收样本目录。

> ⚠️ **先重新生成产物再验**：早期跑出来的 `vlm.json` 可能残留 `producer` 字段，
> 严格（`extra="forbid"`）的公共模型会直接拒绝。用当前代码重跑一次即可：
> `python run.py --image samples/demo_page.png --book-id book01 --page-no 1`

## 6. 在 GitHub 仓库上跑（Actions）

仓库里已带 workflow：`.github/workflows/m2-vision-checks.yml`。
它在 **ubuntu + Python 3.12** 上依次跑三条命令，并把日志挂成 artifact。

### 步骤

```powershell
# 1) 把模块推进联合仓库的自己的分支（不要直接推 main/dev）
cd C:\code\space
git checkout -b zhc-1
# 把 paperbook-ai/ 目录整个拷进来（或按你们的目录约定放置）
git add paperbook-ai
git commit -m "feat(vision): M2 视觉模块 + 隔离检查 workflow"
git push -u origin zhc-1
```

1. 在 GitHub 上对 `zhc-1 → dev` 开 Pull Request；
2. 进 **Actions** 页，选 `m2-vision-checks`，看这次 run；
3. 五个 step 的名字就是结论（与 `.github/workflows/m2-vision-checks.yml` 一一对应）：
   - `Unit and checker regressions` → 期望 `108 passed`（`pytest tests`，含校验器回归；数字以日志为准）
   - `Isolated check` → 期望 `13/13 通过`
   - `Public Schema gate` → 期望 `[PASS] … 结论：N 页、M 个产物全部通过公共 Schema 校验`
   - `Record schema provenance` → 记录 `commit`、Python 版本、两个 Schema 文件的 SHA-256
4. 页面底部 **Artifacts → m2-check-logs** 下载 `tests.log` / `isolated.log` / `schema.log` / `provenance.log`，可直接作为证据。

> 两套入口不要混：
> - `python tests/run_all.py` = **旧 86 项**，零依赖、不需要 pytest，也不含 `test_public_checker.py`；
> - `python -m pytest tests` = **全量**（86 + 检查器回归 22 = 108），需要 `pytest` 与 `SCHEMA_REPO_ROOT`。

也可以不开 PR，在 Actions 页点 **Run workflow**（`workflow_dispatch`）手动触发。

### 这条 workflow 的关键点

- **模块放哪都行**：第一步自动探测 `paperbook-ai/` 或 `paperbook-ai-m2/paperbook-ai/` 或仓库根；
  但 **workflow 文件本身必须放在仓库根的 `.github/workflows/`**，放在模块目录里不生效；
- **`--repo-root .`**：在联合仓库里这一步导入的就是**真实** `orchestrator.schemas.ocr/vlm`，
  不再是我本机的仿真模型；日志会打印模型文件路径与 SHA-256，便于核对“验的是哪版契约”；
- 找不到 `orchestrator/schemas` 时脚本返回 **2 = 未验证**，workflow 里所有 step 都是
  `set -euo pipefail`，**退出 2 会让 CI 变红**——未验证不是通过，不会再有“退出 2 但 CI 绿”的情况；
  字段真的不匹配返回 1，同样变红。

### 不想配 CI？用 Codespaces

仓库页 → **Code → Codespaces → Create codespace**，在云端终端里跑同样的三条：

```bash
cd paperbook-ai
python tests/run_all.py
python scripts/isolated_check.py
python scripts/validate_with_orchestrator.py --repo-root .. --from samples/example
```

（Codespaces 里仓库根是上一级，所以 `--repo-root ..`。）

## 7. 本手册**不覆盖**

- 真实 PaddleOCR / 真实 VLM 的质量与耗时；
- 真实绘本（授权样本）；
- 并发写同一页；
- 阶段硬超时（由编排层的 timeout 决定，模块只做单次 HTTP 超时）；
- 联合仓库里其它依赖（本脚本只用到 pydantic 与两个 schema 模块）。

## 8. 失败排查

| 现象 | 可能原因 |
|---|---|
| `03` 失败 | `empty` 页的 `page_confidence` 被改成非 0 |
| `05` 失败且 code=2001 | 超时异常链断了：检查是否有人把异常重新包成无 `__cause__` 的新异常 |
| `08` 失败 | `image_width/height` 取了摆正后尺寸，而不是文件尺寸 |
| `12` 失败 | 有失败页写下了 `status=failed` 的 vlm.json（违反 VLMData 枚举） |
