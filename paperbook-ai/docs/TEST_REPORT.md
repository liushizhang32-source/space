# 第四轮交付说明与修复报告（M2 · 视觉）

> 对应 `MEMBER2_REVISION_REVIEW_V4.md`：静态结论 **A（可进入隔离独立测试）**。
> 本轮修 N01–N03 与 P3 说明残留，并交付隔离自检套件。
> 未修改 `API_v1.0.md`，未修改 `orchestrator/schemas`，未调用付费 API。

## 一、本轮做了什么

| 编号 | 问题 | 状态 | 位置 |
|---|---|---|---|
| N01 | HTTP 超时被包装后仍可能映射成 2001 | 已修 | `qwen_vl.py` 新增 `VlmTimeout`；`pipeline._is_timeout` 沿异常链判定 |
| N02 | VLM 缺失时 Story 草稿 `scene` 为空 | 已修 | `examples/consume_vision.py` 显式兜底 scene + 严格布尔 |
| N03 | OCR 评测的占位 VLM 仍写"安全通过"的文件 | 已修 | `eval/run_batch.py` 不启用 VLM 时 `run_vlm=False`，彻底不产出 |
| N05 | verbose 分支错误体无上限、非 JSON 异常带正文 | 部分修 | 错误体读取加 2MiB 上限；非 JSON 默认不带原文 |
| P3 | 注释仍称"公共 Schema 拒绝未知字段"；STANDALONE 只看单行 PASS | 已修 | 改为 §1.2.5 口径；判定改为"退出码 + 所有所选产物通过" |

新增交付：`scripts/isolated_check.py` + `docs/ISOLATED_TEST.md`（13 项离线自检）。

## 二、N01：超时映射

**原问题**：`_post` 把所有异常统一包成 `RuntimeError("VLM 请求失败: TimeoutError")`；
`_is_timeout` 只看外层类型名与消息里的 `timed out`，匹配不到 `TimeoutError` 这个字符串。

**修复**：

```python
class VlmTimeout(RuntimeError): ...        # 语义明确的超时类型

except (TimeoutError, socket.timeout) as exc:
    raise VlmTimeout("VLM 请求超时") from exc
except urllib.error.URLError as exc:
    if isinstance(exc.reason, (TimeoutError, socket.timeout)):
        raise VlmTimeout("VLM 连接超时") from exc
```

`pipeline._is_timeout` 改为**沿 `__cause__` / `__context__` / `URLError.reason` 遍历**，
不再依赖消息文本。

**证据**（隔离自检 #13）：把 `urlopen` 替换成抛 `URLError(timeout)`，
断言 `VlmTimeout` 抛出且 `_stage_error` 给出 `2002`。

## 三、N02：Story 草稿空 scene

**原问题**：VLM 缺失时 `scene_tags=[]` → `scene=""`，而公共 `StorySegment.scene` 要求非空。

**修复**（`examples/consume_vision.py`）：

- `scene` 兜底为 `"绘本画面（自动兜底）"`，并注明这是示例兜底、非正式 C3；
- 读外部 JSON 时先做类型检查（objects 必须是 dict 且含 `object_id`）；
- `safety_pass` 改为 `safety.get("pass") is True`——字符串 `"false"` 不再被 `bool()` 误转。

> 该草稿仍**不是**经公共 `StoryData` 验收的正式产物，只在文档里作为 M3 的起点模板。

## 四、N03：评测占位 VLM

**原问题**：`run_batch` 不启用 VLM 时仍传 `_NullVlm`，流水线正常写出 `empty` 的 vlm.json，
且占位结果 `safety_pass=True`。

**修复**：不启用时传 `vlm_backend=None, run_vlm=False`，**完全不产出 vlm.json**；
删除 `_NullVlm` 类。评测目录只含 OCR 产物，不会被误当 VLM 结果消费。

## 五、隔离自检（新增）

```powershell
python scripts/isolated_check.py
```

