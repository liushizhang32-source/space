# 视觉模块对接说明（给 M1 / M3 / M4）

> 视觉模块（M2）的产物就两类：**两个 JSON 文件** + **一个索引文件**。
> 你们不需要 import 视觉代码，读文件就行（M4 点读建议直接调 `vision.index`）。

## 0. 产物在哪

| 文件 | 谁写 | 谁读 | 内容 |
|---|---|---|---|
| `data/json/{page_id}_ocr.json` | M2 | M3、M5 | 文本块 + bbox |
| `data/json/{page_id}_vlm.json` | M2 | M3、M5 | 画面描述 + 物体 + 场景标签 |
| `data/index/{page_id}.json` | M2 | M4（点读） | 物体索引（含轮廓、讲解） |

`page_id` 规则：`{book_id}_p{两位页码}`，如 `book01_p03`。
所有路径都在 `DATA_DIR` 下，默认 `./data`。

## 1. M3：写故事

### 你要读的字段

`ocr.json`
| 字段 | 用法 |
|---|---|
| `text_blocks[].text` | 页面文字，已按阅读顺序（`order`）排好 |
| `text_blocks[].bbox` | 原图像素坐标，做图文对齐时用 |
| `status` | `ok` / `empty`（无字绘本）/ `failed` |

`vlm.json`
| 字段 | 用法 |
|---|---|
| `description` | 一句话画面描述，**写故事的主输入** |
| `objects[].label` / `object_id` | 物体名与主键，写进 `highlight_object_ids` |
| `scene_tags` | 场景氛围（夜晚/森林），决定故事语气 |
| `image_width` / `image_height` | bbox 参照系，勿丢 |

### 空值怎么处理（重要）

| 情况 | 你该怎么做 |
|---|---|
| `ocr.status=empty` | 无字绘本，**只靠 `description` 出故事**，不要报错 |
| `vlm.json` **不存在** | 视为 VLM 阶段失败：只剩文字，用 `text_blocks` 出故事，页面标 `no_scene` |
| 两者都失败 | 这页没救，跳过，页面标 `failed` |

> 注意：`vlm.json` 永远不会出现 `status=failed`（公共 `VLMData` 只有 ok/empty）。
> 失败信号是「文件不存在 + `data/logs/{page_id}_vlm.error.json`」。

### 最小示例

`examples/consume_vision.py` 是一个可直接跑的起步模板：

```bash
python examples/consume_vision.py --page book01_p01
```

它会读两个 JSON，生成一份 **story 草稿**（符合 C3 结构：`title` / `segments[]` /
`duration_sec` / `highlight_object_ids`），你只要把 `narration` 换成 LLM 生成的文本。
草稿里的 `duration_sec` 是按 220 字/分钟估的，等 TTS 接上后要换成实测值，
并把 `duration_source` 改成 `tts`。

### 验收（3 条）

1. 给定一个 `page_id`，能读出文字与物体，不抛异常；
2. `empty` / `failed`（OCR）与「VLM 文件缺失」三种边界都能走通；
3. 产出的 `story.json` 里 `segment_id` 符合 `{page_id}_s{2位}`。

## 2. M4：点读与问答

### 点读（`input_type=tap`）

前端传点击坐标，后端查索引，**不调模型**：

```python
from vision import index as vindex

page = vindex.load("data", "book01_p01")       # 读 data/index/book01_p01.json
obj, how = vindex.hit_test(page, x, y)          # how: inside / nearest / miss
if obj is None:
    # 返回兜底话术，不要报错
    answer = "这里好像没有东西，你点点看别的地方？"
else:
    answer = vindex.explain(page, obj)          # 已缓存的儿童化讲解
    citations = [{"page_id": page.page_id,
                  "object_ids": [obj.object_id],
                  "bbox": list(obj.bbox)}]
```

`/qa` 响应里 `citations` 就填上面这个结构，和 A5 契约一致。

### 完整响应示例

```bash
python examples/consume_tap.py --page book01_p01 --x 660 --y 700
```

直接打印一条**符合 A5 契约的 `/qa` 响应 JSON**，M4 可以照抄字段：

