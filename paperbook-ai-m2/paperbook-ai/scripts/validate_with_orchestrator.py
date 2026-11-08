"""用**公共 Schema** 验证视觉产物（OCRData / VLMData）。

    # 在联合仓库旁边跑（推荐）：--repo-root 指向仓库根
    python scripts/validate_with_orchestrator.py --repo-root C:\\code\\space --all

    # 也可以继续用 PYTHONPATH：
    $env:PYTHONPATH="C:\\code\\space"
    python scripts/validate_with_orchestrator.py --page book01_p01

退出码：
    0  公共 Schema 校验通过（所有被检查的页都通过）
    1  有产物不符合公共 Schema
    2  拿不到公共模型 —— **未验证，不算通过**

说明：
- 公共模型实际位于 `orchestrator/schemas/ocr.py`、`orchestrator/schemas/vlm.py`，
  `orchestrator.schemas` 包本身不一定导出这两个类，所以按子模块导入；
- `--repo-root` 会自动探测 `<root>` 与 `<root>/src` 两种布局，并插到 `sys.path`；
- 只读公共模型，不修改、不复制、不要求对方目录为脚本让路。
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision.config import load_env  # noqa: E402

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_UNVERIFIED = 2


def _pydantic_version() -> str:
    try:
        import pydantic  # noqa: F401

        return getattr(pydantic, "VERSION", "?")
    except Exception:  # noqa: BLE001
        return "未安装"


def find_schema_root(repo_root: Path) -> Path | None:
    """在 <root> 或 <root>/src 下找 orchestrator/schemas/ocr.py。"""
    for candidate in (repo_root, repo_root / "src"):
        if (candidate / "orchestrator" / "schemas" / "ocr.py").is_file():
            return candidate
    return None


def _import_model(module_name: str, class_name: str):
    """先按子模块精确导入，再退一步试包属性。返回 (类, 错误)。"""
    try:
        module = importlib.import_module(module_name)
        model = getattr(module, class_name, None)
        if model is not None:
            return model, ""
        first_error = f"{module_name} 里没有 {class_name}"
    except Exception as exc:  # noqa: BLE001
        first_error = f"import {module_name} 失败：{type(exc).__name__}: {exc}"

    package = module_name.rsplit(".", 1)[0]
    try:
        pkg = importlib.import_module(package)
        model = getattr(pkg, class_name, None)
        if model is not None:
            return model, ""
    except Exception:  # noqa: BLE001
        pass
    return None, first_error


def _validate(model, doc: dict) -> list[str]:
    if hasattr(model, "model_validate"):      # pydantic v2
        try:
            model.model_validate(doc)
            return []
        except Exception as exc:  # noqa: BLE001
            return [str(exc)]
    if hasattr(model, "parse_obj"):           # pydantic v1
        try:
            model.parse_obj(doc)
            return []
        except Exception as exc:  # noqa: BLE001
            return [str(exc)]
    return [f"{model} 不支持 model_validate / parse_obj"]


def _collect_pages(data_dir: Path, page: str | None, all_pages: bool) -> list[str]:
    if page:
        return [page]
    if not all_pages:
        return []
    pages = sorted(
        path.name[: -len("_ocr.json")]
        for path in (data_dir / "json").glob("*_ocr.json")
    )
    return pages


def _collect_flat_pages(flat_dir: Path, page: str | None) -> list[str]:
    """扁平目录：直接放 {page_id}_ocr.json / _vlm.json（如 samples/example/）。"""
    if page:
        return [page]
    if not flat_dir.is_dir():
        return []
    return sorted(
        path.name[: -len("_ocr.json")] for path in flat_dir.glob("*_ocr.json")
    )


def _doc_path(base: Path, page: str, kind: str, *, flat: bool) -> Path:
    if flat:
        return base / f"{page}_{kind}.json"
    return base / "json" / f"{page}_{kind}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用公共 Schema 校验视觉产物")
    parser.add_argument("--page", default=None, help="单页，如 book01_p01")
    parser.add_argument("--all", action="store_true", help="校验 data/json 下所有页")
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument(
        "--from", dest="from_dir", default=None,
        help="扁平目录（直接放 {page_id}_ocr.json / _vlm.json，如 samples/example）",
    )
    parser.add_argument("--repo-root", default=None, help="联合仓库根目录（自动探测 src/ 布局）")
    parser.add_argument("--ocr-module", default="orchestrator.schemas.ocr")
    parser.add_argument("--vlm-module", default="orchestrator.schemas.vlm")
    args = parser.parse_args(argv)

    load_env()
    data_dir = Path(args.data_dir)
    from_dir = Path(args.from_dir) if args.from_dir else None

    if args.repo_root:
        repo_root = Path(args.repo_root).expanduser().resolve()
        schema_root = find_schema_root(repo_root)
        if schema_root is None:
            print(f"[UNVERIFIED] {repo_root} 下找不到 orchestrator/schemas/ocr.py")
            print("  请确认 --repo-root 指向联合仓库根（或它的 src/ 上级）。")
            return EXIT_UNVERIFIED
        sys.path.insert(0, str(schema_root))
        print(f"[INFO] 公共 Schema 根目录：{schema_root}")

    if from_dir is not None:
        pages = _collect_flat_pages(from_dir, args.page)
    else:
        pages = _collect_pages(data_dir, args.page, args.all)
    if not pages:
        print("[ERROR] 没有找到待校验的页：给 --page，或 --all，或 --from <扁平目录>")
        return EXIT_INVALID

    ocr_model, ocr_error = _import_model(args.ocr_module, "OCRData")
    vlm_model, vlm_error = _import_model(args.vlm_module, "VLMData")
    if ocr_model is None or vlm_model is None:
        print("[UNVERIFIED] 拿不到公共 Schema，本次**不能**算通过：")
        if ocr_error:
            print(f"  - {ocr_error}")
        if vlm_error:
            print(f"  - {vlm_error}")
        print("  用 --repo-root 指向联合仓库，或把仓库根加进 PYTHONPATH。")
        return EXIT_UNVERIFIED

    print(f"[INFO] pydantic={_pydantic_version()}")
    print(f"[INFO] OCRData ← {inspect.getsourcefile(ocr_model)}")
    print(f"[INFO] VLMData ← {inspect.getsourcefile(vlm_model)}")
    print(f"[INFO] 待校验 {len(pages)} 页\n")

    failed = 0
    for page in pages:
        for kind, model in (("ocr", ocr_model), ("vlm", vlm_model)):
            path = _doc_path(from_dir or data_dir, page, kind, flat=from_dir is not None)
            if not path.is_file():
                # VLM 阶段失败不产出文件是合法状态，记为 SKIP 而不是失败
                print(f"[SKIP] {page} {kind}.json 不存在（阶段失败或未运行）")
                continue
            doc = json.loads(path.read_text(encoding="utf-8"))
            errors = _validate(model, doc)
            if errors:
                failed += 1
                print(f"[FAIL] {page} {kind}.json")
                for line in errors[0].splitlines()[:10]:
                    print(f"       {line}")
            else:
                print(f"[PASS] {page} {kind}.json  status={doc.get('status')}")

    print()
    if failed:
        print(f"结论：{failed} 个产物不符合公共 Schema")
        return EXIT_INVALID
    print(f"结论：{len(pages)} 页全部通过公共 Schema 校验")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
