"""输入过滤（V1.2）：在解码前挡住不可信 / 超规格的绘本图片。

V1.1.1 只校验「存在 + 长边 ≤ 4096」，但独立运行（CLI / sidecar）时
上传方并不可信：PDF 伪装成 .png、100 MB 的扫描件、像素炸弹、
动图、压缩包都会被直接送进 PIL。本模块把检查前移到**读文件头**，
不通过就不解码，错误码沿用契约里的 1004 / 1006。

边界：
- 只做**格式与规格**过滤，不做内容安全（内容安全在 safety.py）；
- 不替换 preprocess 的 EXIF / 缩放逻辑，guard 先行、load 随后；
- 拒绝动画 GIF / APNG，避免「一页取到第一帧」这种静默错误。
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .preprocess import ImageLoadError

ERROR_IMAGE_TOO_LARGE = 1004   # 尺寸/体积超限（§1.3）
ERROR_IMAGE_UNSUPPORTED = 1006  # 无法解码 / 格式不支持（§1.3）

MAX_BYTES = 25 * 1024 * 1024
"""单文件上限 25 MiB：手机原图通常 3–8 MiB，留足余量。"""

MAX_PIXELS = 40_000_000
"""解码后像素上限 40 MP：4096×4096 ≈ 16.8 MP，40 MP 足够双页跨图。"""

MIN_SIDE = 8
# 收窄到冻结契约常见的三种位图；BMP/TIFF 不在本次放行范围内（V1.2.1 P1-7：
# 只能保持或收紧，不能擅自扩大；要放宽须走 D02 批准）。
ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})

# (magic, 人类可读类型)：这些类型即使 PIL 能解码也不当绘本页
_DENY_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "PDF"),
    (b"<svg", "SVG"),
    (b"<?xml", "XML"),
    (b"PK\x03\x04", "ZIP"),
    (b"Rar!\x1a\x07", "RAR"),
    (b"7z\xbc\xaf\x27\x1c", "7Z"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"\x7fELF", "ELF"),
    (b"MZ", "PE"),
)


class InputRejected(ImageLoadError):
    """输入被过滤（继承 ImageLoadError，CLI 按参数错误处理）。"""

    def __init__(self, code: int, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ImageInfo:
    path: Path
    byte_size: int
    width: int
    height: int
    format: str
    mode: str
    animated: bool


def _denied_type(head: bytes) -> str | None:
    for magic, name in _DENY_MAGIC:
        if head.startswith(magic):
            return name
    return None


def guard_image(
    image_path: str | Path,
    *,
    data: bytes | None = None,
    max_bytes: int = MAX_BYTES,
    max_pixels: int = MAX_PIXELS,
) -> ImageInfo:
    """读文件头并做规格校验；不通过抛 ``InputRejected``。

    只打开、不解码像素（``Image.open`` 惰性），因此对超大图也很快。
    ``data`` 给定时按内存字节校验（Worker 已读一遍并算过 SHA256，
    避免“校验后文件被替换”的 TOCTOU）。
    """
    path = Path(image_path)
    if data is None:
        if not path.is_file():
            raise InputRejected(ERROR_IMAGE_UNSUPPORTED, f"图片不存在: {path}")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise InputRejected(
                ERROR_IMAGE_UNSUPPORTED, f"无法读取文件: {type(exc).__name__}"
            ) from exc

    byte_size = len(data)
    if byte_size <= 0:
        raise InputRejected(ERROR_IMAGE_UNSUPPORTED, "空文件")
    if byte_size > max_bytes:
        raise InputRejected(
            ERROR_IMAGE_TOO_LARGE,
            f"文件体积 {byte_size} 字节超过上限 {max_bytes}",
        )

    head = data[:16]
    denied = _denied_type(head)
    if denied is not None:
        raise InputRejected(ERROR_IMAGE_UNSUPPORTED, f"不支持的文件类型: {denied}")

    try:
        with Image.open(io.BytesIO(data)) as handle:
            fmt = (handle.format or "").upper()
            width, height = handle.size
            mode = handle.mode
            animated = bool(getattr(handle, "is_animated", False))
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InputRejected(
            ERROR_IMAGE_UNSUPPORTED, f"图片无法解码: {type(exc).__name__}"
        ) from exc

    if fmt not in ALLOWED_FORMATS:
        raise InputRejected(ERROR_IMAGE_UNSUPPORTED, f"不支持的图片格式: {fmt or 'unknown'}")
    if animated:
        raise InputRejected(ERROR_IMAGE_UNSUPPORTED, "不支持动图，请取单帧静态页")
    if width <= 0 or height <= 0:
        raise InputRejected(ERROR_IMAGE_UNSUPPORTED, f"图片尺寸非法: {width}x{height}")
    if min(width, height) < MIN_SIDE:
        raise InputRejected(
            ERROR_IMAGE_UNSUPPORTED, f"图片过小: {width}x{height}，短边至少 {MIN_SIDE}px"
        )
    if width * height > max_pixels:
        raise InputRejected(
            ERROR_IMAGE_TOO_LARGE,
            f"像素数 {width * height} 超过上限 {max_pixels}（{width}x{height}）",
        )

    return ImageInfo(
        path=path,
        byte_size=byte_size,
        width=width,
        height=height,
        format=fmt,
        mode=mode,
        animated=animated,
    )
