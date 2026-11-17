"""版面结构 sidecar 的回归测试。"""

from vision.layout import MAX_COLUMNS, build_layout

PAGE = "book01_p01"


def _c1(blocks):
    return {
        "schema_version": "1.0",
        "book_id": "book01",
        "page_id": PAGE,
        "page_no": 1,
        "status": "ok" if blocks else "empty",
        "image_width": 100,
        "image_height": 100,
        "text_blocks": blocks,
        "page_confidence": 0.9 if blocks else 0.0,
        "elapsed_ms": 10,
    }


def _block(bid, text, bbox):
    return {"block_id": bid, "order": 0, "text": text, "bbox": bbox, "confidence": 0.9}


def test_two_columns_are_read_left_column_first():
    blocks = [
        _block(f"{PAGE}_t01", "right-top", [60, 10, 100, 20]),
        _block(f"{PAGE}_t02", "left-top", [0, 10, 40, 20]),
        _block(f"{PAGE}_t03", "right-bottom", [60, 40, 100, 50]),
        _block(f"{PAGE}_t04", "left-bottom", [0, 40, 40, 50]),
    ]
    layout = build_layout(PAGE, _c1(blocks))
    assert layout["column_count"] == 2
    assert layout["reading_order"] == [
        f"{PAGE}_t02",
        f"{PAGE}_t04",
        f"{PAGE}_t01",
        f"{PAGE}_t03",
    ]


def test_single_column_reads_top_to_bottom():
    blocks = [
        _block(f"{PAGE}_t02", "b", [10, 50, 90, 60]),
        _block(f"{PAGE}_t01", "a", [10, 10, 90, 20]),
    ]
    layout = build_layout(PAGE, _c1(blocks))
    assert layout["column_count"] == 1
    assert layout["reading_order"] == [f"{PAGE}_t01", f"{PAGE}_t02"]


def test_empty_page_is_valid_layout():
    layout = build_layout(PAGE, _c1([]))
    assert layout["has_text"] is False
    assert layout["columns"] == []
    assert layout["reading_order"] == []


def test_page_mismatch_is_rejected():
    doc = _c1([])
    doc["page_id"] = "book01_p02"
    try:
        build_layout(PAGE, doc)
    except ValueError:
        pass
    else:
        raise AssertionError("page_id 不一致必须拒绝")


def test_too_many_columns_are_merged_and_flagged():
    blocks = []
    for i in range(MAX_COLUMNS + 2):
        x = i * 12
        blocks.append(_block(f"{PAGE}_t{i + 1:02d}", "x", [x, 10, x + 8, 20]))
    layout = build_layout(PAGE, _c1(blocks))
    assert layout["column_count"] == MAX_COLUMNS
    assert layout["truncated"] is True
    assert len(layout["reading_order"]) == len(blocks)
