"""无第三方依赖的测试辅助：没有 pytest 也能跑（python tests/run_all.py）。

注意：不用系统临时目录——本机沙箱对 %TEMP% 限制写入，
统一在仓库内 tests/.tmp 下开临时目录（已在 .gitignore 中）。
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"


def c1_binding(identity: dict, c1_bytes: bytes, image_bytes: bytes) -> dict:
    """按 M1 supervisor.py:282-285 的原生结构构造 ``c1_binding``。

    ``identity`` 是 **OCR attempt** 的七元；与本次 VLM attempt 的
    attempt_id/fencing_token 必然不同，gate 只比较共享五元。
    """
    ocr_identity = {k: identity[k] for k in (
        "job_id", "page_id", "generation_id", "input_revision", "epoch",
        "attempt_id", "fencing_token",
    )}
    ocr_identity["attempt_id"] = "ocr-" + str(ocr_identity["attempt_id"])
    ocr_identity["fencing_token"] = "ocr-" + str(ocr_identity["fencing_token"])
    return {
        "identity": ocr_identity,
        "sha256": hashlib.sha256(c1_bytes).hexdigest(),
        "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
    }


def raises(exc_type: type[BaseException], fn: Callable[..., object], *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except exc_type:
        return
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"期望 {exc_type.__name__}，实际 {type(exc).__name__}: {exc}") from exc
    raise AssertionError(f"期望 {exc_type.__name__}，但没有抛异常")


@contextmanager
def temp_dir() -> Iterator[Path]:
    # 不用 tempfile.mkdtemp：Windows 沙箱下它创建的目录 ACL 会拒绝写入，
    # 这里用 Path.mkdir（继承父目录 ACL）即可。
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = _TMP_ROOT / f"case_{uuid.uuid4().hex[:10]}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
