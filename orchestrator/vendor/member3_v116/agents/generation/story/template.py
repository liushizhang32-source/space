"""模板通道（mock）：不调模型，用 OCR/VLM 的内容直接拼故事。

用途：
  1. 没配 LLM 时的默认通道，保证全链路能跑（演示必须说明这是 mock 故事）；
  2. LLM 挂了且 STORY_FALLBACK_ON_ERROR=1 时的兜底。
产物 model.name 固定为 "mock-template"，不会和真实模型产物混淆。
"""

from __future__ import annotations

from .draft import DraftSegment, StoryDraft
from .text import normalize, pack, split_sentences, to_beats

MOCK_MODEL = "mock-template"


def page_text(ocr: dict | None) -> str:
    if not ocr:
        return ""
    blocks = ocr.get("text_blocks") or []
    ordered = sorted(
        (b for b in blocks if isinstance(b, dict) and (b.get("text") or "").strip()),
        key=lambda b: (b.get("order") or 0, b.get("block_id") or ""),
    )
    return normalize("".join(str(b["text"]).strip() for b in ordered))


def page_objects(vlm: dict | None) -> list[dict]:
    if not vlm:
        return []
    return [o for o in (vlm.get("objects") or []) if isinstance(o, dict) and o.get("object_id")]


def labels_in(narration: str, objects: list[dict]) -> list[str]:
    hits = [o["object_id"] for o in objects if (o.get("label") or "") and str(o["label"]) in narration]
    return hits


def _wordless_segments(description: str, objects: list[dict], tags: list[str], age_level: str) -> list[DraftSegment]:
    beats: list[str] = list(split_sentences(description))
    for obj in objects:
        label = str(obj.get("label") or "").strip()
        if not label:
            continue
        if age_level == "3-6":
            beats.append(f"看，这是{label}。")
        else:
            beats.append(f"画面里出现了{label}。")
    if not beats and tags:
        beats = [f"这里是{'、'.join(tags[:3])}。"]

    # 无字书靠画面推进，句子短一点，分镜更自然
    segments = [
        DraftSegment(narration=text, scene=description, highlight_object_ids=labels_in(text, objects))
        for text in pack(beats, limit=45)
    ]
    return segments


def build_template_draft(ocr: dict | None, vlm: dict | None, age_level: str) -> StoryDraft:
    text = page_text(ocr)
    objects = page_objects(vlm)
    description = normalize(str((vlm or {}).get("description") or ""))
    tags = [str(t) for t in ((vlm or {}).get("scene_tags") or []) if str(t).strip()]

    if text:
        beats = to_beats(text)
    else:
        return StoryDraft(
            title=_title_from(None, objects, tags),
            segments=_wordless_segments(description, objects, tags, age_level),
            model_name=MOCK_MODEL,
        )

    segments = [
        DraftSegment(
            narration=beat,
            scene=description,
            highlight_object_ids=labels_in(beat, objects),
        )
        for beat in beats
    ]
    return StoryDraft(
        title=_title_from(text, objects, tags),
        segments=segments,
        model_name=MOCK_MODEL,
    )


def _title_from(text: str | None, objects: list[dict], tags: list[str]) -> str:
    if text:
        first = split_sentences(text)[0] if split_sentences(text) else text
        title = first.rstrip("。！？!?；;，, ")[:16]
        if title:
            return title
    if tags:
        return "·".join(tags[:2])[:20]
    if objects:
        label = str(objects[0].get("label") or "").strip()
        if label:
            return f"{label}的一页"[:20]
    return "书页上的故事"
