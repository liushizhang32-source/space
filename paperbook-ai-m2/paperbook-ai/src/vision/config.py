"""极简 .env 加载器（不引入 python-dotenv，零依赖）。

约定：
- **已存在的环境变量优先**：现场用 `export`/`set` 覆盖 .env，符合直觉；
- 支持 `#` 注释、`KEY=VALUE`、值两侧引号；
- 默认读仓库根目录 `.env`，可用环境变量 `PB_ENV_FILE` 指定别处。
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"


def find_env_file() -> Path | None:
    override = os.getenv("PB_ENV_FILE")
    if override:
        path = Path(override)
        return path if path.is_file() else None
    return DEFAULT_ENV_FILE if DEFAULT_ENV_FILE.is_file() else None


def parse_env_file(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env(path: str | Path | None = None, *, override: bool = False) -> dict[str, str]:
    """把 .env 灌进 os.environ；返回实际加载的键值。"""
    target = Path(path) if path else find_env_file()
    values: dict[str, str] = {}
    if target is not None and target.is_file():
        values = parse_env_file(target)
        for key, value in values.items():
            if override or key not in os.environ:
                os.environ[key] = value
        _anchor_paths_to_repo()
    _ensure_matplotlib_cache()
    return values


def _ensure_matplotlib_cache() -> None:
    """paddleocr 会间接 import matplotlib，它默认往用户目录写字体缓存。

    在只读家目录 / 容器里这会直接抛 PermissionError，导致 OCR 启动失败。
    这里把缓存目录固定到 DATA_DIR 下，用户显式设了 MPLCONFIGDIR 就不动。
    """
    if os.environ.get("MPLCONFIGDIR"):
        return
    base = Path(os.environ.get("DATA_DIR") or (REPO_ROOT / "data"))
    if not base.is_absolute():
        base = REPO_ROOT / base
    cache = base / ".mplconfig"
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001 - 建不出来就交给 matplotlib 自己处理
        return
    os.environ["MPLCONFIGDIR"] = str(cache)


# 这些键是路径，相对路径必须锚定仓库根目录——
# 否则在 PyCharm 里以 scripts/ 为工作目录运行时，会重新下载模型到 scripts/models。
_PATH_KEYS = (
    "DATA_DIR",
    "PADDLE_PDX_CACHE_HOME",
    "PADDLE_OCR_MODEL_DIR",
    "QWEN_VL_MODEL_PATH",
    "WHISPER_MODEL_PATH",
)


def _anchor_paths_to_repo() -> None:
    for key in _PATH_KEYS:
        raw = os.environ.get(key)
        if not raw:
            continue
        path = Path(raw)
        if path.is_absolute():
            continue
        os.environ[key] = str((REPO_ROOT / path).resolve())
