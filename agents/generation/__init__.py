"""成员 3 负责模块：Story 生成 / TTS / 视频合成。

契约见 docs/API_v1.0.md（PDF 版 ZSZB-API-1.0）：
  - json/{page_id}_story.json   (C3)
  - json/{page_id}_video.json   (C4)
  - POST /api/v1/tts            (A6)
"""

__all__ = ["config", "errors", "ids", "schemas", "storage"]
