# M2 互动阶段视觉能力说明

> 版本：V1.2.4 附带（2026-11-12）
> 定位：在原有“绘本页 OCR + VLM”之外，补齐**版面结构、跨页对象关联、视频帧识别、触控命中**。
> 边界：全部为 sidecar 或独立返回结构，**不改动 C1/C2 冻结字段**，不定义 canonical 身份。

## 1. 职责对照

| 新增职责 | 实现位置 | 输出 |
|---|---|---|
| 文字识别 + 版面结构 | `src/vision/layout.py` | `vision_layout/0.1` |
| 人物/动物/物品/场景识别 | `src/vision/characters.py` | `vision_objects/0.1` 目录 |
| 跨页人物与物体关联 | `characters.cluster_objects` | 候选簇 + 跨页 links |
| 当前视频帧物体识别 | `src/vision/frame.py` | `vision_frame/0.1` |
| 触控目标定位 | `frame.hit_test` | 命中的 object |
| 返回 ID/类别/位置/置信度 | 三者统一 | `object_id`/`category`/`bbox`/`confidence` |
| 同一角色跨帧关联 | `frame.link_frame_to_page` | frame→page 关联（候选） |

## 2. 版面结构 `build_layout(page_id, c1)`

输入是已通过校验的 C1；输出：

```json
{
  "schema_version": "vision_layout/0.1",
  "page_id": "book01_p01",
  "has_text": true,
  "column_count": 2,
  "columns": [{"column_id": "col_01", "block_ids": ["book01_p01_t01"], "x1": 40, "x2": 520}],
  "reading_order": ["book01_p01_t01", "book01_p01_t02"],
  "blocks": [{"block_id": "book01_p01_t01", "order": 0, "text": "...", "bbox": [40, 80, 520, 160]}],
  "truncated": false
}
```

规则：横向重叠 ≥ 较窄块宽度的 50% 视为同列；列从左到右、列内从上到下；
列数上限 6，超出时右侧合并并置 `truncated=true`。

## 3. 对象目录与跨页关联 `characters.py`

`build_object_catalog(pages)`：`pages` 是 `page_id → C2`。输出扁平对象列表，
每个对象带 `page_id`、`category`（person/animal/scene/object/other）与原始 bbox。

`cluster_objects(pages)`：按 `(category, label)` 分组，输出

```json
{
  "cluster_id": "cc_001",
  "category": "person",
  "label": "人物",
  "identity_status": "unknown",
  "method": "label_heuristic",
  "page_ids": ["book01_p01", "book01_p02"],
  "instances": [{"page_id": "book01_p01", "object_id": "book01_p01_o01", "bbox": [], "confidence": 0.8}]
}
```

**这是候选关联，不是身份识别**：同标签不同角色也会进同一簇，因此
`identity_status` 恒为 `unknown`，不产出 `canonical_id`/`character_id`（归 M1 决定）。

## 4. 帧识别与触控 `frame.py`

```python
doc = recognize_frame(image, vlm_backend, frame_id="f001", page_id="book01_p01")
hit = hit_test(doc, x, y)                 # 命中最小的包含框
links = link_frame_to_page(doc, page_doc) # 帧对象 → 页面对象（候选）
```

- 安全：复用 `safety.evaluate_vlm_safety`，非空 flags、缺失 safety、来源不可信 → `SafetyBlocked`（3004），不产出帧文档；
- 置信度缺失记 0.0 并计数，不做默认值填充；
- `hit_test` 使用 x2/y2 开区间，与 C1 坐标约定一致；
- 关联打分 = 0.6×标签一致 + 0.4×画布内中心距离，低于 0.5 不产出。

## 5. 已验证 / 未验证

已验证（`tests/test_layout.py`、`test_characters.py`、`test_frame.py`，共 17 项）：
双列阅读顺序、空页、列数上限、类别映射、跨页同标签成簇、簇上限、
object_id 前缀校验、帧 ID、非空 flags 拦截、缺 safety 拦截、命中最小框、跨帧关联。

未验证：
1. 真实绘本多栏/竖排/图文混排的版面准确率；
2. 同一角色跨页/跨帧的**身份**判别（当前只到标签级候选）；
3. 视频帧的真实模型时延与稳定性（本机 `qwen2.5vl:3b` 单帧约 2–10 s，未做批量统计）；
4. 触控命中在缩放/旋转显示下的坐标换算（由前端按原图坐标处理）。

## 6. 与 M1/M3 的接口

- 这些 sidecar 都是**私有候选协议**，未进入公共 C1/C2；
- 若 M1 需要消费，应以 M1 Gate 源码为准逐字段对齐（见
  `docs/M2_V1.2.4_ROOT_CAUSE_REMEDIATION_PLAN.md` §9）；
- 点读链路：`hit_test` 命中 → `object_id` → `index` 里的讲解缓存 → 返回 1–2 句；
  帧场景下先 `link_frame_to_page` 再查讲解。
