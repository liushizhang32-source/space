"""互动阶段：帧识别、触控命中与帧↔页面关联的回归测试。"""

from PIL import Image

from vision.backends.base import VlmObject, VlmResult
from vision.frame import hit_test, link_frame_to_page, recognize_frame
from vision.safety import SafetyBlocked


class _Vlm:
    def __init__(self, objects, *, flags=None, raw=None, pass_value=True):
        self._objects = objects
        # VlmResult.safety_flags 必须与原始 safety 里的 flags 一致；None 视为“模型没给”会被判缺失
        self._flags = [] if flags is None else flags
        self._raw = raw
        self._pass = pass_value

    def understand(self, image, ocr_text):
        return VlmResult(
            description="画面",
            safety_pass=self._pass,
            objects=list(self._objects),
            safety_flags=self._flags,
            safety_raw=self._raw if self._raw is not None else {"pass": self._pass, "flags": list(self._flags)},
            safety_source="model",
            confidence_missing=0,
        )


def _image(width=200, height=100):
    return Image.new("RGB", (width, height), "white")


def test_recognize_frame_assigns_ids_and_categories():
    vlm = _Vlm([VlmObject("男孩", (10, 10, 60, 90), 0.9), VlmObject("狗", (100, 40, 150, 90), 0.8)])
    doc = recognize_frame(_image(), vlm, frame_id="f001", page_id="book01_p01")
    assert [o["object_id"] for o in doc["objects"]] == ["f001_o01", "f001_o02"]
    assert [o["category"] for o in doc["objects"]] == ["person", "animal"]
    assert doc["safety"]["pass"] is True


def test_recognize_frame_blocks_on_nonempty_flags():
    vlm = _Vlm([VlmObject("刀", (10, 10, 60, 60), 0.9)], flags=["violence"], pass_value=False)
    try:
        recognize_frame(_image(), vlm, frame_id="f001")
    except SafetyBlocked as exc:
        assert "violence" in str(exc)
    else:
        raise AssertionError("非空 flags 必须 fail-closed")


def test_recognize_frame_requires_raw_safety():
    vlm = _Vlm([VlmObject("男孩", (0, 0, 10, 10), 0.9)], raw={})
    try:
        recognize_frame(_image(), vlm, frame_id="f001")
    except SafetyBlocked:
        pass
    else:
        raise AssertionError("缺少 safety 原始对象必须阻断")


def test_hit_test_returns_smallest_containing_object():
    doc = {
        "objects": [
            {"object_id": "f_o01", "label": "房间", "category": "scene", "bbox": [0, 0, 200, 100], "confidence": 0.9},
            {"object_id": "f_o02", "label": "狗", "category": "animal", "bbox": [100, 40, 150, 90], "confidence": 0.8},
        ]
    }
    hit = hit_test(doc, 120, 60)
    assert hit is not None and hit["object_id"] == "f_o02"
    assert hit_test(doc, 190, 10)["object_id"] == "f_o01"
    assert hit_test(doc, 250, 10) is None


def test_link_frame_to_page_matches_same_category_and_label():
    frame_doc = {
        "frame_id": "f001",
        "page_id": "book01_p01",
        "image_width": 200,
        "image_height": 100,
        "objects": [
            {"object_id": "f001_o01", "label": "狗", "category": "animal", "bbox": [100, 40, 150, 90], "confidence": 0.8}
        ],
    }
    page_doc = {
        "page_id": "book01_p01",
        "image_width": 200,
        "image_height": 100,
        "objects": [
            {"object_id": "book01_p01_o01", "label": "狗", "bbox": [100, 40, 150, 90], "confidence": 0.8}
        ],
    }
    links = link_frame_to_page(frame_doc, page_doc)
    assert len(links) == 1
    assert links[0]["page_object_id"] == "book01_p01_o01"
    assert links[0]["identity_status"] == "unknown"
    assert links[0]["score"] >= 0.5


def test_link_skips_when_no_page_objects():
    frame_doc = {"frame_id": "f001", "image_width": 10, "image_height": 10, "objects": []}
    assert link_frame_to_page(frame_doc, {"page_id": "p", "objects": []}) == []
