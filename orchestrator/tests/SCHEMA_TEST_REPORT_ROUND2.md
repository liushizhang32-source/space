# Schema 第二轮修复与复测报告

## 现场与范围

- 日期：2026-11-05（Asia/Hong_Kong）。
- 仓库：`C:\Users\16173\Documents\ChatGPT\人工智能+\space`。
- 开始及结束分支：`dev`；HEAD：`009d9ed7875ef71b95a6582600ecea89cc98cfa8`，与报告基准相同，未执行重置或切换分支。
- 检查仓库内及工作目录祖先路径，未发现适用的 AGENTS.md。
- 初始已跟踪文件无改动；已有五个未跟踪文件为第一轮 conftest.py、requirements-test.txt、SCHEMA_TEST_REPORT.md、schema-test-results.xml、test_schema_contract.py。均保留，未覆盖、删除或暂存。
- 依据：docs/API_v1.0.md 第一章、第一轮报告和测试。只修复授权的四类问题；未开发 Mock、路由、数据库或其他业务功能。
- 未修改全局 Git 配置。仅在 Git 命令中使用本次进程的精确 safe.directory 参数解决沙箱用户与仓库所有者不同的问题；未读取 .env 或密钥，修复及测试未发网络请求。

## 实际运行环境

| 项目 | 实测值 |
|---|---|
| 解释器 | `C:\Users\16173\Documents\ChatGPT\人工智能+\.venv-schema-tests\Scripts\python.exe` |
| Python | 3.12.14 |
| Pydantic | 2.14.1 |
| pytest | 9.2.0 |
| serialize_by_alias 配置 | 在当前 ConfigDict 中受支持 |

沿用第一轮独立环境，不使用损坏的 PATH python，未安装、升级或更改依赖。所有 pytest 命令均在仓库根目录运行，进程设置 `$env:PYTHONDONTWRITEBYTECODE='1'`，不生成字节码缓存。

## 执行命令、退出码与统计

实际调用解释器为上述路径，命令使用相对于仓库根目录的 `..\.venv-schema-tests\Scripts\python.exe`。

先执行六个原失败用例：

```powershell
& '..\.venv-schema-tests\Scripts\python.exe' -m pytest orchestrator/tests/test_schema_contract.py -q --tb=short -W error -p no:cacheprovider -k 'test_bbox_forbids_integral_float or test_capture_absolute_preview_url or test_safety_pass_default_json_serialization or test_story_highlight_object_id_format'
```

结果：6 passed，301 deselected，退出码 0。这里的 deselected 是定向复测筛选，不是跳过或弱化用例。

按本轮提供的参数尝试完整命令：

```powershell
& '..\.venv-schema-tests\Scripts\python.exe' -m pytest orchestrator/tests -q --tb=short -W error -p no
```

退出码 1，启动错误为 `Error importing plugin "no": No module named 'no'`。该命令没有运行测试，不能视为测试失败或测试通过。`-p no` 会尝试加载名为 no 的插件；据第一轮命令改为 `-p no:cacheprovider` 禁用缓存插件后执行完整测试：

```powershell
& '..\.venv-schema-tests\Scripts\python.exe' -m pytest orchestrator/tests -q --tb=short -W error -p no:cacheprovider
```

结果：409 passed in 0.59s，退出码 0。

为独立统计原始与新增用例，再分别执行：

```powershell
& '..\.venv-schema-tests\Scripts\python.exe' -m pytest orchestrator/tests/test_schema_contract.py -q --tb=short -W error -p no:cacheprovider
& '..\.venv-schema-tests\Scripts\python.exe' -m pytest orchestrator/tests/test_schema_round2.py -q --tb=short -W error -p no:cacheprovider
```

| 测试组 | 总数 | 通过 | 失败 | 跳过 | xfail | xpass | 收集/运行错误 | 退出码 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 原始测试 | 307 | 307 | 0 | 0 | 0 | 0 | 0 | 0 |
| 新增针对性回归 | 102 | 102 | 0 | 0 | 0 | 0 | 0 | 0 |
| 完整 orchestrator/tests | 409 | 409 | 0 | 0 | 0 | 0 | 0 | 0 |

原始 301 个通过用例无回归，原始 6 个失败用例全部修复；未删改原始测试，未新增 skip 或 xfail。`-W error` 下无警告转错误。未覆盖第一轮结果 XML，因此该历史 XML 仍反映第一轮的 6 项失败；第二轮以本报告的实际运行结果为准。

