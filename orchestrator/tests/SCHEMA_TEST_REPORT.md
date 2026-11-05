# Schema 第一轮自动化测试报告

- 测试日期：2026-11-05（Asia/Hong_Kong）
- 仓库：liushizhang32-source/space
- 分支：dev；基准提交：009d9ed7875ef71b95a6582600ecea89cc98cfa8
- 判断依据：docs/API_v1.0.md 第一章；不采用附录作为实现要求。
- 环境：Python 3.12.14、Pydantic 2.14.1、pytest 9.2.0。
- 最终执行：307 项，301 通过，6 失败，0 跳过，0 xfail，0 收集错误；pytest 退出码 1。
- 使用 `-W error`，未出现额外的 Pydantic 弃用警告。

## 失败明细与建议

| 测试 | 实际行为与契约依据 | 建议（未实施） |
|---|---|---|
| test_bbox_forbids_integral_float[ocr] | OCRTextBlock 接受 `[0.0,0,10,10]` 并把浮点数转换为整数；§1.2.3 明确禁止浮点坐标。 | bbox 元素使用严格整数类型，例如 StrictInt，保留当前几何与边界校验。 |
| test_bbox_forbids_integral_float[vlm] | VLMObject 同样接受整数值浮点坐标，违反 §1.2.3。 | 同上。 |
| test_capture_absolute_preview_url | CaptureData 接受 `previews/page.jpg`；§1.15.3 要求 HTTP 响应由网关拼接为绝对 URL。 | 在响应模型或明确的响应出口校验绝对 HTTP(S) URL；采用 URL 类型时复核序列化输出兼容性。 |
| test_safety_pass_default_json_serialization[safety] | VLMSafety 默认 model_dump_json() 输出 `pass_`，C2 契约字段为 `pass`。 | 文件出口统一显式 by_alias=True，或在支持的 Pydantic 版本配置默认按别名序列化。 |
| test_safety_pass_default_json_serialization[nested_vlm] | VLMData 默认 model_dump_json() 嵌套输出 safety.pass_。 | 同上，并保留嵌套序列化测试。 |
| test_story_highlight_object_id_format | StoryData 接受 `book01_p03_oBAD`；目前只检查当前页前缀，未检查 §1.2.2 的 object_id 两位数字规则。 | 对 highlight_object_ids 的每个元素复用 object_id 格式校验，并继续检查所属页面。 |

安全序列化的两项失败属于默认出口风险：显式 `by_alias=True` 的独立与嵌套文档往返测试通过。尚未开发或测试 FastAPI 路由，不能据此断言未来 FastAPI 的实际 HTTP 输出一定错误。

## 覆盖与通过结果

- 原仓库全部 5 个 Python 文件均成功按包路径导入；新增 conftest 和测试模块也被 pytest 成功加载。
- 所有 11 种模型/泛型特化通过正式示例解析、Pydantic 2 API、显式别名 JSON 往返、JSON Schema 生成、字段集合与类型检查。
- 必填字段逐项删除测试、所有字段不兼容类型测试、默认值与列表默认值隔离检查通过。
- book_id/page_id/object_id/segment_id/block_id 正反格式、页身份一致性、子 ID 所属页检查通过。
- bbox 长度、负坐标、零面积、逆序、小数坐标、精确右/下边界及越界检查通过；整数值浮点数例外见失败。
- OCR empty 空块及零置信度、VLM empty 空物体及 object_id 唯一性检查通过。
- Story tts 分支缺失/null/空字符串音频拒绝，estimate 分支允许省略音频；未知 duration_source 拒绝。
- APIResponse[T] 成功、失败 null、泛型数据验证、trace_id 格式、默认值通过；同时允许 §1.9 的非零业务码携带 data，不错误强制所有失败 data=null。
- 未知字段被忽略，JSON Schema 未禁止 additionalProperties。

## 字段审计与契约不明确项

1. common / capture / ocr / vlm / story 及其嵌套模型的 JSON 别名字段集合、类型与相应正式示例一致，未发现拼写缺失或额外字段。VLM 的 pass_ 是 Python 内部名称，正确别名为 pass；默认输出风险另列。
2. C1、C2 未逐项列出必填性及默认值。目前 OCR.text_blocks、VLM.objects / scene_tags、safety.flags、Story.safety_flags 可省略并默认空列表；统一响应 code/msg/data 默认 0/ok/null。测试显式锁定当前实现快照，但不能把这些未写明的默认行为认定为正式契约已确认，也没有据示例强行要求全部字段必填。
3. §1.2.3 要求每个页面级产物提供 image_width/image_height，但 C3 Story 正式示例和 StoryData 都没有这两个字段。这是第一章内部表述不一致：请队长明确该要求是否仅适用于包含坐标的产物；本轮未擅自增字段，也未用相互冲突的条款制造确定性失败。
4. OCR 要求 order 连续无缺口，而 C1 仅明确从 1 开始；这是实现附加约束，建议队长确认。对象/片段完整页面前缀校验比 ID 表中的简写正则更严格，但符合其 `{page_id}` 派生规则。
5. Capture 当前仅提供响应 Schema，没有上传请求模型。multipart 文件格式/大小/长边、上传处理及 page_no 分配属于后续路由测试范围，本轮不宣称已验证。
6. bbox 在 JSON 中正确序列化为数组，Python 内部使用 tuple 并不构成字段类型差异。其他标量采用 Pydantic 默认宽松转换；本轮不擅自将全部字段改成 strict 模式。

## 复现

从仓库根目录执行（任意具备 requirements-test.txt 依赖的 Python 环境）：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pytest orchestrator/tests -q --tb=short -W error -p no:cacheprovider --junitxml=orchestrator/tests/schema-test-results.xml
```

本机测试解释器位于仓库外的 `../.venv-schema-tests/Scripts/python.exe`，该环境不属于提交内容。默认 PATH 的 python 是损坏的 MySQL 内置解释器，实际测试未使用它。pytest 已安装至独立环境，Pydantic 来自本机打包运行时。本轮仅验证 Pydantic 2.14.1，不代表所有历史 2.x 小版本兼容。

## 交付与结论

新增文件：conftest.py、test_schema_contract.py、requirements-test.txt、schema-test-results.xml、本报告（均在 orchestrator/tests/）。

未修改 API 文档及任何 Schema；未修改 main；未提交或推送。307 项中存在 6 项未通过，因此目前不能给出 Schema 契约验收通过结论。建议队长先确认上述修复与歧义处理，获批修复后重跑本套测试，再作为后续 FastAPI Mock 的验收基础。
