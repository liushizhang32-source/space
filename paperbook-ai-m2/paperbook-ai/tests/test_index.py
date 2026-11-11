from vision import contracts, index
from vision.backends.base import VlmObject


def _doc():
    return contracts.build_vlm_document(
        book_id="book01",
        page_id="book01_p01",
        page_no=1,
        image_width=1000,
        image_height=1000,
        description="小兔子在森林里",
        objects=[
            VlmObject("树", [100, 100, 400, 700], 0.9),
            VlmObject("兔子", [300, 400, 500, 700], 0.9),
            VlmObject("胡萝卜", [600, 500, 680, 620], 0.9),
        ],
        scene_tags=["森林"],
        safety_pass=True,
        elapsed_ms=1,
        backend="test",
    )


def test_build_from_vlm():
    page = index.build_from_vlm(_doc())
    assert page.page_id == "book01_p01"
    assert [o.label for o in page.objects] == ["树", "兔子", "胡萝卜"]
    assert page.objects[1].bbox == (300, 400, 500, 700)
    assert page.objects[1].area == 200 * 300
    # 公共 Schema 默认不带 producer，索引记 unknown 即可
    assert page.vlm_backend == "unknown"


def test_hit_inside_picks_smallest_area():
    page = index.build_from_vlm(_doc())
    # (350,450) 同时落在"树"和"兔子"里，应命中更具体的"兔子"
    obj, how = index.hit_test(page, 350, 450)
    assert how == "inside"
    assert obj.label == "兔子"


def test_hit_with_tolerance_near_edge():
    page = index.build_from_vlm(_doc())
    # 兔子右边界是 500，点在 508（容差 12 内）
    obj, how = index.hit_test(page, 508, 500)
    assert how == "inside"
    assert obj.label == "兔子"


def test_nearest_fallback_for_small_object():
    page = index.build_from_vlm(_doc())
    # 点在胡萝卜下边界外 20px（超出 12px 容差），但在最近物体阈值内
    obj, how = index.hit_test(page, 640, 640)
    assert how == "nearest"
    assert obj.label == "胡萝卜"


def test_miss_far_away():
    page = index.build_from_vlm(_doc())
    obj, how = index.hit_test(page, 10, 990)
    assert how == "miss"
    assert obj is None


def test_save_and_load_roundtrip():
    from _helpers import temp_dir

    with temp_dir() as tmp:
        page = index.build_from_vlm(_doc())
        path = index.save(page, tmp)
        assert path.is_file()
        loaded = index.load(tmp, "book01_p01")
        assert loaded.page_id == page.page_id
        assert [o.label for o in loaded.objects] == [o.label for o in page.objects]
        assert loaded.objects[0].bbox == page.objects[0].bbox


def test_empty_objects_page():
    doc = contracts.build_vlm_document(
        book_id="book01", page_id="book01_p02", page_no=2,
        image_width=100, image_height=100, description="无物体",
        objects=[], elapsed_ms=1, backend="test", safety_pass=True,
    )
    page = index.build_from_vlm(doc)
    assert page.objects == []
    obj, how = index.hit_test(page, 50, 50)
    assert obj is None and how == "miss"


def test_explain_contains_label():
    page = index.build_from_vlm(_doc())
    text = index.explain(page, page.objects[0])
    assert "树" in text
    assert "小兔子在森林里" in text


def test_merge_annotations_keeps_explanation_and_polygon():
    import numpy as np

    from vision import mask as mask_mod

    page = index.build_from_vlm(_doc())
    enriched, _ = index.with_explanations(page, {"兔子": "在啃胡萝卜"})
    enriched = index.with_masks(
        enriched,
        mask_mod.NullSegmenter().segment(np.zeros((1000, 1000, 3), np.uint8),
                                         [o.bbox for o in enriched.objects]),
    )

    rebuilt = index.build_from_vlm(_doc())  # 模拟重建：讲解/轮廓全丢
    merged = index.merge_annotations(rebuilt, enriched)

    rabbit = next(o for o in merged.objects if o.label == "兔子")
    assert rabbit.explanation == "在啃胡萝卜"
    assert len(rabbit.polygon) == 4
    assert rabbit.mask_method == "none"


def test_failed_document_rejected():
    doc = {"page_id": "book01_p03", "status": "failed"}
    try:
        index.build_from_vlm(doc)
    except ValueError:
        return
    raise AssertionError("failed 文档应拒绝建库")