## 六个原失败用例最新结果

| 原测试名称 | 结果 |
|---|---|
| test_bbox_forbids_integral_float[ocr] | PASS，拒绝浮点坐标 |
| test_bbox_forbids_integral_float[vlm] | PASS，拒绝浮点坐标 |
| test_capture_absolute_preview_url | PASS，拒绝相对路径 |
| test_safety_pass_default_json_serialization[safety] | PASS，默认输出 pass |
| test_safety_pass_default_json_serialization[nested_vlm] | PASS，嵌套默认输出 safety.pass |
| test_story_highlight_object_id_format | PASS，拒绝 oBAD 后缀 |

## 修改文件与兼容性影响

| 文件 | 最小修复 | 兼容性影响 |
|---|---|---|
| orchestrator/schemas/ocr.py | bbox 四个元素由 int 改为 StrictInt | 拒绝整数值浮点、小数、布尔值、数字字符串；合法 JSON 整数数组及 JSON 数组输出保留。原长度、非负、顺序、面积与图像边界校验不变；未启用整个模型 strict 模式。 |
| orchestrator/schemas/vlm.py | bbox 同上；仅 VLMSafety 配置新增 serialize_by_alias=True | 内部 pass_、输入 pass/pass_ 兼容性、显式 by_alias=True 均保留；独立和嵌套默认 model_dump/model_dump_json 使用 pass。未修改公共基类或全局策略。 |
| orchestrator/schemas/capture.py | preview_url 增加字段验证器：现有 Pydantic HttpUrl 验证 HTTP(S) 与主机合法性，标准库 urlsplit 确认原始 URL 中存在主机 | 字段仍为 str，返回原字符串，合法输入的大小写、编码、端口与路径不归一化。拒绝相对路径、非 HTTP(S)、无主机与非法主机/端口；不改变存储层相对路径规则，不新增依赖，不访问网络。 |
| orchestrator/schemas/story.py | highlight_object_ids 每个字符串通过 Annotated/Field 沿用完整 object_id 正则 | 保留原当前页面归属校验、省略及默认空列表；仅拒绝畸形 ID，无跨模块依赖、无 VLM 文件存在性查询。 |
| orchestrator/tests/test_schema_round2.py（新增） | 102 个参数化针对性回归 | 原始测试未改动。 |
| orchestrator/tests/SCHEMA_TEST_REPORT_ROUND2.md（新增） | 本报告 | 第一轮报告保留。 |

新增测试统计：bbox 每元素严格类型的 Python/JSON 输入 64 项、合法整数数组往返 2 项、合法 URL 原值保留 6 项、非法 URL 11 项、独立/嵌套安全字段输入兼容与默认/显式别名输出 8 项、合法高亮 2 项、畸形高亮 6 项、跨页高亮 2 项、省略高亮字段与默认列表隔离 1 项，共 102 项。合法同页 o99 明确通过，不引入跨文件存在性检查。

## 保留歧义与测试限制

- Story 图片尺寸：§1.2.3 的页面产物尺寸要求与 C3 示例不一致，继续等待队长裁定，不增字段。
- OCR order：实现要求连续无缺口，文档仅明确从 1 开始；保持现状。
- C1/C2 等列表必填性及默认值不够明确；继续保留现有行为，不改变任何无关字段、枚举、必填性或默认值。
- 仅验证当前 Python 3.12.14/Pydantic 2.14.1/pytest 9.2.0 环境；不宣称覆盖所有历史 Pydantic 2.x 版本。默认别名配置依赖环境支持，当前环境无阻塞。
- 本轮没有 FastAPI 路由、HTTP 集成、上传处理、OCR/VLM/Story 模型调用、TTS 或跨文件业务验收；本次通过仅代表上述 Schema 修复及回归范围。
- 所给 `-p no` 的启动错误已记录并通过明确插件参数解决，无剩余测试执行阻塞。

## 最终检查与建议

最终差异仅包含四份授权 Schema 修改和两个本轮新增文件。API_v1.0.md、common.py 及五个第一轮文件均与开工时 SHA-256 一致；无无关改动。git diff --check 通过，暂存区无修改，分支及 HEAD 保持原值。

Schema 第二轮测试全部通过，建议进入队长验收。

队长确认后可安排后续 Mock 阶段；本轮没有开发 Mock，不代表接口契约已正式冻结验收。未暂存、提交、推送、合并或修改 main。