```json
{
  "code": 0, "msg": "ok",
  "data": {
    "answer_id": "ans_demo0000000000000000000",
    "answer": "小白兔跳跳跳，发现胡萝卜啦。",
    "is_fallback": false,
    "citations": [{"page_id": "book01_p01", "object_ids": ["book01_p01_o02"],
                   "bbox": [595, 509, 744, 877]}],
    "audio_url": null,
    "safety": {"pass": true, "flags": []},
    "latency_ms": {"asr": 0, "llm": 0, "tts": 0, "total": 0}
  },
  "trace_id": "tr_demo"
}
```

> `audio_url` 由 M3 的 TTS 填；`latency_ms` 由你实测填。点读链路本身 <1ms。

### 语音问答（`input_type=voice/text`）

M2 不参与。但**答案要引用画面**时，用 `story.json` 的 `segments[].highlight_object_ids`
或索引里的 `object_id`，这样前端能高亮。

### 验收（3 条）

1. 点物体返回正确 label + 讲解；
2. 点空白返回兜底话术，`code` 仍为 0（不是错误）；
3. 连续点 100 次不崩、不卡（索引常驻内存）。

## 3. M1：编排

视觉模块就是一个函数调用，同步阻塞、无状态：

```python
from vision.backends import build_ocr_backend, build_vlm_backend
from vision import pipeline

ocr_backend = build_ocr_backend()   # 读 .env，默认 paddle
vlm_backend = build_vlm_backend()   # 读 .env，默认 http(Ollama/vLLM)

result = pipeline.run_page(
    image_path="/path/to/page.jpg",
    book_id="book01", page_no=3,
    data_dir="data",
    ocr_backend=ocr_backend,
    vlm_backend=vlm_backend,
)
result.ocr["status"]   # ok / empty / failed
result.vlm["status"]
```

**注意**：`run_page` 不抛模型异常，会返回结构化结果：

- **OCR 失败** → 仍写 `ocr.json`（`status=failed`），`result.ocr_error` 带错误；
- **VLM 失败** → **不写 `vlm.json`**，`result.vlm_error` 带错误 + 错误日志；
- 构造/校验异常也走同一条通道，不会中断。

你按 `ocr.json` 的 `status` 与 `vlm.json` 是否存在判页面状态（§1.7 三级状态）。

后端只初始化一次，进程常驻；每次调用只是推理，不要反复 `build_*`。

### 耗时参考（本机 CPU）

| 阶段 | 单页耗时 |
|---|---|
| PaddleOCR | 2–5 s |
| VLM（Qwen3-VL 4B，含思考） | 20–26 s |
| 索引 + 分割 | <1 s |
| 点读 | <0.05 ms |

> 8 页绘本：OCR ≈ 30 s，VLM ≈ 3 min。企业赛云 GPU 上 VLM 会快一个数量级。

### 阶段失败怎么读（重要）

| 情况 | 磁盘表现 | 中枢该怎么处理 |
|---|---|---|
| OCR 失败 | `ocr.json` 存在，`status=failed` | 按 §1.14 降级为 `no_ocr`，页面 `partial` |
| VLM 失败 | **`vlm.json` 不存在** | 判 `no_scene`，页面 `partial`；别等文件出现 |
| 字段不合规 | 文件不落盘 | 同上，按阶段失败处理 |

失败详情在 `data/logs/{page_id}_{stage}.error.json`：

```json
{"page_id": "book01_p01", "stage": "vlm", "code": 2001,
 "message": "VLM 请求失败: ...", "elapsed_ms": 2086}
```

命令行退出码：`0` 成功、`3` 后端不可用、`4` 字段不合规、`5` 阶段失败。
**`contract: ok` 只代表字段合规，不代表阶段成功**。

## 4. 常见坑

| 坑 | 说明 |
|---|---|
| bbox 坐标系 | 全是**原图像素**，不是归一化。前端按 `image_width/height` 缩放 |
| 文件编码 | 全部 UTF-8，`ensure_ascii=False`，别用 GBK 读 |
| `order` 语义 | 文本块从 1 连续编号，直接按它排序 |
| `object_id` 主键 | `label` 只用于展示，关联一律用 `object_id` |
| 索引缺失 | 没跑 `build_index.py` 就没有点读，返回 404/兜底，不要崩 |
| 重复生成 | 同名文件直接覆盖，前端靠 `job_id` 区分批次 |
