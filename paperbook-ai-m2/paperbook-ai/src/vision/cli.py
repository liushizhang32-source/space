"""命令行入口：一页绘本图 → 两份契约文件。

用法：
    python run.py --image samples/demo_page.png --book-id book01 --page-no 1
    python run.py --image x.jpg --book-id book01 --page-no 1 --ocr-backend paddle --strict

后端默认值来自 .env（VISION_OCR_BACKEND / VISION_VLM_BACKEND）。
配置的后端不可用时自动回退 stub 并打印警告；加 --strict 则直接失败。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import ids, pipeline
from .backends import OCR_BACKENDS, VLM_BACKENDS, build_ocr_backend, build_vlm_backend
from .config import find_env_file, load_env

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_BAD_ARG = 2
EXIT_BACKEND = 3
EXIT_CONTRACT = 4
EXIT_STAGE = 5  # 执行成功但某个阶段失败（status=failed / 失败未产出文件）


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vision", description="绘本单页视觉流水线（成员2）：输出 ocr.json / vlm.json"
    )
    parser.add_argument("--image", required=True, help="绘本页图片路径")
    parser.add_argument("--book-id", required=True, help="如 book01")
    parser.add_argument("--page-no", type=int, required=True, help="从 1 开始")
    parser.add_argument(
        "--data-dir", default=None, help="产物根目录，默认取 DATA_DIR 或 ./data"
    )
    parser.add_argument("--ocr-backend", choices=OCR_BACKENDS, default=None)
    parser.add_argument("--vlm-backend", choices=VLM_BACKENDS, default=None)
    parser.add_argument(
        "--only", choices=("both", "ocr", "vlm"), default="both",
        help="只跑 OCR 或只跑 VLM（独立验收用），默认都跑",
    )
    parser.add_argument("--stub-text", default=None, help="stub OCR 的文本，多行用 ; 分隔")
    parser.add_argument("--strict", action="store_true", help="后端不可用时直接失败，不回退")
    parser.add_argument("--print-json", action="store_true", help="打印完整 JSON")
    return parser


def _with_fallback(backend, factory, *, strict: bool, stub_text: str | None = None):
    """后端不可用 → 回退 stub（默认），除非 strict。返回 (backend, warning)。"""
    available, reason = backend.available()
    if available:
        return backend, None
    if strict or os.getenv("VISION_STRICT_BACKEND") == "1":
        return None, reason
    fallback = factory("stub", stub_text=stub_text)
    return fallback, reason


def main(argv: list[str] | None = None) -> int:
    loaded = load_env()
    args = build_parser().parse_args(argv)

    env_file = find_env_file()
    env_note = (
        f"{env_file.name} 已加载（OCR={os.getenv('VISION_OCR_BACKEND', 'stub')}"
        f", VLM={os.getenv('VISION_VLM_BACKEND', 'stub')}）"
        if loaded
        else "未找到 .env，使用默认 stub"
    )
    print(f"[env] {env_note}")

    try:
        ids.make_page_id(args.book_id, args.page_no)
    except ids.IdError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_BAD_ARG

    # 先确定跑哪些阶段，再只初始化所需后端——
    # 否则 --only ocr --strict 会被不可用的 VLM 后端挡住（第二轮 F05）
    run_ocr = args.only in ("both", "ocr")
    run_vlm = args.only in ("both", "vlm")

    stub_text = args.stub_text.replace(";", "\n") if args.stub_text else None
    ocr_backend = vlm_backend = None

    if run_ocr:
        ocr_backend, ocr_reason = _with_fallback(
            build_ocr_backend(args.ocr_backend),
            build_ocr_backend,
            strict=args.strict,
            stub_text=stub_text,
        )
        if ocr_backend is None:
            print(f"[ERROR] OCR 后端不可用：{ocr_reason}", file=sys.stderr)
            return EXIT_BACKEND
        if ocr_reason:
            print(f"[WARN] OCR 后端不可用（{ocr_reason}），本次用 stub 输出", file=sys.stderr)

    if run_vlm:
        vlm_backend, vlm_reason = _with_fallback(
            build_vlm_backend(args.vlm_backend), build_vlm_backend, strict=args.strict
        )
        if vlm_backend is None:
            print(f"[ERROR] VLM 后端不可用：{vlm_reason}", file=sys.stderr)
            return EXIT_BACKEND
        if vlm_reason:
            print(f"[WARN] VLM 后端不可用（{vlm_reason}），本次用 stub 输出", file=sys.stderr)

    data_dir = args.data_dir or os.getenv("DATA_DIR", "./data")
    try:
        result = pipeline.run_page(
            image_path=args.image,
            book_id=args.book_id,
            page_no=args.page_no,
            data_dir=data_dir,
            ocr_backend=ocr_backend,
            vlm_backend=vlm_backend,
            run_ocr=run_ocr,
            run_vlm=run_vlm,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 流水线失败：{exc}", file=sys.stderr)
        return EXIT_RUNTIME

    print(f"page_id   : {result.page_id}")
    if result.ocr is not None:
        print(
            f"ocr.json  : {result.ocr_path}  [{result.ocr['status']}] "
            f"blocks={len(result.ocr['text_blocks'])} "
            f"conf={result.ocr['page_confidence']:.2f} {result.ocr['elapsed_ms']}ms"
        )
    if result.vlm is not None:
        print(
            f"vlm.json  : {result.vlm_path}  [{result.vlm['status']}] "
            f"objects={len(result.vlm['objects'])} {result.vlm['elapsed_ms']}ms"
        )

    if args.print_json:
        print(json.dumps({"ocr": result.ocr, "vlm": result.vlm}, ensure_ascii=False, indent=2))

    errors = [*result.ocr_errors, *result.vlm_errors]
    if errors:
        print("[CONTRACT] 契约校验失败：", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return EXIT_CONTRACT

    stage_errors = [e for e in (result.ocr_error, result.vlm_error) if e is not None]
    if stage_errors:
        print("contract  : ok（字段合规，但阶段失败）", file=sys.stderr)
        for stage_error in stage_errors:
            print(
                f"[STAGE] {stage_error.stage} 失败 code={stage_error.code} "
                f"{stage_error.elapsed_ms}ms: {stage_error.message}",
                file=sys.stderr,
            )
            print(
                f"        详情：data/logs/{result.page_id}_{stage_error.stage}.error.json",
                file=sys.stderr,
            )
        return EXIT_STAGE

    print("contract  : ok")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
