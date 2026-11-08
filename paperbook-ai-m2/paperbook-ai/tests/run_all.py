"""无 pytest 的测试运行器：python tests/run_all.py

CI 里装了 pytest 也可以直接 `pytest -q`，两套都能跑。
"""

from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

MODULES = (
    "test_ids",
    "test_contracts",
    "test_paddle_normalize",
    "test_metrics",
    "test_index",
    "test_mask",
    "test_schema_compat",
    "test_failure_paths",
    "test_explain",
    "test_tap_eval",
    "test_pipeline",
)


def main() -> int:
    passed = 0
    failures: list[tuple[str, str, str]] = []
    for module_name in MODULES:
        module = importlib.import_module(module_name)
        for attr in sorted(dir(module)):
            if not attr.startswith("test_"):
                continue
            fn = getattr(module, attr)
            if not callable(fn):
                continue
            try:
                fn()
                passed += 1
                print(f"  PASS  {module_name}.{attr}")
            except Exception:  # noqa: BLE001
                failures.append((module_name, attr, traceback.format_exc()))
                print(f"  FAIL  {module_name}.{attr}")

    print(f"\n{passed} passed, {len(failures)} failed")
    for module_name, attr, tb in failures:
        print(f"\n--- {module_name}.{attr} ---\n{tb}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
