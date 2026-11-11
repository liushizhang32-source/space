"""PaddleOCR 后端（真实模型，懒加载）。

兼容 PP-OCR 2.x 的 ``ocr()`` 与 3.x 的 ``predict()`` 两套返回结构。
依赖缺失时不会在 import 阶段炸，只在真正调用时报错，方便 CI 跑 stub。
"""

from __future__ import annotations

from typing import Any, Sequence

from PIL import Image

from .base import OcrLine


def _poly_to_bbox(poly: Sequence[Sequence[float]]) -> list[float]:
    xs = [float(point[0]) for point in poly]
    ys = [float(point[1]) for point in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


def _is_meaningful(text: str, confidence: float) -> bool:
    """过滤纯符号块（插画边缘常被误检成 "-"）和极低置信块。"""
    if confidence < 0.35:
        return False
    return any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in text)


class PaddleOcrBackend:
    name = "paddleocr"

    def __init__(
        self,
        lang: str = "ch",
        model_dir: str | None = None,
        enable_mkldnn: bool = False,
        det_model_name: str | None = "PP-OCRv5_mobile_det",
        rec_model_name: str | None = "PP-OCRv5_mobile_rec",
        use_textline_orientation: bool = False,
    ) -> None:
        self.lang = lang
        self.model_dir = model_dir
        # Paddle 3.x 在部分 CPU 上 onednn + PIR 会报
        # "ConvertPirAttribute2RuntimeAttribute not support"，默认关掉更稳
        self.enable_mkldnn = enable_mkldnn
        # 实测：默认 medium 模型 CPU 约 8s/页；v5 mobile 约 2s/页，准确率几乎不降
        self.det_model_name = det_model_name
        self.rec_model_name = rec_model_name
        # 绘本文字基本正排；开方向分类会多一次推理，且与 mobile 模型组合有兼容问题
        self.use_textline_orientation = use_textline_orientation
        self._engine: Any = None

    def available(self) -> tuple[bool, str]:
        try:
            import paddleocr  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            return False, f"未安装 paddleocr: {exc}"
        return True, ""

    def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        from paddleocr import PaddleOCR

        kwargs: dict[str, Any] = {"lang": self.lang, "enable_mkldnn": self.enable_mkldnn}
        if self.model_dir:
            kwargs["det_model_dir"] = self.model_dir
        if self.det_model_name:
            kwargs["text_detection_model_name"] = self.det_model_name
        if self.rec_model_name:
            kwargs["text_recognition_model_name"] = self.rec_model_name
        # 3.x 的参数；2.x 不认，回退到老参数
        try:
            self._engine = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=self.use_textline_orientation,
                **kwargs,
            )
        except TypeError:
            self._engine = PaddleOCR(use_angle_cls=True, show_log=False, **kwargs)
        return self._engine

    def recognize(self, image: Image.Image) -> list[OcrLine]:
        if not self.available()[0]:
            raise RuntimeError(self.available()[1])
        import numpy as np

        engine = self._ensure_engine()
        array = np.asarray(image.convert("RGB"))

        if hasattr(engine, "predict"):
            lines = self._normalize_v3(engine.predict(array))
        else:
            lines = self._normalize_v2(engine.ocr(array, cls=True))
        return [line for line in lines if _is_meaningful(line.text, line.confidence)]

    @staticmethod
    def _normalize_v2(result: Any) -> list[OcrLine]:
        lines: list[OcrLine] = []
        if not result:
            return lines
        page = result[0] if isinstance(result, list) and result and isinstance(result[0], list) else result
        for item in page or []:
            try:
                box, payload = item[0], item[1]
                text, score = payload[0], float(payload[1])
            except Exception:  # noqa: BLE001
                continue
            if not text:
                continue
            lines.append(OcrLine(text=str(text), bbox=_poly_to_bbox(box), confidence=score))
        return lines

    @staticmethod
    def _normalize_v3(result: Any) -> list[OcrLine]:
        lines: list[OcrLine] = []
        for page in result or []:
            data = page if isinstance(page, dict) else getattr(page, "json", None)
            if isinstance(data, dict) and "res" in data:
                data = data["res"]
            if not isinstance(data, dict):
                continue
            texts = data.get("rec_texts") or []
            scores = data.get("rec_scores") or []
            polys = data.get("rec_polys") or data.get("dt_polys") or []
            for index, text in enumerate(texts):
                if not text:
                    continue
                try:
                    poly = polys[index]
                    score = float(scores[index]) if index < len(scores) else 0.0
                except Exception:  # noqa: BLE001
                    continue
                lines.append(
                    OcrLine(text=str(text), bbox=_poly_to_bbox(poly), confidence=score)
                )
        return lines
