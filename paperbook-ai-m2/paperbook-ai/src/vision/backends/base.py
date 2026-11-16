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
    # 原始 flags，**逐字保留**；None 表示模型响应里根本没有 flags 字段。
    # V1.2.1 曾把它替换成“原因列表”，导致 flags=["violence"] 被丢掉后误判安全。
    safety_flags: list[str] | None = None
    # 解析出的原因（只用于诊断，不替代 safety_flags）。
    safety_reasons: tuple[str, ...] = ()
    # 原始 safety 对象与其规范化 SHA256，用于跨层对照与证据留存。
    safety_raw: dict | None = None
    safety_evidence: str = ""
    # 安全结论的来源。只有模型响应本身（"model"）才算数；
    # 默认 "unknown" 会被 safety.evaluate_vlm_safety 判为不可信并 fail-closed。
    safety_source: str = "unknown"
    # 置信度缺失/非法的物体数，用于诊断，不参与打分。
    confidence_missing: int = 0


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