- 自建 `data/_isolated_<uuid>/` 临时目录，跑完删除；
- **不联网、不加载模型**，只用 stub / 假后端；
- 强制清除 `VISION_LOG_VERBOSE`，日志只含异常类型；
- 单进程同页串行。

13 项检查（详见 [ISOLATED_TEST.md](ISOLATED_TEST.md)）：

```
01 正常页产出两份契约        08 EXIF 坐标系为文件原始像素
02 stub safety=false         09 safety 缺失/未知 → 不安全
03 无字页 empty/0            10 超 99 块截断
04 OCR 崩溃 → failed+日志     11 省略 safety → TypeError
05 VLM 崩溃 → 无文件+2002     12 无 status=failed 的 vlm 文件
06 返回 None → 9002          13 HTTP 超时包装链 → 2002
07 畸形 OCR 不中断
```

**当前结果：13/13 通过**（本机）。

## 六、回归测试

两套入口，覆盖范围**不同**（不要互相替代）：

```
python tests/run_all.py      →  86 passed, 0 failed     # 本机已跑，无 pytest 也能跑（不含校验器回归）
python -m pytest tests -q    →  108 passed              # 全量：86 + 校验器回归 22；CI 执行
```

| 入口 | 依赖 | 覆盖 |
|---|---|---|
| `tests/run_all.py` | 仅 Pillow / NumPy | 86 条既有用例（旧入口） |
| `pytest tests` | + pytest、opencv（`requirements-test.txt`） | 86 条 + `test_public_checker.py` 22 项 |

`test_public_checker.py` 需要 `SCHEMA_REPO_ROOT` 指向带 `orchestrator/schemas` 的仓库根，
否则它自己会 `pytest.fail`（未验证不算通过）。CI 里已由 workflow 设置。

校验器回归 22 项的构成：基本完备性 5、严格整数负例 8（OCR/VLM × `1.0`/`1.5`/`True`/`"1"`）、
坏 JSON 1、缺公共模型 1、目录枚举盲区 2（混合目录里只有 VLM / 只有 OCR）、
文件名与内容不符 1、配对身份/尺寸不一致 4。

本轮未删除任何既有测试；N01–N03 的行为由隔离自检覆盖。

## 七、仍未闭环（如实列出）

1. **公共 Schema 已在 CI 用真实模型跑通**（2026-11-08，`space` 仓库 PR #3）：
   - run #2（旧 workflow）：`pydantic=2.14.3`，2 页 4 个产物 PASS；
   - **run #5（新 workflow，zhc，19s）**：`pytest` **94 passed in 2.09s**、
     `结论：2 页、4 个产物全部通过公共 Schema 校验`、
     `OCRData ← /home/runner/work/space/space/orchestrator/schemas/ocr.py`；
   - 第五轮评审（V5）后扩到 **108 项**并新增 provenance 记录，
     本轮复跑结果以 Actions 日志与 `m2-check-logs` artifact 为准（含 `commit` 与 Schema 文件 SHA-256）。
   仍未覆盖真实绘本与更复杂版式。
2. **真实 Paddle / VLM / 真实绘本未验证**：质量、耗时、阅读顺序均无实测。
3. **依赖与模型版本未锁定**：`requirements.txt` 仅 Pillow/NumPy。
4. **同页并发无锁**：需编排层按 `page_id` 串行；`_drop_stale` 删除失败被忽略。
5. **占位 confidence 0.75** 不可当校准概率。
6. **阶段硬超时**仍由调用方负责，模块只做单次 HTTP 超时。
7. **日志脱敏不完整**：默认不记原文，但不是字段白名单式脱敏。

## 八、复现命令

```powershell
# 隔离自检（无需模型）
python scripts/isolated_check.py

# 单元测试
python tests/run_all.py

# 公共 Schema（有联合仓库就能跑）
git clone https://github.com/<组织>/<仓库>.git C:\code\space
python scripts/validate_with_orchestrator.py --repo-root C:\code\space --all --data-dir data
```
