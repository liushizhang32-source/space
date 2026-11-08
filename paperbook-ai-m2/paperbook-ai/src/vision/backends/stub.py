"""打桩后端：不依赖任何模型，用来打通契约与联调。

产物会带 ``producer.backend = "stub"``，评测/答辩不要拿它当真实结果。
默认布局是确定性的：文字块自上而下均分，物体框固定落在画面中部，
保证同一张图多次运行结果完全一致（可复现）。
"""

from __future__ import annotations

from PIL import Image

from .base import OcrLine, VlmObject, VlmResult

DEFAULT_TEXT = "小兔子在森林里发现了一根胡萝卜"


class StubOcrBackend:
    name = "stub"

    def __init__(self, text: str | None = None) -> None:
        raw = DEFAULT_TEXT if text is None else text
        self._lines = [line.strip() for line in raw.splitlines() if line.strip()]

    def available(self) -> tuple[bool, str]:
        return True, ""

    def recognize(self, image: Image.Image) -> list[OcrLine]:
        width, height = image.size
        if not self._lines:
            return []
        top = int(height * 0.62)
        band = max(8, int(height * 0.07))
        left, right = int(width * 0.08), int(width * 0.92)
        lines: list[OcrLine] = []
        for index, text in enumerate(self._lines):
            y1 = min(top + index * band, height - 2)
            y2 = min(y1 + band - 4, height - 1)
            if y2 <= y1:
                break
            lines.append(OcrLine(text=text, bbox=[left, y1, right, y2], confidence=0.99))
        return lines


class StubVlmBackend:
    name = "stub"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def understand(self, image: Image.Image, ocr_text: str) -> VlmResult:
        width, height = image.size
        hint = ocr_text.strip().splitlines()[0] if ocr_text.strip() else "无字页"
        objects = [
            VlmObject(
                label="兔子",
                bbox=[int(width * 0.18), int(height * 0.28), int(width * 0.46), int(height * 0.62)],
                confidence=0.90,
            ),
            VlmObject(
                label="树",
                bbox=[int(width * 0.58), int(height * 0.08), int(width * 0.92), int(height * 0.72)],
                confidence=0.93,
            ),
        ]
        return VlmResult(
            description=f"（stub）画面内容占位，参考文字：{hint}",
            objects=objects,
            scene_tags=["stub"],
            # 打桩结果不是真实安全结论：显式标注来源，避免被当成已审查内容
            safety_pass=False,
            safety_flags=["stub_mock"],
        )
