"""后端协议：OCR / VLM 都可插拔，pipeline 只认这两个 Protocol。

约定：后端返回的 bbox 是**工作副本像素**（绝对坐标），由 contracts 负责
除以 scale 还原成原图坐标。后端不要自己处理 ID、状态、落盘。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

from PIL import Image


@dataclass
class OcrLine:
    text: str
    bbox: Sequence[float]  # 工作副本像素 [x1, y1, x2, y2]
    confidence: float = 0.0


@dataclass
class VlmObject:
    label: str
    bbox: Sequence[float]
    confidence: float = 0.0


@dataclass(kw_only=True)
class VlmResult:
    """VLM 阶段结果。

    ``safety_pass`` 是**必填**：安全结论必须由后端显式给出，
    忘传时构造即报错，不存在"默认安全"的路径（第三轮 R02）。
    """

    description: str
    safety_pass: bool
    objects: list[VlmObject] = field(default_factory=list)
    scene_tags: list[str] = field(default_factory=list)
    safety_flags: list[str] = field(default_factory=list)


@runtime_checkable
class OcrBackend(Protocol):
    name: str

    def available(self) -> tuple[bool, str]:
        """(是否可用, 不可用原因)"""
        ...

    def recognize(self, image: Image.Image) -> list[OcrLine]:
        ...


@runtime_checkable
class VlmBackend(Protocol):
    name: str

    def available(self) -> tuple[bool, str]:
        ...

    def understand(self, image: Image.Image, ocr_text: str) -> VlmResult:
        ...
