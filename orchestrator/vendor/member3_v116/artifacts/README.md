# 测试产物说明（artifacts/）

本轮（v1.1.4 / `wzy622-patch-1`）用**离线 mock** 跑出来的真实文件，用于证明：

- Story 产物符合 C3 与公共 StoryData 边界（`status=ok`、`scene` 非空、
  `highlight_object_ids` 默认 `[]` 且属于本页、`safety_flags` 默认 `[]`）；
- TTS 产物是**真实存在、可解码**的音频文件；
- Video 产物是**真实存在、可解码**的 mp4 文件，发布采用“提交点/回滚/清理”分离的成对事务。

> **重要**：故事是 `mock-template` 拼的，音频是**静音**（`TTS_ENGINE=silent`）。
> 这些文件用于验证链路与文件有效性，不代表真实模型效果。

## 目录

```
artifacts/
├── manifest.json                版本、生成时间、文件 sha256、mock 标注
├── story/
│   ├── input_ocr.json / input_vlm.json / input_page.png
│   ├── output_story.json        C3 输出（StoryDoc 校验通过）
│   ├── schema_check.txt
│   └── cli_stdout.json
├── tts/
│   ├── request.json / response.json
│   ├── tts_sample.mp3           静音，24000Hz mono mp3
│   └── probe.txt / probe.json
└── video/
    ├── input_story.json / output_video.json
    ├── book01_p03_video.mp4     720x1280 / 25fps / 7.67s
    ├── probe.txt / probe.json
    ├── schema_check.txt
    └── cli_stdout.json
```

## 怎么复现

```bash
export DATA_DIR=./_artifact_work
export FFMPEG_PATH=/path/to/ffmpeg FFPROBE_PATH=/path/to/ffprobe
export TTS_ENGINE=silent

python examples/install_example.py
python -m agents.generation story --page-id book01_p03
python -m agents.generation tts   --text "从前有只小兔子，住在森林边上。"
python -m agents.generation video --page-id book01_p03
python -m agents.generation run   --page-id book01_p03
```
