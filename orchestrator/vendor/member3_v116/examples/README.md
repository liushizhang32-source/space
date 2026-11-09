# 示例输入数据

这里放一页**假的绘本页**，字段严格按 `docs/API_v1.0.md` 的 C1（ocr.json）/ C2（vlm.json）来写，
用来在成员 2 的真实 OCR/VLM 产物到位前，把成员 3 的 story → tts → video 全链路跑通。

| 文件 | 对应契约 | 说明 |
|---|---|---|
| `book01_p03_ocr.json` | C1 OCR 产物 | 两行文字、`status: ok`、图幅 900×1200 |
| `book01_p03_vlm.json` | C2 VLM 产物 | 画面描述 + 两个物体（兔子/树）+ 场景标签 |
| `book01_p03_orig.png` | 原图 | `uploads/{page_id}_orig.png`，也就是视频的底图 |

> 这一页的图是脚本画的示意图，**不是真实绘本书页**；文字块 bbox 与画面内容只是用来演示坐标与流程。

## 怎么用

```bash
# 1) 装进 DATA_DIR（默认 ./data，可用 DATA_DIR 环境变量改）
python examples/install_example.py

# 2) 跑全链路（会写 json/{page_id}_story.json、json/{page_id}_video.json、videos/*.mp4）
python -m agents.generation run --page-id book01_p03 --age-level 3-6

# 3) 看产物
cat data/json/book01_p03_story.json
ls data/videos/
```

也可以直接 `python -m agents.generation demo --overwrite`，那条路会**重新生成**一页 mock 输入，
不依赖这个目录。

## 注意

- `audio_url` / `video_url` 会按 `ASSET_BASE_URL`（默认 `http://127.0.0.1:8000`）拼成绝对地址；
  本机验证时如果没起静态服务，URL 打不开但文件是真实存在的，按 `DATA_DIR` 下的相对路径去拿即可。
- 示例里没有 API Key、没有真实模型调用；想接真实模型改 `.env` 里的 `LLM_*` / `TTS_HTTP_URL`。
