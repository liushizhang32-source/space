"""用 M3 现有故事生成器消费 M1 授权的输入，产出候选 Generation 结果。

该函数是 M1 接入层与 M3 生成算法之间的最小胶水：输入只能是
`M1GenerationConsumer.read_inputs()` 返回的已授权 c1/c2 字节，
输出是待提交的候选结果字节；不读写本地 ocr/vlm 文件、不自行拼接路径。
"""

from __future__ import annotations

import json

from .config import Settings
from .story.builder import build_page_story

__all__ = ["story_payload"]


def story_payload(
    inputs: dict[str, bytes],
    *,
    age_level: str = "3-6",
    settings: Settings | None = None,
) -> bytes:
    """c1/c2（已授权字节）→ C3 故事 JSON 字节。"""
    ocr = json.loads(inputs["c1.json"])
    vlm = json.loads(inputs["c2.json"])
    page_id = ocr["page_id"]
    result = build_page_story(
        page_id,
        age_level,
        settings or Settings(),
        persist=False,
        ocr=ocr,
        vlm=vlm,
    )
    return json.dumps(
        result.doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
