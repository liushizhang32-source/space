"""第一轮验收问题的回归测试。

覆盖四件事：
1. 输出字段与公共 Schema 完全一致（不擅自附加 producer / error）；
2. 安全值 "false" 必须解析成 False；
3. EXIF 方向：bbox 最终落在**原图像素**坐标系；
4. OCR / VLM 可独立运行。
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image

from vision import contracts, pipeline, preprocess
from vision.backends.base import OcrLine, VlmObject
from vision.backends.qwen_vl import QwenVlBackend, parse_bool, parse_flags, parse_safety
from vision.backends.stub import StubOcrBackend

from _helpers import temp_dir

OCR_KEYS = {
    "schema_version", "book_id", "page_id", "page_no", "status",
    "image_width", "image_height", "text_blocks", "page_confidence", "elapsed_ms",
}
VLM_KEYS = {
    "schema_version", "book_id", "page_id", "page_no", "status",
    "image_width", "image_height", "description", "objects", "scene_tags",
    "safety", "elapsed_ms",
}


# ---------- 1. 字段集合与公共 Schema 一致 ----------

def test_ocr_ok_keys_exact():
    doc = contracts.build_ocr_document(
        book_id="book01", page_id="book01_p01", page_no=1,
        image_width=100, image_height=100,
        lines=[OcrLine("你好", [1, 1, 50, 20], 0.9)],
        elapsed_ms=10, backend="paddleocr",
    )
    assert set(doc) == OCR_KEYS
    assert set(doc["text_blocks"][0]) == {"block_id", "order", "text", "bbox", "confidence"}


def test_ocr_failed_keys_exact():
    doc = contracts.failed_ocr_document(
        book_id="book01", page_id="book01_p01", page_no=1,
        width=100, height=100, elapsed_ms=10, backend="paddleocr",
        code=2001, msg="超时",
    )
    assert set(doc) == OCR_KEYS
    assert doc["status"] == "failed"
    assert doc["text_blocks"] == []


def test_vlm_ok_and_empty_keys_exact():
    ok = contracts.build_vlm_document(
        book_id="book01", page_id="book01_p01", page_no=1,
        image_width=100, image_height=100, description="画面",
        objects=[VlmObject("兔子", [1, 1, 50, 50], 0.9)],
        scene_tags=["森林"], elapsed_ms=10, backend="vlm", safety_pass=True,
    )
    assert set(ok) == VLM_KEYS
    assert set(ok["objects"][0]) == {"object_id", "label", "bbox", "confidence"}
    assert set(ok["safety"]) == {"pass", "flags"}

    empty = contracts.build_vlm_document(
        book_id="book01", page_id="book01_p01", page_no=1,
        image_width=100, image_height=100, description="", objects=[],
        safety_pass=True,
        elapsed_ms=10, backend="vlm",
    )
    assert set(empty) == VLM_KEYS
    assert empty["status"] == "empty"


def test_vlm_status_enum_excludes_failed():
    """公共 VLMData 只有 ok / empty：构造 failed 必须被拒绝。"""
    for status in ("failed", "error", "unknown"):
        try:
            contracts.build_vlm_document(
                book_id="book01", page_id="book01_p01", page_no=1,
                image_width=100, image_height=100, description="",
                objects=[], status=status, elapsed_ms=1, backend="vlm",
                safety_pass=True,
            )
        except ValueError as exc:
            assert "VLMData.status" in str(exc)
        else:
            raise AssertionError(f"status={status} 应被拒绝")


def test_failed_vlm_document_is_removed():
    """旧的 failed_vlm_document 入口必须显式报错，避免误用产出非法文件。"""
    try:
        contracts.failed_vlm_document(
            book_id="book01", page_id="book01_p01", page_no=1,
            width=100, height=100, elapsed_ms=10, backend="vlm",
            code=2001, msg="超时",
        )
    except ValueError as exc:
        assert "StageError" in str(exc)
    else:
        raise AssertionError("failed_vlm_document 应直接报错")


def test_builder_rejects_non_bool_safety():
    for value in ("false", "true", None, 0, 1):
        try:
            contracts.build_vlm_document(
                book_id="book01", page_id="book01_p01", page_no=1,
                image_width=100, image_height=100, description="",
                objects=[], safety_pass=value, elapsed_ms=1, backend="vlm",
            )
        except TypeError:
            continue
        raise AssertionError(f"safety_pass={value!r} 应被拒绝")


def test_blocks_are_capped_at_99():
    lines = [OcrLine(f"第{i}行", [1, 1 + i % 90, 50, 2 + i % 90], 0.9) for i in range(120)]
    doc = contracts.build_ocr_document(
        book_id="book01", page_id="book01_p01", page_no=1,
        image_width=100, image_height=100, lines=lines, elapsed_ms=1, backend="stub",
    )
    assert len(doc["text_blocks"]) == 99          # 截断而不是整页失败
    assert doc["text_blocks"][-1]["order"] == 99


# ---------- 2. 安全值解析 ----------

def test_parse_bool_handles_strings():
    assert parse_bool("false") is False
    assert parse_bool("False") is False
    assert parse_bool("0") is False
    assert parse_bool("") is False
    assert parse_bool("true") is True
    assert parse_bool("1") is True
    assert parse_bool(0) is False
    assert parse_bool(1) is True
    assert parse_bool(None) is False          # 缺失 → 保守
    assert parse_bool("看不懂") is False
    assert parse_bool("看不懂", default=False) is False


def test_parse_safety_is_fail_closed():
    # V1.2.1 P0-1：只认原生布尔 true；"true"/1/"1" 一律不算安全
    assert parse_safety({"pass": True}) == (True, [])
    assert parse_safety({"pass": True, "flags": []}) == (True, [])
    assert parse_safety({"pass": "true"}) == (False, ["safety_pass_not_true"])
    assert parse_safety({"pass": 1}) == (False, ["safety_pass_not_true"])
    assert parse_safety({"pass": "false"})[0] is False
    assert parse_safety({"pass": False, "flags": ["暴力"]})[0] is False
    assert parse_safety({"pass": True, "flags": "暴力"}) == (False, ["safety_flags_not_list"])
    assert parse_safety({"pass": True, "flags": ["  "]}) == (False, ["safety_flag_blank"])

    # 缺失 / null / 未知 / 类型不对 —— 一律判不安全并留原因
    for payload, flag in (
        (None, "safety_missing"),
        ({}, "safety_pass_missing"),
        ({"flags": []}, "safety_pass_missing"),
        ({"pass": None}, "safety_pass_not_true"),
        ({"pass": "maybe"}, "safety_pass_not_true"),
        ({"pass": [1]}, "safety_pass_not_true"),
        ("false", "safety_missing"),
    ):
        passed, flags = parse_safety(payload)
        assert passed is False, payload
        assert flag in flags, (payload, flags)


def test_parse_flags_normalizes():
    assert parse_flags(None) == []
    assert parse_flags("暴力") == ["暴力"]
    assert parse_flags(["a", " b ", ""]) == ["a", "b"]
    assert parse_flags(123) == ["123"]


def test_vlm_parse_treats_false_string_as_false():
    content = (
        '{"description":"画面","objects":[],"scene_tags":[],'
        '"safety":{"pass":"false","flags":"暴力"}}'
    )
    result = QwenVlBackend._parse(content, (100, 100))
    assert result.safety_pass is False
    # 字符串 "false" 不是原生布尔、flags 不是数组，按 V1.2.1 两条都拒绝
    assert result.safety_flags == ["safety_pass_not_true", "safety_flags_not_list"]
    assert result.safety_source == "unavailable"

    doc = contracts.build_vlm_document(
        book_id="book01", page_id="book01_p01", page_no=1,
        image_width=100, image_height=100, description=result.description,
        objects=result.objects, scene_tags=result.scene_tags,
        safety_pass=result.safety_pass, safety_flags=result.safety_flags,
        elapsed_ms=1, backend="vlm",
    )
    assert doc["safety"]["pass"] is False


# ---------- 3. EXIF 方向 ----------

def _save_with_orientation(path: Path, orientation: int, size=(60, 40)) -> None:
    width, height = size
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = ((x * 7) % 256, (y * 11) % 256, ((x + y) * 5) % 256)
    exif = Image.Exif()
    exif[0x0112] = orientation
    image.save(path, exif=exif)
    image.close()


def test_exif_orientation_keeps_raw_coordinates():
    """摆正图里的任意点，映射回原图后必须落在同色像素上。"""
    rng = random.Random(20261107)
    with temp_dir() as root:
        for orientation in range(1, 9):
            path = root / f"p{orientation}.png"
            _save_with_orientation(path, orientation)

            page = preprocess.load_page_image(path)
            assert page.orientation == orientation

            raw = Image.open(path)
            raw.load()
            assert (page.width, page.height) == raw.size  # 契约坐标系 = 文件尺寸
            upright = page.image
            assert upright.size == ((raw.height, raw.width) if orientation >= 5 else raw.size)

            for _ in range(20):
                ux = rng.randrange(2, upright.width - 2)
                uy = rng.randrange(2, upright.height - 2)
                x, y, _, _ = page.to_original_bbox([ux + 0.5, uy + 0.5, ux + 0.6, uy + 0.6])
                rx = min(page.width - 1, max(0, int(x)))
                ry = min(page.height - 1, max(0, int(y)))
                assert raw.getpixel((rx, ry)) == upright.getpixel((ux, uy)), (
                    f"orientation={orientation} 点 ({ux},{uy}) 映射到 ({rx},{ry}) 颜色不符"
                )
            raw.close()


def test_exif_bbox_stays_inside_raw_frame():
    with temp_dir() as root:
        path = root / "p6.png"
        _save_with_orientation(path, 6)
        page = preprocess.load_page_image(path)
        # 摆正图整幅 → 原图整幅
        box = page.to_original_bbox([0, 0, page.image.width, page.image.height])
        assert box == [0, 0, page.width, page.height]


# ---------- 4. OCR / VLM 独立运行 ----------

class _ExplodingVlm:
    name = "explode"

    def available(self):
        return True, ""

    def understand(self, image, ocr_text):
        raise AssertionError("只跑 OCR 时不应调用 VLM")


def test_run_ocr_only_skips_vlm():
    with temp_dir() as root:
        image = root / "p.png"
        Image.new("RGB", (200, 300), "white").save(image)
        result = pipeline.run_page(
            image_path=image, book_id="book01", page_no=1, data_dir=root / "data",
            ocr_backend=StubOcrBackend("测试文本"), vlm_backend=_ExplodingVlm(),
            run_ocr=True, run_vlm=False,
        )
        assert result.ocr is not None and result.ocr["status"] == "ok"
        assert result.vlm is None and result.vlm_path is None
        assert (root / "data" / "json" / "book01_p01_ocr.json").is_file()
        assert not (root / "data" / "json" / "book01_p01_vlm.json").exists()


def test_run_vlm_only_skips_ocr():
    class _Vlm:
        name = "vlm"

        def available(self):
            return True, ""

        def understand(self, image, ocr_text):
            from vision.backends.base import VlmResult

            return VlmResult(description="画面", objects=[], scene_tags=[], safety_pass=True)

    with temp_dir() as root:
        image = root / "p.png"
        Image.new("RGB", (200, 300), "white").save(image)
        result = pipeline.run_page(
            image_path=image, book_id="book02", page_no=1, data_dir=root / "data",
            ocr_backend=StubOcrBackend("不该跑"), vlm_backend=_Vlm(),
            run_ocr=False, run_vlm=True,
        )
        assert result.ocr is None and result.ocr_path is None
        assert result.vlm is not None
        assert not (root / "data" / "json" / "book02_p01_ocr.json").exists()


# ---------- 5. CLI 独立入口（走真实 main，不经 pipeline） ----------

def _patch(module, name, value):
    old = getattr(module, name)
    setattr(module, name, value)
    return old


def test_cli_only_ocr_never_builds_vlm_backend():
    from vision import cli

    def _boom(*args, **kwargs):
        raise AssertionError("--only ocr 不应构造 VLM 后端")

    with temp_dir() as root:
        image = root / "p.png"
        Image.new("RGB", (200, 300), "white").save(image)
        old = _patch(cli, "build_vlm_backend", _boom)
        try:
            code = cli.main([
                "--image", str(image), "--book-id", "book01", "--page-no", "1",
                "--only", "ocr", "--ocr-backend", "stub", "--strict",
                "--data-dir", str(root / "data"),
            ])
        finally:
            _patch(cli, "build_vlm_backend", old)
        assert code == 0
        assert (root / "data" / "json" / "book01_p01_ocr.json").is_file()


def test_cli_only_vlm_never_builds_ocr_backend():
    from vision import cli
    from vision.backends.base import VlmResult

    class _Vlm:
        name = "fake-vlm"

        def available(self):
            return True, ""

        def understand(self, image, ocr_text):
            return VlmResult(description="画面", objects=[], scene_tags=[], safety_pass=True)

    def _boom(*args, **kwargs):
        raise AssertionError("--only vlm 不应构造 OCR 后端")

    with temp_dir() as root:
        image = root / "p.png"
        Image.new("RGB", (200, 300), "white").save(image)
        old_ocr = _patch(cli, "build_ocr_backend", _boom)
        old_vlm = _patch(cli, "build_vlm_backend", lambda *a, **k: _Vlm())
        try:
            code = cli.main([
                "--image", str(image), "--book-id", "book02", "--page-no", "1",
                "--only", "vlm", "--strict", "--data-dir", str(root / "data"),
            ])
        finally:
            _patch(cli, "build_ocr_backend", old_ocr)
            _patch(cli, "build_vlm_backend", old_vlm)
        assert code == 0
        assert (root / "data" / "json" / "book02_p01_vlm.json").is_file()


def test_cli_exits_5_when_vlm_stage_fails():
    from vision import cli

    class _Broken:
        name = "broken"

        def available(self):
            return True, ""

        def understand(self, image, ocr_text):
            raise RuntimeError("模拟 VLM 崩溃")

    with temp_dir() as root:
        image = root / "p.png"
        Image.new("RGB", (200, 300), "white").save(image)
        old = _patch(cli, "build_vlm_backend", lambda *a, **k: _Broken())
        try:
            code = cli.main([
                "--image", str(image), "--book-id", "book03", "--page-no", "1",
                "--only", "vlm", "--strict", "--data-dir", str(root / "data"),
            ])
        finally:
            _patch(cli, "build_vlm_backend", old)
        assert code == 5, "阶段失败必须返回非 0"
        assert not (root / "data" / "json" / "book03_p01_vlm.json").exists()
        assert (root / "data" / "logs" / "book03_p01_vlm.error.json").is_file()
