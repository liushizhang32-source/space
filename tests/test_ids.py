from __future__ import annotations

import re

import pytest

from agents.generation.ids import (
    book_id_of,
    is_page_id,
    make_page_id,
    new_job_id,
    new_trace_id,
    page_no_of,
    segment_id,
    tts_cache_key,
    ulid,
)

CROCKFORD = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_page_id_roundtrip():
    page_id = make_page_id("book01", 3)
    assert page_id == "book01_p03"
    assert book_id_of(page_id) == "book01"
    assert page_no_of(page_id) == 3
    assert is_page_id(page_id)


@pytest.mark.parametrize("bad", ["book01_p3", "Book01_p03", "book-01_p03", "b_p03", "book01_p100"])
def test_bad_page_ids_rejected(bad: str):
    assert not is_page_id(bad)
    with pytest.raises(ValueError):
        page_no_of(bad)


def test_book_id_with_underscore_is_rejected():
    # book_id 不允许下划线，否则 page_id 无法用最后一个 _p 切分
    with pytest.raises(ValueError):
        make_page_id("book_01", 3)


def test_segment_and_ulid_format():
    assert segment_id("book01_p03", 1) == "book01_p03_s01"
    for factory in (new_job_id, new_trace_id):
        value = factory()
        prefix, _, body = value.partition("_")
        assert CROCKFORD.match(body), value
    assert len({ulid() for _ in range(200)}) > 190


def test_tts_cache_key_is_stable_and_sensitive():
    key = tts_cache_key("你好", "female_warm", 1.0)
    assert key == tts_cache_key("你好", "female_warm", 1.0)
    assert len(key) == 12
    assert key != tts_cache_key("你好", "female_warm", 1.5)
    assert key != tts_cache_key("你好呀", "female_warm", 1.0)
    assert key != tts_cache_key("你好", "male_deep", 1.0)
    # 内容哈希必须是 sha1 前 12 位，跨进程可复现
    import hashlib

    expected = hashlib.sha1("你好|female_warm|1.00".encode("utf-8")).hexdigest()[:12]
    assert key == expected
