"""点读评测：用**独立真值轮廓**采样点击，算「触控万物识别」的准确率。

真值来自 `samples/books_demo/*/pXX.gt.json`（由绘图代码生成，与 VLM/索引无关），
所以这个数不是自己评自己。

    python eval/tap_eval.py --gt-dir samples/books_demo --index-dir data/index --out eval

指标：
- 检出率：真值物体里有几个被索引收录
- Top-1 准确率：点击落在物体上时，返回的 label 是否正确
- 背景误触率：点在空白处却被判成某个物体
- 延迟：hit_test 的 P50 / P95
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision import index as index_mod  # noqa: E402
from vision.mask import point_in_polygon  # noqa: E402

# 模型常用别名 → 评测口径
ALIASES = {
    "小兔子": "兔子",
    "白兔": "兔子",
    "兔": "兔子",
    "大树": "树",
    "树木": "树",
    "日头": "太阳",
    "阳光": "太阳",
    "白云": "云",
    "云朵": "云",
    "小房子": "房子",
    "小屋": "房子",
    "小花": "花",
    "花朵": "花",
}


def norm_label(label: str) -> str:
    text = (label or "").strip()
    return ALIASES.get(text, text)


def match_label(label: str, vocabulary: set[str]) -> str:
    """把模型叫法对齐到真值词表：先查别名，再去掉"小/大/老"前缀。"""
    text = norm_label(label)
    if text in vocabulary:
        return text
    for prefix in ("小", "大", "老"):
        if text.startswith(prefix) and text[1:] in vocabulary:
            return text[1:]
    return text


def polygon_bbox(polygon: list[list[int]]) -> tuple[int, int, int, int]:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def sample_inside(
    polygon: list[list[int]], count: int, rng: random.Random, margin: int = 4
) -> list[tuple[int, int]]:
    """在轮廓内均匀撒点（拒绝采样）。margin 让点离边缘远一点，避免歧义。"""
    x1, y1, x2, y2 = polygon_bbox(polygon)
    points: list[tuple[int, int]] = []
    attempts = 0
    while len(points) < count and attempts < count * 200:
        attempts += 1
        x = rng.randint(x1, x2)
        y = rng.randint(y1, y2)
        if not point_in_polygon(x, y, polygon):
            continue
        if margin and _dist_to_polygon(x, y, polygon) < margin:
            continue
        points.append((x, y))
    return points


def _dist_to_polygon(x: float, y: float, polygon: list[list[int]]) -> float:
    best = float("inf")
    n = len(polygon)
    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        best = min(best, _dist_to_segment(x, y, ax, ay, bx, by))
    return best


def _dist_to_segment(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def sample_background(
    width: int, height: int, polygons: list[list[list[int]]],
    count: int, rng: random.Random, clearance: float = 24.0,
) -> list[tuple[int, int]]:
    """空白处撒点：不在任何物体轮廓内，且离轮廓至少 clearance 像素。"""
    points: list[tuple[int, int]] = []
    attempts = 0
    while len(points) < count and attempts < count * 400:
        attempts += 1
        x, y = rng.randint(0, width - 1), rng.randint(0, height - 1)
        if any(point_in_polygon(x, y, poly) for poly in polygons):
            continue
        if any(_dist_to_polygon(x, y, poly) < clearance for poly in polygons):
            continue
        points.append((x, y))
    return points


@dataclass
class TapRecord:
    page_id: str
    gt_label: str
    pred_label: str | None
    how: str
    x: int
    y: int
    latency_ms: float
    gt_detected: bool = True  # 该真值物体是否被索引收录


@dataclass
class PageOutcome:
    page_id: str
    gt_objects: int
    detected: int
    missing: list[str] = field(default_factory=list)


def evaluate_page(
    page_id: str,
    gt_objects: list[dict],
    page_index,
    rng: random.Random,
    per_object: int,
    background: int,
) -> tuple[list[TapRecord], TapRecord | None, PageOutcome]:
    gt_labels = {norm_label(o["label"]) for o in gt_objects}
    by_label = {match_label(o.label, gt_labels): o for o in page_index.objects}
    detected = [o for o in gt_objects if norm_label(o["label"]) in by_label]
    outcome = PageOutcome(
        page_id=page_id,
        gt_objects=len(gt_objects),
        detected=len(detected),
        missing=[o["label"] for o in gt_objects if norm_label(o["label"]) not in by_label],
    )

    records: list[TapRecord] = []
    for gt in gt_objects:
        label = norm_label(gt["label"])
        is_detected = label in by_label
        for x, y in sample_inside(gt["polygon"], per_object, rng):
            started = time.perf_counter()
            obj, how = index_mod.hit_test(page_index, x, y)
            latency = (time.perf_counter() - started) * 1000
            records.append(
                TapRecord(
                    page_id=page_id,
                    gt_label=label,
                    pred_label=match_label(obj.label, gt_labels) if obj else None,
                    how=how,
                    x=x,
                    y=y,
                    latency_ms=latency,
                    gt_detected=is_detected,
                )
            )

    polygons = [o["polygon"] for o in gt_objects]
    background_record = None
    if background:
        bg_hits = []
        for x, y in sample_background(
            page_index.image_width, page_index.image_height, polygons, background, rng
        ):
            started = time.perf_counter()
            obj, how = index_mod.hit_test(page_index, x, y)
            latency = (time.perf_counter() - started) * 1000
            bg_hits.append(
                TapRecord(
                    page_id=page_id,
                    gt_label="__background__",
                    pred_label=obj.label if obj else None,
                    how=how,
                    x=x,
                    y=y,
                    latency_ms=latency,
                )
            )
        # 汇总成一条占位记录，明细在 results.json
        background_record = bg_hits[0] if bg_hits else None
        records.extend(bg_hits)
    return records, background_record, outcome


def summarize(records: list[TapRecord], outcomes: list[PageOutcome]) -> dict:
    positives = [r for r in records if r.gt_label != "__background__"]
    negatives = [r for r in records if r.gt_label == "__background__"]

    correct = sum(1 for r in positives if r.pred_label == r.gt_label)
    wrong = sum(1 for r in positives if r.pred_label and r.pred_label != r.gt_label)
    missed = sum(1 for r in positives if r.pred_label is None)
    false_hits = sum(1 for r in negatives if r.pred_label is not None)

    latencies = sorted(r.latency_ms for r in records) or [0.0]

    detected_samples = [r for r in positives if r.gt_detected]
    detected_correct = sum(1 for r in detected_samples if r.pred_label == r.gt_label)

    confusion: dict[str, dict[str, int]] = {}
    for r in positives:
        key = r.gt_label
        pred = r.pred_label or "(未命中)"
        confusion.setdefault(key, {})
        confusion[key][pred] = confusion[key].get(pred, 0) + 1

    per_label: dict[str, dict[str, int]] = {}
    for r in positives:
        row = per_label.setdefault(r.gt_label, {"n": 0, "correct": 0, "wrong": 0, "miss": 0})
        row["n"] += 1
        if r.pred_label == r.gt_label:
            row["correct"] += 1
        elif r.pred_label is None:
            row["miss"] += 1
        else:
            row["wrong"] += 1

    return {
        "pages": len(outcomes),
        "gt_objects": sum(o.gt_objects for o in outcomes),
        "detected_objects": sum(o.detected for o in outcomes),
        "positive_samples": len(positives),
        "background_samples": len(negatives),
        "top1_accuracy": correct / len(positives) if positives else 0.0,
        "top1_accuracy_detected": (
            detected_correct / len(detected_samples) if detected_samples else 0.0
        ),
        "detected_samples": len(detected_samples),
        "wrong_object_rate": wrong / len(positives) if positives else 0.0,
        "miss_rate": missed / len(positives) if positives else 0.0,
        "background_false_hit_rate": false_hits / len(negatives) if negatives else 0.0,
        "latency_p50_ms": statistics.median(latencies),
        "latency_p95_ms": latencies[int(0.95 * (len(latencies) - 1))],
        "per_label": per_label,
        "confusion": confusion,
        "missing": {o.page_id: o.missing for o in outcomes if o.missing},
    }


def write_report(summary: dict, out_dir: Path, gt_label: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "tap_report.md"
    lines = [
        "# 点读评测报告（触控万物识别）",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 真值目录：`{gt_label}`（真值来自绘图代码，与 VLM/索引无关）",
        f"- 页数：{summary['pages']}",
        "",
        "## 一、总览",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 真值物体数 | {summary['gt_objects']} |",
        f"| 被索引检出 | {summary['detected_objects']} "
        f"（{summary['detected_objects'] / max(1, summary['gt_objects']):.0%}） |",
        f"| 正样本（点在物体上） | {summary['positive_samples']} |",
        f"| **Top-1 准确率**（含漏检） | **{summary['top1_accuracy']:.1%}** |",
        f"| **Top-1 准确率**（仅已检出） | **{summary['top1_accuracy_detected']:.1%}** "
        f"（{summary['detected_samples']} 样本） |",
        f"| 错判成别的物体 | {summary['wrong_object_rate']:.1%} |",
        f"| 未命中 | {summary['miss_rate']:.1%} |",
        f"| 背景样本 | {summary['background_samples']} |",
        f"| **背景误触率** | **{summary['background_false_hit_rate']:.1%}** |",
        f"| 延迟 P50 / P95 | {summary['latency_p50_ms']:.3f} / "
        f"{summary['latency_p95_ms']:.3f} ms |",
        "",
        "## 二、分物体",
        "",
        "| 物体 | 样本 | 正确 | 错判 | 未命中 | 准确率 |",
        "|---|---|---|---|---|---|",
    ]
    for label, row in sorted(summary["per_label"].items()):
        acc = row["correct"] / row["n"] if row["n"] else 0.0
        lines.append(
            f"| {label} | {row['n']} | {row['correct']} | {row['wrong']} | "
            f"{row['miss']} | {acc:.1%} |"
        )

    lines += ["", "## 三、混淆情况", "", "| 真值 | 预测分布 |", "|---|---|"]
    for label, dist in sorted(summary["confusion"].items()):
        text = "、".join(f"{k}×{v}" for k, v in sorted(dist.items(), key=lambda kv: -kv[1]))
        lines.append(f"| {label} | {text} |")

    if summary["missing"]:
        lines += ["", "## 四、未被检出的物体", "", "| 页面 | 缺失 |", "|---|---|"]
        for page, labels in summary["missing"].items():
            lines.append(f"| {page} | {'、'.join(labels)} |")
    else:
        lines += ["", "## 四、未被检出的物体", "", "无，真值物体全部被索引收录。"]

    lines += [
        "",
        "## 五、结论",
        "",
        f"- 检出率 {summary['detected_objects']}/{summary['gt_objects']}："
        "没检出的物体，点击一定落空，所以先补召回。",
        f"- 已检出物体的 Top-1 准确率 {summary['top1_accuracy_detected']:.1%}，"
        "反映的是**定位精度**（轮廓是否贴合）。",
        f"- 背景误触率 {summary['background_false_hit_rate']:.1%}，"
        + ("空白处基本不误判。" if summary["background_false_hit_rate"] <= 0.05 else "空白处误判偏多。"),
        f"- 单次命中 {summary['latency_p50_ms']:.3f} ms，可忽略不计。",
        "",
        "> 注：本报告用的是合成绘本 + 绘图代码真值，用于验证评测方法与链路；",
        "> 正式提交前需换成组委会授权绘本 + 人工标注真值。",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "tap_results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="点读准确率评测")
    parser.add_argument(
        "--gt-dir", nargs="+",
        default=[str(ROOT / "samples" / "books_demo")],
        help="可传多个目录，合并评测",
    )
    parser.add_argument("--index-dir", default=str(ROOT / "data" / "index"))
    parser.add_argument("--out", default=str(ROOT / "eval"))
    parser.add_argument("--per-object", type=int, default=40)
    parser.add_argument("--background", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    gt_dirs = [Path(d) for d in args.gt_dir]
    index_dir = Path(args.index_dir)
    out_dir = Path(args.out)
    rng = random.Random(args.seed)

    gt_files: list[Path] = []
    for directory in gt_dirs:
        gt_files.extend(sorted(directory.rglob("*.gt.json")))
    if not gt_files:
        print(f"{', '.join(str(d) for d in gt_dirs)} 下没有 *.gt.json")
        return 1

    records: list[TapRecord] = []
    outcomes: list[PageOutcome] = []
    for gt_file in gt_files:
        gt = json.loads(gt_file.read_text(encoding="utf-8"))
        page_id = gt["page_id"]
        index_file = index_dir / f"{page_id}.json"
        if not index_file.is_file():
            print(f"  跳过 {page_id}：没有索引（先跑 run.py + build_index）")
            continue
        # 直接读文件，避免 index.load 再拼一层 "index/" 目录
        page_index = index_mod.PageIndex.from_dict(
            json.loads(index_file.read_text(encoding="utf-8"))
        )
        page_records, _, outcome = evaluate_page(
            page_id, gt["objects"], page_index, rng, args.per_object, args.background
        )
        records.extend(page_records)
        outcomes.append(outcome)
        print(f"  {page_id}: gt={outcome.gt_objects} 检出={outcome.detected} "
              f"样本={len(page_records)}")

    if not records:
        print("没有可评测的页面：索引缺失，或真值里没有物体")
        return 1

    summary = summarize(records, outcomes)
    report = write_report(summary, out_dir, "/".join(d.name for d in gt_dirs))
    print(f"\nTop-1 {summary['top1_accuracy']:.1%}　"
          f"背景误触 {summary['background_false_hit_rate']:.1%}　"
          f"P50 {summary['latency_p50_ms']:.3f}ms")
    print(f"报告：{report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
