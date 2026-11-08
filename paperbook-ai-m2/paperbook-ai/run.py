"""根目录快捷入口：python run.py --image ... --book-id ... --page-no ...

不装包也能跑，避免比赛现场还要 ``pip install -e .``。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from vision.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
