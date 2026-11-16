"""PaddleOCR 适配层测试：用假引擎覆盖 2.x / 3.x 两种返回结构。

这样即使机器上没装 paddle，也能验证"解析代码对不对"——
真正接模型前，最可能出错的就是这段结构归一化。
"""

from vision.backends.paddle_ocr import PaddleOcrBackend, _poly_to_bbox


def test_poly_to_bbox():
    assert _poly_to_bbox([[10, 20], [50, 20], [50, 60], [10, 60]]) == [10, 20, 50, 60]
    assert _poly_to_bbox([[50, 60], [10, 20], [50, 20], [10, 60]]) == [10, 20, 50, 60]


def test_normalize_v2_single_page():
    raw = [
        [
            [[[10, 20], [200, 20], [200, 60], [10, 60]], ("小兔子", 0.98)],
            [[[10, 80], [300, 80], [300, 120], [10, 120]], ("胡萝卜", 0.91)],
        ]
    ]
    lines = PaddleOcrBackend._normalize_v2(raw)
    assert [line.text for line in lines] == ["小兔子", "胡萝卜"]
    assert lines[0].bbox == [10, 20, 200, 60]
    assert abs(lines[1].confidence - 0.91) < 1e-6


def test_normalize_v2_empty_and_malformed():
    assert PaddleOcrBackend._normalize_v2([]) == []
    assert PaddleOcrBackend._normalize_v2(None) == []
    raw = [[[None, ("", 0.0)], [[[0, 0], [1, 1], [1, 2], [0, 2]], ("ok", 0.5)]]]
    lines = PaddleOcrBackend._normalize_v2(raw)
    assert [line.text for line in lines] == ["ok"]


def test_normalize_v3_dict():
    raw = [
        {
            "rec_texts": ["小兔子", "森林"],
            "rec_scores": [0.97, 0.88],
            "rec_polys": [
                [[10, 20], [200, 20], [200, 60], [10, 60]],
                [[10, 80], [300, 80], [300, 120], [10, 120]],
            ],
        }
    ]
    lines = PaddleOcrBackend._normalize_v3(raw)
    assert [line.text for line in lines] == ["小兔子", "森林"]
    assert lines[1].bbox == [10, 80, 300, 120]


def test_normalize_v3_wrapped_in_res():
    raw = [{"res": {"rec_texts": ["嗨"], "rec_scores": [0.9],
                    "rec_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]]}}]
    lines = PaddleOcrBackend._normalize_v3(raw)
    assert [line.text for line in lines] == ["嗨"]


def test_normalize_v3_object_with_json_attr():
    class Page:
        json = {"rec_texts": ["树"], "rec_scores": [0.8],
                "rec_polys": [[[5, 5], [50, 5], [50, 55], [5, 55]]]}

    lines = PaddleOcrBackend._normalize_v3([Page()])
    assert [line.text for line in lines] == ["树"]
    assert lines[0].bbox == [5, 5, 50, 55]


def test_available_reports_missing_dependency_without_raising():
    backend = PaddleOcrBackend()
    ok, reason = backend.available()
    assert isinstance(ok, bool)
    if not ok:
        assert "paddleocr" in reason
