"""ID 规则与生成（对齐 API v1.0 §1.2.2）。

关键约束：
  - book_id 不含下划线，page_id 可用最后一个 "_p" 切分；
  - 派生 ID 稳定可复现，禁用随机 UUID；
  - job/answer/trace 用 ULID(26)，Crockford Base32，去掉 I/L/O/U。
"""

from __future__ import annotations

import hashlib
import os
import re
import time

BOOK_ID_RE = re.compile(r"^[a-z][a-z0-9]{3,11}$")
PAGE_ID_RE = re.compile(r"^[a-z][a-z0-9]{3,11}_p\d{2}$")
BLOCK_ID_RE = re.compile(r"^.+_t\d{2}$")
OBJECT_ID_RE = re.compile(r"^.+_o\d{2}$")
SEGMENT_ID_RE = re.compile(r"^.+_s\d{2}$")
JOB_ID_RE = re.compile(r"^job_[0-9A-HJKMNP-TV-Z]{26}$")
SESSION_ID_RE = re.compile(r"^ses_[a-z0-9]{8,32}$")
ANSWER_ID_RE = re.compile(r"^ans_[0-9A-HJKMNP-TV-Z]{26}$")
TRACE_ID_RE = re.compile(r"^tr_[0-9A-HJKMNP-TV-Z]{26}$")

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def is_book_id(value: str) -> bool:
    return bool(BOOK_ID_RE.match(value))


def is_page_id(value: str) -> bool:
    return bool(PAGE_ID_RE.match(value))


def book_id_of(page_id: str) -> str:
    """page_id -> book_id。book_id 不允许下划线，所以切最后一个 "_p" 是安全的。"""
    if not is_page_id(page_id):
        raise ValueError(f"page_id 格式非法: {page_id!r}")
    return page_id.rsplit("_p", 1)[0]


def page_no_of(page_id: str) -> int:
    if not is_page_id(page_id):
        raise ValueError(f"page_id 格式非法: {page_id!r}")
    return int(page_id.rsplit("_p", 1)[1])


def make_page_id(book_id: str, page_no: int) -> str:
    if not is_book_id(book_id):
        raise ValueError(f"book_id 格式非法: {book_id!r}")
    if not 1 <= page_no <= 99:
        raise ValueError("page_no 必须在 1~99（page_id 固定两位页码）")
    return f"{book_id}_p{page_no:02d}"


def segment_id(page_id: str, order: int) -> str:
    """{page_id}_s{2位}，order 从 1 开始。"""
    if not is_page_id(page_id):
        raise ValueError(f"page_id 格式非法: {page_id!r}")
    if not 1 <= order <= 99:
        raise ValueError("segment order 必须在 1~99")
    return f"{page_id}_s{order:02d}"


def ulid(timestamp_ms: int | None = None, randomness: bytes | None = None) -> str:
    """26 位 ULID：10 位时间 + 16 位随机。同毫秒内可排序，但不是 UUIDv4。"""
    ts = int(time.time() * 1000) if timestamp_ms is None else int(timestamp_ms)
    if not 0 <= ts < 1 << 48:
        raise ValueError("ULID 时间戳超出 48 位")
    rand = os.urandom(10) if randomness is None else randomness
    if len(rand) != 10:
        raise ValueError("ULID 随机部分必须是 10 字节")

    chars: list[str] = []
    t = ts
    for _ in range(10):
        chars.append(_CROCKFORD[t & 0x1F])
        t >>= 5
    time_part = "".join(reversed(chars))

    value = int.from_bytes(rand, "big")
    chars = []
    for _ in range(16):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return time_part + "".join(reversed(chars))


def new_job_id() -> str:
    return "job_" + ulid()


def new_trace_id() -> str:
    return "tr_" + ulid()


def new_answer_id() -> str:
    return "ans_" + ulid()


def tts_cache_key(text: str, voice_id: str, speed: float) -> str:
    """TTS 内容哈希（§1.10）：sha1(text + voice_id + speed) 前 12 位。

    规范化规则写在这里并进文档，保证同一句话在视频与问答两条路径命中同一缓存：
    text 原样（不 strip、不做标点归一）、voice_id 原样、speed 保留两位小数。
    """
    payload = f"{text}|{voice_id}|{speed:.2f}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:12]
