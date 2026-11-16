"""跨页对象目录与候选关联的回归测试。"""

from vision.characters import (
    MAX_CLUSTERS,
    build_object_catalog,
    category_of,
    cluster_objects,
)


def _c2(page_id, objects):
    return {
        "schema_version": "1.0",
        "book_id": page_id.split("_")[0],
        "page_id": page_id,
        "page_no": 1,
        "status": "ok" if objects else "empty",
        "image_width": 100,
        "image_height": 100,
        "description": "",
        "objects": objects,
        "scene_tags": [],
        "safety": {"pass": True, "flags": []},
        "elapsed_ms": 10,
    }


def _obj(page_id, index, label, bbox=(10, 10, 30, 30)):
    return {
        "object_id": f"{page_id}_o{index:02d}",
        "label": label,
        "bbox": list(bbox),
        "confidence": 0.8,
    }


def test_category_of_maps_common_labels():
    assert category_of("男孩") == "person"
    assert category_of("狗") == "animal"
    assert category_of("星星") == "scene"
    assert category_of("袋子") == "object"
    assert category_of("外星飞船") == "other"


def test_catalog_keeps_page_and_category():
    pages = {
        "book01_p01": _c2("book01_p01", [_obj("book01_p01", 1, "男孩")]),
        "book01_p02": _c2("book01_p02", [_obj("book01_p02", 1, "狗")]),
    }
    catalog = build_object_catalog(pages)
    assert [o["category"] for o in catalog["objects"]] == ["person", "animal"]
    assert catalog["objects"][0]["object_id"] == "book01_p01_o01"


def test_cross_page_same_label_is_one_cluster():
    pages = {
        "book01_p01": _c2("book01_p01", [_obj("book01_p01", 1, "人物")]),
        "book01_p02": _c2("book01_p02", [_obj("book01_p02", 1, "人物")]),
    }
    result = cluster_objects(pages)
    assert len(result["clusters"]) == 1
    cluster = result["clusters"][0]
    assert cluster["page_ids"] == ["book01_p01", "book01_p02"]
    assert cluster["identity_status"] == "unknown"
    assert len(result["links"]) == 1


def test_different_labels_are_separate_clusters():
    pages = {
        "book01_p01": _c2(
            "book01_p01", [_obj("book01_p01", 1, "男孩"), _obj("book01_p01", 2, "狗")]
        )
    }
    result = cluster_objects(pages)
    assert len(result["clusters"]) == 2


def test_cluster_count_is_capped():
    objects = [_obj("book01_p01", i + 1, f"物品{i}") for i in range(MAX_CLUSTERS + 5)]
    result = cluster_objects({"book01_p01": _c2("book01_p01", objects)})
    assert len(result["clusters"]) == MAX_CLUSTERS
    assert result["truncated"] is True


def test_object_id_must_match_page():
    pages = {"book01_p01": _c2("book01_p01", [_obj("book01_p02", 1, "人物")])}
    try:
        build_object_catalog(pages)
    except ValueError:
        pass
    else:
        raise AssertionError("跨页 object_id 必须拒绝")
