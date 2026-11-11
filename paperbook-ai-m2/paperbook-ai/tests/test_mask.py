import numpy as np

from vision import index as index_mod
from vision import mask as mask_mod


def test_polygon_area_square_and_triangle():
    assert mask_mod.polygon_area([(0, 0), (10, 0), (10, 10), (0, 10)]) == 100
    assert mask_mod.polygon_area([(0, 0), (10, 0), (0, 10)]) == 50
    assert mask_mod.polygon_area([(0, 0), (1, 1)]) == 0  # 少于 3 点


def test_point_in_polygon():
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert mask_mod.point_in_polygon(5, 5, square) is True
    assert mask_mod.point_in_polygon(-1, 5, square) is False
    assert mask_mod.point_in_polygon(11, 5, square) is False
    triangle = [(0, 0), (10, 0), (5, 10)]
    assert mask_mod.point_in_polygon(5, 5, triangle) is True
    assert mask_mod.point_in_polygon(1, 9, triangle) is False


def test_null_segmenter_returns_bbox_polygon():
    seg = mask_mod.NullSegmenter()
    assert seg.available()[0]
    results = seg.segment(np.zeros((100, 100, 3), np.uint8), [(10, 20, 60, 80)])
    assert len(results) == 1
    assert results[0].method == "none"
    assert results[0].polygon == [(10, 20), (60, 20), (60, 80), (10, 80)]
    assert results[0].area == 50 * 60


def test_grabcut_segmenter_contract():
    image = np.full((120, 120, 3), 240, np.uint8)
    image[30:90, 30:90] = (40, 40, 200)  # 一个方块
    seg = mask_mod.GrabCutSegmenter()
    assert seg.available()[0]
    results = seg.segment(image, [(28, 28, 92, 92)])
    assert len(results) == 1
    assert len(results[0].polygon) >= 3
    assert results[0].method in ("grabcut", "grabcut-fallback")


def test_build_segmenter_auto_and_unknown():
    assert mask_mod.build_segmenter("none").name == "none"
    assert mask_mod.build_segmenter("grabcut").name == "grabcut"
    try:
        mask_mod.build_segmenter("magic")
    except ValueError:
        return
    raise AssertionError("未知后端应报错")


def test_with_masks_merges_polygons():
    from vision import contracts
    from vision.backends.base import VlmObject

    doc = contracts.build_vlm_document(
        book_id="book01", page_id="book01_p01", page_no=1,
        image_width=100, image_height=100, description="x",
        objects=[VlmObject("兔子", [10, 10, 60, 60], 0.9)],
        safety_pass=True,
        elapsed_ms=1, backend="test",
    )
    page = index_mod.build_from_vlm(doc)
    results = mask_mod.NullSegmenter().segment(np.zeros((100, 100, 3), np.uint8), [(10, 10, 60, 60)])
    updated = index_mod.with_masks(page, results)
    assert updated.objects[0].mask_method == "none"
    assert len(updated.objects[0].polygon) == 4


def test_hit_uses_polygon_not_bbox():
    from vision import contracts
    from vision.backends.base import VlmObject

    doc = contracts.build_vlm_document(
        book_id="book01", page_id="book01_p01", page_no=1,
        image_width=100, image_height=100, description="x",
        objects=[VlmObject("三角", [0, 0, 100, 100], 0.9)],
        safety_pass=True,
        elapsed_ms=1, backend="test",
    )
    page = index_mod.build_from_vlm(doc)
    triangle = [(0, 0), (100, 0), (50, 100)]
    from dataclasses import replace

    page = replace(page, objects=[replace(page.objects[0], polygon=tuple(triangle))])

    obj, how = index_mod.hit_test(page, 50, 10)  # 三角形内
    assert how == "inside" and obj is not None

    obj, how = index_mod.hit_test(page, 5, 95)  # bbox 内、三角形外
    assert how == "miss" and obj is None
