"""检查 VLM 服务是否可用，并验证它能否按 C2 契约输出物体。

用法：
    python scripts/check_vlm.py                # 用 samples/demo_page.png
    python scripts/check_vlm.py --image x.jpg

它会：
1. 打印后端配置（base_url / model）；
2. 发一张图，量一次调用耗时；
3. 用返回结果构造 vlm.json 并跑契约校验，把 objects 打出来。

这一步过了，再把 .env 的 VISION_VLM_BACKEND 切到 http。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision import contracts, validate  # noqa: E402
from vision.backends import build_vlm_backend  # noqa: E402
from vision.backends.qwen_vl import QwenVlBackend  # noqa: E402
from vision.config import load_env  # noqa: E402
from vision.preprocess import load_page_image  # noqa: E402

SAMPLE_TEXT = "小兔子在森林里发现了一根胡萝卜"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VLM 连通性与契约检查")
    parser.add_argument("--image", default=str(ROOT / "samples" / "demo_page.png"))
    parser.add_argument("--base-url", default=None, help="临时指定端点，覆盖 .env（如云 GPU）")
    parser.add_argument("--model", default=None, help="临时指定模型名，覆盖 .env")
    parser.add_argument("--api-key", default=None, help="临时指定 key，覆盖 .env")
    args = parser.parse_args(argv)

    load_env()
    if args.base_url or args.model:
        backend = QwenVlBackend(
            base_url=args.base_url, model=args.model, api_key=args.api_key
        )
    else:
        backend = build_vlm_backend()
    available, reason = backend.available()
    print(f"后端    : {backend.name}")
    print(f"base_url: {getattr(backend, 'base_url', '-')}")
    print(f"model   : {getattr(backend, 'model', '-')}")

    if not available:
        print(f"\n不可用：{reason}")
        print("检查 .env 里的 QWEN_VL_BASE_URL / QWEN_VL_MODEL，并确认服务已启动。")
        return 1

    image_path = Path(args.image)
    if not image_path.is_file():
        print(f"\n找不到图片：{image_path}")
        return 1
    page = load_page_image(image_path)

    print(f"\n调用中（{page.width}x{page.height}）…")
    started = time.perf_counter()
    try:
        result = backend.understand(page.image, SAMPLE_TEXT)
    except Exception as exc:  # noqa: BLE001
        print(f"调用失败：{type(exc).__name__}: {exc}")
        return 2
    elapsed = time.perf_counter() - started

    doc = contracts.build_vlm_document(
        book_id="book01",
        page_id="book01_p01",
        page_no=1,
        image_width=page.width,
        image_height=page.height,
        description=result.description,
        objects=result.objects,
        scene_tags=result.scene_tags,
        safety_pass=result.safety_pass,
        safety_flags=result.safety_flags,
        elapsed_ms=int(elapsed * 1000),
        backend=backend.name,
        scale=page.scale,
    )

    print(f"\n耗时    : {elapsed:.2f}s")
    print(f"描述    : {doc['description']}")
    print(f"场景标签: {doc['scene_tags']}")
    print(f"物体    : {len(doc['objects'])} 个")
    for obj in doc["objects"]:
        print(f"  - {obj['label']:<8} bbox={obj['bbox']} conf={obj['confidence']:.2f}")

    errors = validate.validate_vlm(doc)
    if errors:
        print("\n契约校验失败：")
        for error in errors:
            print("  -", error)
        return 3

    print("\ncontract : ok")
    if elapsed > 5:
        print(f"提示：单次 {elapsed:.1f}s 偏慢，演示时考虑降分辨率或换更小模型")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
