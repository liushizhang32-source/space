"""后端工厂：后端名 → 实例。pipeline 与 CLI 都只经过这里。"""

from __future__ import annotations

import os

from .base import OcrBackend, VlmBackend
from .paddle_ocr import PaddleOcrBackend
from .qwen_vl import QwenVlBackend
from .stub import StubOcrBackend, StubVlmBackend

OCR_BACKENDS = ("stub", "paddle")
VLM_BACKENDS = ("stub", "http")


def build_ocr_backend(name: str | None = None, *, stub_text: str | None = None) -> OcrBackend:
    resolved = (name or os.getenv("VISION_OCR_BACKEND") or "stub").lower()
    if resolved == "stub":
        return StubOcrBackend(text=stub_text)
    if resolved in ("paddle", "paddleocr"):
        overrides = {}
        if os.getenv("PADDLE_OCR_DET_MODEL"):
            overrides["det_model_name"] = os.environ["PADDLE_OCR_DET_MODEL"]
        if os.getenv("PADDLE_OCR_REC_MODEL"):
            overrides["rec_model_name"] = os.environ["PADDLE_OCR_REC_MODEL"]
        if os.getenv("PADDLE_OCR_ORIENTATION") == "1":
            overrides["use_textline_orientation"] = True
        return PaddleOcrBackend(
            lang=os.getenv("PADDLE_OCR_LANG", "ch"),
            model_dir=os.getenv("PADDLE_OCR_MODEL_DIR") or None,
            enable_mkldnn=os.getenv("PADDLE_OCR_MKLDNN", "0") == "1",
            **overrides,
        )
    raise ValueError(f"未知 OCR 后端 {name!r}，可选：{OCR_BACKENDS}")


def build_vlm_backend(name: str | None = None) -> VlmBackend:
    resolved = (name or os.getenv("VISION_VLM_BACKEND") or "stub").lower()
    if resolved == "stub":
        return StubVlmBackend()
    if resolved in ("http", "qwen", "qwen-vl", "openai"):
        return QwenVlBackend()
    raise ValueError(f"未知 VLM 后端 {name!r}，可选：{VLM_BACKENDS}")
