from _helpers import raises

from vision import ids


def test_make_page_id_pads_two_digits():
    assert ids.make_page_id("book01", 3) == "book01_p03"
    assert ids.make_page_id("book01", 12) == "book01_p12"


def test_book_id_rules():
    for invalid in ("boo", "Book01", "book_01", "b01", "book0123456789"):
        raises(ids.IdError, ids.validate_book_id, invalid)
    assert ids.validate_book_id("book01") == "book01"


def test_page_no_range():
    raises(ids.IdError, ids.make_page_id, "book01", 0)
    raises(ids.IdError, ids.make_page_id, "book01", 100)
    raises(ids.IdError, ids.make_page_id, "book01", True)


def test_parse_page_id_roundtrip():
    page_id = ids.make_page_id("book07", 23)
    assert ids.parse_page_id(page_id) == ("book07", 23)
    raises(ids.IdError, ids.parse_page_id, "book01-03")


def test_derived_ids():
    assert ids.block_id("book01_p03", 1) == "book01_p03_t01"
    assert ids.object_id("book01_p03", 12) == "book01_p03_o12"
    raises(ids.IdError, ids.block_id, "book01_p03", 100)
