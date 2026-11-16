"""批量跑视觉模块，产出 Markdown 评测报告 + JSON 明细。

用法：
    python eval/run_batch.py --input samples/books --out eval
    python eval/run_batch.py --input samples/books_demo --out eval

目录约定：
    {input}/{book_id}/p01.jpg      ← 图片（jpg/png/webp）
    {input}/{book_id}/p01.txt      ← 可选，真值文本；有它才算得出 CER

看什么：
    - 成功率（ok + empty 都算成功，empty 是无字页，契约上不是失败）
    - 每页耗时（含模型推理，不含首次加载）
    - 有真值的页：CER / 字准确率
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from eval.metrics import levenshtein, normalize  # noqa: E402
from vision import pipeline  # noqa: E402
from vision.backends import build_ocr_backend, build_vlm_backend  # noqa: E402
from vision.config import load_env  # noqa: E402
from vision.preprocess import load_page_image  # noqa: E402

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
PAGE_PATTERN = re.compile(r"p(\d{1,2})$", re.IGNORECASE)
BOOK_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]{3,11}$")


@dataclass
class PageResult:
    page_id: str
    book_id: str
    page_no: int
    image: str
    status: str
    blocks: int
    chars: int
    elapsed_ms: int
    has_gt: bool
    cer: float | None
    text: str
    gt_chars: int = 0
    edits: int = 0
    error: str | None = None


def _book_id_from_dir(name: str) -> str:
    """目录名 → 合法 book_id（契约要求 ^[a-z][a-z0-9]{3,11}$）。"""
    cleaned = re.sub(r"[^a-z0-9]", "", name.lower())
    if not cleaned or not cleaned[0].isalpha():
        cleaned = "book" + cleaned
    if len(cleaned) < 4:
        cleaned = (cleaned + "0000")[:4]
    return cleaned[:12]


def discover(input_dir: Path) -> list[tuple[str, int, Path, Path | None]]:
    """返回 [(book_id, page_no, image, gt_path|None)]，按书、按页排序。"""
    if not input_dir.is_dir():
        raise SystemExit(f"输入目录不存在：{input_dir}")

    book_dirs = sorted(p for p in input_dir.iterdir() if p.is_dir())
    loose = [p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    if loose:  # 直接给了一本书的目录
        book_dirs = [input_dir]

    pages: list[tuple[str, int, Path, Path | None]] = []
    for book_dir in book_dirs:
        book_id = _book_id_from_dir(book_dir.name)
        if not BOOK_ID_PATTERN.match(book_id):
            raise SystemExit(f"无法生成合法 book_id：{book_dir.name!r} → {book_id!r}")
        images = [p for p in book_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]

        def page_no_of(path: Path, index: int) -> int:
            match = PAGE_PATTERN.search(path.stem)
            return int(match.group(1)) if match else index

        ordered = sorted(images, key=lambda p: (page_no_of(p, 0), p.name))
        for index, image in enumerate(ordered, start=1):
            gt = image.with_suffix(".txt")
            pages.append((book_id, page_no_of(image, index), image, gt if gt.is_file() else None))
    if not pages:
        raise SystemExit(f"{input_dir} 下没有找到图片（jpg/png/webp）")
    return pages


def run_batch(pages, *, data_dir: Path, with_vlm: bool, ocr_backend, vlm_backend) -> list[PageResult]:
    results: list[PageResult] = []
    total = len(pages)
    for index, (book_id, page_no, image, gt_path) in enumerate(pages, start=1):
        started = time.perf_counter()
        try:
            result = pipeline.run_page(
                image_path=image,
                book_id=book_id,
                page_no=page_no,
                data_dir=data_dir,
                ocr_backend=ocr_backend,
                # 不启用 VLM 就**真的不跑**，不产出任何 vlm.json，
                # 避免占位文件被后续按路径误当真实结果（第四轮 N03）
                vlm_backend=vlm_backend if with_vlm else None,
                run_vlm=with_vlm,
            )
            if result.ocr is None:
                raise RuntimeError(
                    f"OCR 未产出：{result.ocr_error.message if result.ocr_error else '未知原因'}"
                )
            text = "\n".join(block["text"] for block in result.ocr["text_blocks"])
            truth = gt_path.read_text(encoding="utf-8") if gt_path else ""
            truth_norm = normalize(truth)
            pred_norm = normalize(text)
            edits = levenshtein(pred_norm, truth_norm) if truth_norm else 0
            error = result.ocr_error.message if result.ocr_error else None
            item = PageResult(
                page_id=result.page_id,
                book_id=book_id,
                page_no=page_no,
                image=str(image.relative_to(ROOT)),
                status=result.ocr["status"],
                blocks=len(result.ocr["text_blocks"]),
                chars=len(pred_norm),
                elapsed_ms=result.ocr["elapsed_ms"],
                has_gt=bool(gt_path),
                cer=(edits / len(truth_norm)) if truth_norm else None,
                text=text,
                gt_chars=len(truth_norm),
                edits=edits,
                error=str(error)[:200] if error else None,
            )
        except Exception as exc:  # noqa: BLE001 - 单页异常不中断整批
            item = PageResult(
                page_id=f"{book_id}_p{page_no:02d}",
                book_id=book_id,
                page_no=page_no,
                image=str(image.relative_to(ROOT)),
                status="failed",
                blocks=0,
                chars=0,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                has_gt=bool(gt_path),
                cer=None,
                text="",
                error=f"{type(exc).__name__}: {exc}"[:200],
            )
        results.append(item)
        acc = "" if item.cer is None else f" CER={item.cer:.3f}"
        print(f"[{index}/{total}] {item.page_id:<14} {item.status:<6} "
              f"{item.elapsed_ms:>6}ms blocks={item.blocks}{acc}")
    return results




def summarize(results: list[PageResult]) -> dict:
    total = len(results)
    ok = sum(1 for r in results if r.status == "ok")
    empty = sum(1 for r in results if r.status == "empty")
    failed = sum(1 for r in results if r.status == "failed")
    latencies = sorted(r.elapsed_ms for r in results)
    with_gt = [r for r in results if r.cer is not None]
    return {
        "total": total,
        "ok": ok,
        "empty": empty,
        "failed": failed,
        "success_rate": (ok + empty) / total if total else 0.0,
        "latency_mean_ms": int(statistics.fmean(latencies)) if latencies else 0,
        "latency_median_ms": int(statistics.median(latencies)) if latencies else 0,
        "latency_p95_ms": latencies[int(0.95 * (len(latencies) - 1))] if latencies else 0,
        "pages_with_gt": len(with_gt),
        "char_accuracy": _char_accuracy(with_gt),
        "cer_mean": statistics.fmean(r.cer for r in with_gt) if with_gt else None,
    }


def _char_accuracy(rows: list[PageResult]) -> float | None:
    """按字数加权：1 − Σ编辑数 / Σ真值字数（整体字准确率，不是逐页平均）。"""
    edits = sum(row.edits for row in rows if row.cer is not None)
    chars = sum(row.gt_chars for row in rows if row.cer is not None)
    if not chars:
        return None
    return max(0.0, 1.0 - edits / chars)


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def write_report(results, summary, out_dir: Path, *, input_dir: Path, backend: str, vlm: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "report.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# OCR 批量评测报告",
        "",
        f"- 生成时间：{now}",
        f"- 数据目录：`{_display_path(input_dir)}`",
        f"- OCR 后端：`{backend}`　VLM：`{vlm}`",
        f"- 页数：{summary['total']}",
        "- 耗时说明：已预热，单页耗时不含模型加载；服务化后模型常驻，在线延迟会更低。",
        "",
        "## 一、总览",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 总页数 | {summary['total']} |",
        f"| 识别成功（ok） | {summary['ok']} |",
        f"| 无字页（empty） | {summary['empty']} |",
        f"| 失败（failed） | {summary['failed']} |",
        f"| **成功率**（ok+empty） | **{summary['success_rate']:.1%}** |",
        f"| 耗时 均值 / 中位 / P95 | {summary['latency_mean_ms']} / "
        f"{summary['latency_median_ms']} / {summary['latency_p95_ms']} ms |",
        f"| 有真值页数 | {summary['pages_with_gt']} |",
    ]
    if summary["char_accuracy"] is not None:
        lines.append(f"| **字准确率（1-CER）** | **{summary['char_accuracy']:.2%}** |")
        lines.append(f"| CER 均值 | {summary['cer_mean']:.3f} |")
    lines += ["", "## 二、按书统计", "", "| 书 | 页数 | ok | empty | failed | 平均耗时 | 字准确率 |", "|---|---|---|---|---|---|---|"]

    books = sorted({r.book_id for r in results})
    for book in books:
        rows = [r for r in results if r.book_id == book]
        acc = _char_accuracy([r for r in rows if r.cer is not None])
        mean_ms = int(statistics.fmean([r.elapsed_ms for r in rows]))
        lines.append(
            f"| {book} | {len(rows)} | {sum(r.status == 'ok' for r in rows)} | "
            f"{sum(r.status == 'empty' for r in rows)} | {sum(r.status == 'failed' for r in rows)} | "
            f"{mean_ms} ms | {'-' if acc is None else f'{acc:.1%}'} |"
        )

    worst = sorted(
        [r for r in results if r.cer is not None and r.cer > 0],
        key=lambda r: r.cer,
        reverse=True,
    )[:10]
    if worst:
        lines += ["", "## 三、最差页面（Top 10）", "", "| 页面 | CER | 耗时 | 预测（截断） |", "|---|---|---|---|"]
        for r in worst:
            preview = r.text.replace("\n", " ")[:40].replace("|", "／")
            lines.append(f"| {r.page_id} | {r.cer:.3f} | {r.elapsed_ms} ms | {preview} |")
    else:
        lines += ["", "## 三、最差页面", "",
                  "所有有真值的页面 CER 均为 0，未出现识别错误。"]

    failures = [r for r in results if r.status == "failed"]
    lines += ["", "## 四、失败清单", ""]
    if failures:
        lines += ["| 页面 | 图片 | 错误 |", "|---|---|---|"]
        for r in failures:
            lines.append(f"| {r.page_id} | {r.image} | {(r.error or '').replace('|', '／')} |")
    else:
        lines.append("无。")

    lines += [
        "",
        "## 五、结论与下一步",
        "",
        f"- 成功率 {summary['success_rate']:.1%}，"
        + ("达到可用水平。" if summary["success_rate"] >= 0.95 else "低于 95%，需排查失败页。"),
    ]
    if summary["char_accuracy"] is not None:
        acc = summary["char_accuracy"]
        lines.append(
            f"- 字准确率 {acc:.2%}，"
            + ("满足绘本场景（正文短、字号大）。" if acc >= 0.95 else "需要优化预处理或换模型。")
        )
    lines.append(f"- 单页中位耗时 {summary['latency_median_ms']} ms；"
                 "服务化后模型常驻，实际在线延迟会更低。")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    (out_dir / "results.json").write_text(
        json.dumps(
            {"summary": summary, "pages": [asdict(r) for r in results]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="批量 OCR + 评测报告")
    parser.add_argument("--input", default="samples/books", help="书籍根目录")
    parser.add_argument("--out", default="eval", help="报告输出目录")
    parser.add_argument("--data-dir", default=None, help="产物目录，默认 DATA_DIR")
    parser.add_argument("--with-vlm", action="store_true", help="同时跑 VLM（较慢）")
    args = parser.parse_args(argv)

    load_env()
    input_dir = (ROOT / args.input).resolve() if not Path(args.input).is_absolute() else Path(args.input)
    out_dir = (ROOT / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    data_dir = Path(args.data_dir) if args.data_dir else Path(ROOT / "data")
    data_dir.mkdir(parents=True, exist_ok=True)

    pages = discover(input_dir)
    ocr_backend = build_ocr_backend()
    vlm_backend = build_vlm_backend()

    print(f"输入：{input_dir}（{len(pages)} 页）")
    print(f"后端：OCR={ocr_backend.name} VLM={vlm_backend.name if args.with_vlm else 'skipped'}\n")

    # 预热：把首次模型加载排除在单页耗时之外
    try:
        started = time.perf_counter()
        ocr_backend.recognize(load_page_image(pages[0][2]).image)
        print(f"[warmup] {ocr_backend.name} 预热 {int((time.perf_counter() - started) * 1000)} ms\n")
    except Exception as exc:  # noqa: BLE001
        print(f"[warmup] 跳过：{exc}\n")

    results = run_batch(
        pages,
        data_dir=data_dir,
        with_vlm=args.with_vlm,
        ocr_backend=ocr_backend,
        vlm_backend=vlm_backend,
    )
    summary = summarize(results)
    report = write_report(
        results, summary, out_dir,
        input_dir=input_dir, backend=ocr_backend.name,
        vlm=vlm_backend.name if args.with_vlm else "skipped",
    )

    print(f"\n成功率 {summary['success_rate']:.1%}　"
          f"中位耗时 {summary['latency_median_ms']} ms　"
          + (f"字准确率 {summary['char_accuracy']:.2%}" if summary["char_accuracy"] is not None else "无真值"))
    print(f"报告：{report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
