"""把示例页装进 DATA_DIR，然后用 CLI 跑通 story -> tts -> video。

用法：
    python examples/install_example.py                # 装到 .env 的 DATA_DIR（默认 ./data）
    DATA_DIR=./_demo python examples/install_example.py

装完之后：
    python -m agents.generation run --page-id book01_p03 --age-level 3-6
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE_ID = "book01_p03"
SOURCE = HERE / PAGE_ID


def main() -> int:
    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    json_dir = data_dir / "json"
    uploads_dir = data_dir / "uploads"
    json_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    for stage in ("ocr", "vlm"):
        src = SOURCE / f"{PAGE_ID}_{stage}.json"
        dst = json_dir / f"{PAGE_ID}_{stage}.json"
        shutil.copy2(src, dst)
        copied.append(dst)

    image = SOURCE / f"{PAGE_ID}_orig.png"
    image_dst = uploads_dir / image.name
    shutil.copy2(image, image_dst)
    copied.append(image_dst)

    # 顺手校验一下示例文件本身没坏（也提醒消费方这些字段是冻结的）
    for stage in ("ocr", "vlm"):
        payload = json.loads((SOURCE / f"{PAGE_ID}_{stage}.json").read_text(encoding="utf-8"))
        assert payload["schema_version"] == "1.0"
        assert payload["page_id"] == PAGE_ID

    print(f"DATA_DIR = {data_dir.resolve()}")
    for path in copied:
        print(f"  + {path}")
    print("\n下一步：python -m agents.generation run --page-id book01_p03 --age-level 3-6")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
