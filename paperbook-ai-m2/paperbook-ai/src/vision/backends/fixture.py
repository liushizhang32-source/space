"""离线 fixture 后端：确定性的、可审查的夹具结果。

与 ``stub`` 的区别只有一个：fixture 是**离线协议测试**里被明确声明的夹具，
它的 safety 证据是夹具自带的 ``pass=true / flags=[]``，用于验证正例链路；
它不代表真实模型，也不得在真实绘本评测中被当作模型输出。
"""

from __future__ import annotations

from PIL import Image

from .base import VlmObject, VlmResult
from .stub import StubOcrBackend

FIXTURE_TEXT = "FIXTURE TEXT FOR OFFLINE PROTOCOL"


class FixtureOcrBackend(StubOcrBackend):
    name = "fixture"

    def __init__(self) -> None:
        super().__init__(text=FIXTURE_TEXT)


class FixtureVlmBackend:
    name = "fixture"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def understand(self, image: Image.Image, ocr_text: str) -> VlmResult:
        width, height = image.size
        objects = [
            VlmObject(
                label="fixture-object",
                bbox=[int(width * 0.20), int(height * 0.30), int(width * 0.45), int(height * 0.60)],
                confidence=0.90,
            )
        ]
        return VlmResult(
            description="offline fixture description",
            objects=objects,
            scene_tags=["fixture"],
            safety_pass=True,
            safety_flags=[],
            safety_reasons=(),
            safety_raw={"pass": True, "flags": []},
            safety_source="model",
        )
