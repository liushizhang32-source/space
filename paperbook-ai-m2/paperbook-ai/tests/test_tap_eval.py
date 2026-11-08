import random

from eval import tap_eval
from vision.mask import point_in_polygon


def test_norm_label_aliases():
    assert tap_eval.norm_label("小兔子") == "兔子"
    assert tap_eval.norm_label(" 大树 ") == "树"
    assert tap_eval.norm_label("太阳") == "太阳"
    assert tap_eval.norm_label("") == ""


def test_sample_inside_all_points_inside():
    square = [[0, 0], [200, 0], [200, 200], [0, 200]]
    rng = random.Random(7)
    points = tap_eval.sample_inside(square, 30, rng)
    assert len(points) == 30
    assert all(point_in_polygon(x, y, square) for x, y in points)
    # margin 生效：点离边缘至少 4px
    assert all(4 <= x <= 196 and 4 <= y <= 196 for x, y in points)


def test_sample_background_avoids_objects():
    small = [[10, 10], [30, 10], [30, 30], [10, 30]]
    rng = random.Random(3)
    points = tap_eval.sample_background(100, 100, [small], 20, rng)
    assert len(points) == 20
    assert all(not point_in_polygon(x, y, small) for x, y in points)


def test_summarize_metrics():
    def rec(gt, pred):
        return tap_eval.TapRecord(
            page_id="p1", gt_label=gt, pred_label=pred, how="inside",
            x=0, y=0, latency_ms=0.01,
        )

    records = [
        rec("兔子", "兔子"),
        rec("兔子", "兔子"),
        rec("兔子", "树"),        # 错判
        rec("树", None),          # 未命中
        rec("__background__", None),
        rec("__background__", "树"),  # 背景误触
    ]
    outcomes = [tap_eval.PageOutcome(page_id="p1", gt_objects=2, detected=2, missing=[])]
    summary = tap_eval.summarize(records, outcomes)

    assert summary["positive_samples"] == 4
    assert summary["top1_accuracy"] == 0.5
    assert summary["top1_accuracy_detected"] == 0.5
    assert summary["wrong_object_rate"] == 0.25
    assert summary["miss_rate"] == 0.25
    assert summary["background_false_hit_rate"] == 0.5
    assert summary["per_label"]["兔子"]["correct"] == 2
