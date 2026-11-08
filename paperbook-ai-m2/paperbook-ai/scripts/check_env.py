"""环境自检：在接真实模型之前，先确认这套代码在本机能跑。

    python scripts/check_env.py

退出码：0 = 核心链路可用；1 = 有阻塞项。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vision import pipeline  # noqa: E402
from vision.backends import build_ocr_backend, build_vlm_backend  # noqa: E402
from vision.config import find_env_file, load_env  # noqa: E402

load_env()

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

results: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))


def check_python() -> None:
    version = sys.version_info
    label = f"{version.major}.{version.minor}.{version.micro}"
    if version < (3, 10):
        record("Python 版本", FAIL, f"{label}，需要 ≥3.10")
    elif version >= (3, 13):
        record("Python 版本", WARN, f"{label}，Paddle 生态可能未提供 wheel，建议 3.10–3.12")
    else:
        record("Python 版本", OK, label)


def check_deps() -> None:
    for module, package in (("PIL", "pillow"), ("numpy", "numpy")):
        spec = importlib.util.find_spec(module)
        if spec is None:
            record(f"依赖 {package}", FAIL, "未安装：pip install -r requirements.txt")
        else:
            mod = __import__(module)
            record(f"依赖 {package}", OK, getattr(mod, "__version__", "已安装"))


def check_ocr_backend() -> None:
    backend = build_ocr_backend()
    available, reason = backend.available()
    if backend.name == "stub":
        record("OCR 后端", WARN, "当前是 stub（打桩）。接真模型：--ocr-backend paddle")
    elif available:
        record("OCR 后端", OK, backend.name)
    else:
        record("OCR 后端", FAIL, f"{backend.name} 不可用：{reason}")


def check_vlm_backend() -> None:
    backend = build_vlm_backend()
    available, reason = backend.available()
    if backend.name == "stub":
        record("VLM 后端", WARN, "当前是 stub。配置 QWEN_VL_BASE_URL 后 --vlm-backend http")
    elif available:
        record("VLM 后端", OK, backend.name)
    else:
        record("VLM 后端", FAIL, f"{backend.name} 不可用：{reason}")


def check_data_dir() -> None:
    data_dir = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
    try:
        target = data_dir / "json"
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        record("DATA_DIR 可写", OK, str(target))
    except Exception as exc:  # noqa: BLE001
        record("DATA_DIR 可写", FAIL, f"{data_dir}: {exc}")


def check_smoke() -> None:
    sample = ROOT / "samples" / "demo_page.png"
    if not sample.is_file():
        record("冒烟测试", WARN, "缺少 samples/demo_page.png，先跑 scripts/make_demo_page.py")
        return

    data_dir = ROOT / "data"
    try:
        result = pipeline.run_page(
            image_path=sample,
            book_id="check01",
            page_no=1,
            data_dir=data_dir,
            ocr_backend=build_ocr_backend("stub"),
            vlm_backend=build_vlm_backend("stub"),
        )
    except Exception as exc:  # noqa: BLE001
        record("冒烟测试", FAIL, f"{type(exc).__name__}: {exc}")
        return

    if not result.ok:
        parts = []
        if result.ocr_errors:
            parts.append(f"ocr 契约错误：{result.ocr_errors[:1]}")
        if result.vlm_errors:
            parts.append(f"vlm 契约错误：{result.vlm_errors[:1]}")
        for stage_error in (result.ocr_error, result.vlm_error):
            if stage_error:
                parts.append(f"{stage_error.stage} 失败：{stage_error.message[:60]}")
        record("冒烟测试", FAIL, "；".join(parts))
        return
    record(
        "冒烟测试",
        OK,
        f"{result.page_id}：ocr[{result.ocr['status'] if result.ocr else '-'}] "
        f"vlm[{result.vlm['status'] if result.vlm else '未产出'}] → data/json/",
    )


def main() -> int:
    check_python()
    check_deps()
    check_ocr_backend()
    check_vlm_backend()
    check_data_dir()
    check_smoke()

    width = max(len(name) for name, _, _ in results) + 2
    print("=" * 64)
    print("纸书智伴 · 视觉模块环境自检")
    print("=" * 64)
    for name, status, detail in results:
        print(f"{name:<{width}} [{status}]  {detail}")
    print("-" * 64)

    failures = [name for name, status, _ in results if status == FAIL]
    if failures:
        print(f"阻塞项：{', '.join(failures)}")
        return 1
    print("核心链路可用。接真实模型：--ocr-backend paddle / --vlm-backend http")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
