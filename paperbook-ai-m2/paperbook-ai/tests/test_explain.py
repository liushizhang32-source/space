from vision import contracts, explain, index
from vision.backends.base import VlmObject


class FakeBackend:
    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    def available(self):
        return True, ""

    def chat_raw(self, image, prompt, max_tokens=None):
        self.calls += 1
        assert "兔子" in prompt  # 物体列表要进 prompt
        return self.reply


class NoChatBackend:
    name = "stub"

    def available(self):
        return True, ""


def _page():
    doc = contracts.build_vlm_document(
        book_id="book01",
        page_id="book01_p01",
        page_no=1,
        image_width=1000,
        image_height=1000,
        description="小兔子在森林里",
        objects=[
            VlmObject("兔子", [300, 400, 500, 700], 0.9),
            VlmObject("胡萝卜", [600, 500, 680, 620], 0.9),
        ],
        safety_pass=True,
        elapsed_ms=1,
        backend="test",
    )
    return index.build_from_vlm(doc)


def test_explain_objects_parses_mapping():
    backend = FakeBackend('{"兔子": "它正要去拔胡萝卜", "胡萝卜": "橙色的，藏在草丛里"}')
    mapping = explain.explain_objects(backend, None, ["兔子", "胡萝卜"])
    assert mapping["兔子"] == "它正要去拔胡萝卜"
    assert backend.calls == 1  # 一页只调一次


def test_explain_objects_ignores_blank_and_extra_keys():
    backend = FakeBackend('{"兔子": "  ", "胡萝卜": "橙色", "太阳": "暖洋洋"}')
    mapping = explain.explain_objects(backend, None, ["兔子", "胡萝卜"])
    assert mapping == {"胡萝卜": "橙色"}


def test_explain_objects_empty_labels_skips_call():
    backend = FakeBackend("{}")
    assert explain.explain_objects(backend, None, []) == {}
    assert backend.calls == 0


def test_backend_without_chat_raw_raises():
    try:
        explain.explain_objects(NoChatBackend(), None, ["兔子"])
    except RuntimeError as exc:
        assert "chat_raw" in str(exc)
        return
    raise AssertionError("应抛出 RuntimeError")


def test_with_explanations_merges_and_explain_prefers_cached():
    page = _page()
    updated, hit = index.with_explanations(page, {"兔子": "它正要去拔胡萝卜"})
    assert hit == 1
    rabbit = updated.objects[0]
    assert rabbit.explanation == "它正要去拔胡萝卜"
    assert index.explain(updated, rabbit) == "它正要去拔胡萝卜"

    # 没命中的物体仍走模板
    carrot = updated.objects[1]
    assert carrot.explanation == ""
    assert "这是胡萝卜" in index.explain(updated, carrot)


def test_explanations_survive_save_load():
    from _helpers import temp_dir

    with temp_dir() as tmp:
        page = _page()
        updated, _ = index.with_explanations(page, {"兔子": "它正要去拔胡萝卜"})
        index.save(updated, tmp)
        loaded = index.load(tmp, "book01_p01")
        assert loaded.objects[0].explanation == "它正要去拔胡萝卜"
