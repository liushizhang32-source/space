"""文本切分：把 OCR 文本切成能直接送进 TTS 的短句（≤120 字）。"""

from __future__ import annotations

import re

#: TTS 单段上限 120 字，这里留 10 字余量给标点与后续拼接
SOFT_LIMIT = 110
SENTENCE_END = "。！？!?；;\n"
CLAUSE_END = "，,、：:"


def normalize(text: str) -> str:
    return re.sub(r"[ \t\u3000]+", " ", (text or "").replace("\r", "\n")).strip()


def split_sentences(text: str) -> list[str]:
    """按句末标点切句，保留标点。"""
    text = normalize(text)
    if not text:
        return []
    parts = re.split(rf"(?<=[{SENTENCE_END}])", text)
    return [p.strip() for p in parts if p.strip()]


def split_long(sentence: str, limit: int = SOFT_LIMIT) -> list[str]:
    """超长句子先在逗号处切，仍超长就硬切。"""
    sentence = sentence.strip()
    if len(sentence) <= limit:
        return [sentence] if sentence else []

    chunks: list[str] = []
    buffer = ""
    for piece in re.split(rf"(?<=[{CLAUSE_END}])", sentence):
        if not piece:
            continue
        if len(buffer) + len(piece) <= limit:
            buffer += piece
            continue
        if buffer:
            chunks.append(buffer)
        buffer = piece
        while len(buffer) > limit:
            chunks.append(buffer[:limit])
            buffer = buffer[limit:]
    if buffer:
        chunks.append(buffer)
    return [c.strip() for c in chunks if c.strip()]


def pack(beats: list[str], limit: int = SOFT_LIMIT, max_segments: int = 20) -> list[str]:
    """把短句贪心装进 ≤limit 字的段，段数不超过 max_segments。

    超过 max_segments 时把相邻最短的两段合并（合并后仍超限就放弃合并，
    宁可多一段也不截断原文）。
    """
    segments: list[str] = []
    buffer = ""
    for beat in beats:
        if not beat:
            continue
        if not buffer:
            buffer = beat
            continue
        if len(buffer) + len(beat) <= limit:
            buffer += beat
        else:
            segments.append(buffer)
            buffer = beat
    if buffer:
        segments.append(buffer)

    while len(segments) > max_segments:
        best = min(
            range(len(segments) - 1),
            key=lambda i: len(segments[i]) + len(segments[i + 1]),
        )
        merged = segments[best] + segments[best + 1]
        if len(merged) > limit:
            break
        segments[best : best + 2] = [merged]

    return segments


def to_beats(text: str, limit: int = SOFT_LIMIT) -> list[str]:
    beats: list[str] = []
    for sentence in split_sentences(text):
        beats.extend(split_long(sentence, limit))
    return beats
