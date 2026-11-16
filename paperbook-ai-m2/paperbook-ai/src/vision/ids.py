"""ID 规则（对齐 docs/API_v1.0.md §1.2.2）。

契约要点：
- book_id 禁止含下划线，保证 page_id 能用最后一个 ``_p`` 切分；
- 所有派生 ID 稳定可复现，禁止随机 UUID；
- block_id / object_id 由成员2 生成，两位序号从 01 开始。
"""

from __future__ import annotations

import re

BOOK_ID_PATTERN = r"^[a-z][a-z0-9]{3,11}$"
PAGE_ID_PATTERN = r"^(?P<book_id>[a-z][a-z0-9]{3,11})_p(?P<page_no>\d{2})$"

_BOOK_RE = re.compile(BOOK_ID_PATTERN)
_PAGE_RE = re.compile(PAGE_ID_PATTERN)


class IdError(ValueError):
    """ID 不满足契约。"""


def validate_book_id(book_id: str) -> str:
    if not isinstance(book_id, str) or not _BOOK_RE.match(book_id):
        raise IdError(f"book_id 非法: {book_id!r}，需匹配 {BOOK_ID_PATTERN}")
    return book_id


def make_page_id(book_id: str, page_no: int) -> str:
    """book01 + 3 -> book01_p03"""
    validate_book_id(book_id)
    if isinstance(page_no, bool) or not isinstance(page_no, int):
        raise IdError(f"page_no 必须是整数: {page_no!r}")
    if not 1 <= page_no <= 99:
        raise IdError(f"page_no 必须在 1..99（page_id 用两位编码）: {page_no}")
    return f"{book_id}_p{page_no:02d}"


def parse_page_id(page_id: str) -> tuple[str, int]:
    match = _PAGE_RE.match(page_id or "")
    if not match:
        raise IdError(f"page_id 非法: {page_id!r}，需匹配 {PAGE_ID_PATTERN}")
    return match.group("book_id"), int(match.group("page_no"))


def block_id(page_id: str, order: int) -> str:
    return f"{page_id}_t{_two_digit(order)}"


def object_id(page_id: str, order: int) -> str:
    return f"{page_id}_o{_two_digit(order)}"


def _two_digit(n: int) -> str:
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 99:
        raise IdError(f"序号必须是 1..99 的整数（两位编码）: {n!r}")
    return f"{n:02d}"
