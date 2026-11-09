"""pytest 公共夹具：临时 DATA_DIR、样例 ocr/vlm、ffmpeg 探测。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from agents.generation.config import Settings

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_FFMPEG_DIR = ROOT / "_tools" / "ffmpeg" / "ffmpeg-9.0.2-essentials_build" / "bin"


def _resolve(name: str) -> str | None:
    env_value = os.environ.get(f"{name.upper()}_PATH") or os.environ.get(name.upper())
    if env_value and Path(env_value).is_file():
        return str(Path(env_value))
    bundled = BUNDLED_FFMPEG_DIR / f"{name}.exe"
    if bundled.is_file():
        return str(bundled)
    found = shutil.which(name)
    return found


@pytest.fixture(scope="session")
def ffmpeg_pair() -> tuple[str, str]:
    ffmpeg, ffprobe = _resolve("ffmpeg"), _resolve("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("环境里没有 ffmpeg/ffprobe，跳过需要真实编码的用例")
    return ffmpeg, ffprobe


@pytest.fixture
def tmp_path():
    """自带 tmp_path：本机沙箱里 pytest 的 tmpdir 清理钩子会误报权限错误，索性不用它。

    用例结束后尽力清理；Windows 上若有句柄未释放则忽略。
    """
    import uuid

    path = ROOT / "_test_tmp" / uuid.uuid4().hex[:12]
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """不依赖 ffmpeg 的配置（纯逻辑用例用这个）。"""
    config = Settings(
        data_dir=tmp_path / "data",
        asset_base_url="http://test.local",
        ffmpeg_path=_resolve("ffmpeg") or "ffmpeg",
        ffprobe_path=_resolve("ffprobe") or "ffprobe",
        tts_engine="silent",
        tts_voice_id="female_warm",
        max_retry=0,
        retry_backoff_sec=0.0,
    )
    config.ensure_dirs()
    return config


@pytest.fixture
def media_settings(tmp_path: Path, ffmpeg_pair: tuple[str, str]) -> Settings:
    """需要真实编码的用例：强制指定 ffmpeg/ffprobe。"""
    ffmpeg, ffprobe = ffmpeg_pair
    config = Settings(
        data_dir=tmp_path / "data",
        asset_base_url="http://test.local",
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        tts_engine="silent",
        max_retry=0,
        retry_backoff_sec=0.0,
    )
    config.ensure_dirs()
    return config


@pytest.fixture
def sample_ocr() -> dict:
    return {
        "schema_version": "1.0",
        "book_id": "book01",
        "page_id": "book01_p03",
        "page_no": 3,
        "status": "ok",
        "image_width": 900,
        "image_height": 1200,
        "text_blocks": [
            {
                "block_id": "book01_p03_t01",
                "order": 1,
                "text": "从前有只小兔子，住在森林边上。",
                "bbox": [90, 940, 800, 990],
                "confidence": 0.97,
            },
            {
                "block_id": "book01_p03_t02",
                "order": 2,
                "text": "一天晚上，它出门去找朋友。",
                "bbox": [90, 998, 800, 1048],
                "confidence": 0.96,
            },
        ],
        "page_confidence": 0.965,
        "elapsed_ms": 1830,
    }


@pytest.fixture
def sample_vlm() -> dict:
    return {
        "schema_version": "1.0",
        "book_id": "book01",
        "page_id": "book01_p03",
        "page_no": 3,
        "status": "ok",
        "image_width": 900,
        "image_height": 1200,
        "description": "夜晚的森林，一只小兔子站在树下，月光洒在树梢。",
        "objects": [
            {"object_id": "book01_p03_o01", "label": "兔子", "bbox": [420, 620, 620, 900], "confidence": 0.92},
            {"object_id": "book01_p03_o02", "label": "树", "bbox": [60, 470, 300, 1080], "confidence": 0.96},
        ],
        "scene_tags": ["夜晚", "森林"],
        "safety": {"pass": True, "flags": []},
        "elapsed_ms": 2100,
    }


@pytest.fixture
def page_image(tmp_path: Path) -> Path:
    """造一张 600x800 的假书页（PIL 在离线环境里也能画）。"""
    from PIL import Image, ImageDraw

    path = tmp_path / "data" / "uploads" / "book01_p03_orig.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (600, 800), "#1b2a4a")
    draw = ImageDraw.Draw(image)
    draw.ellipse([380, 80, 480, 180], fill="#f4e7c5")
    draw.rectangle([60, 420, 540, 760], fill="#22402f")
    image.save(path)
    return path
