import json

from _helpers import temp_dir
from PIL import Image, ImageDraw

from vision import pipeline, validate, writer
from vision.backends.stub import StubOcrBackend, StubVlmBackend


def _make_page(path, size: tuple[int, int] = (1200, 1800)):
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([80, 120, 1100, 1100], outline="black", width=6)  # 画面
    draw.rectangle([80, 1300, 1100, 1400], fill="#eeeeee")  # 一行文字区
    image.save(path)
    return path


def test_run_page_writes_both_contract_files():
    with temp_dir() as root:
        page = _make_page(root / "page.png")
        result = pipeline.run_page(
            image_path=page,
            book_id="book01",
            page_no=3,
            data_dir=root / "data",
            ocr_backend=StubOcrBackend("小兔子在森林里"),
            vlm_backend=StubVlmBackend(),
        )
        assert result.page_id == "book01_p03"
        assert result.ocr_path == root / "data" / "json" / "book01_p03_ocr.json"
        assert result.vlm_path == root / "data" / "json" / "book01_p03_vlm.json"
        assert result.ocr_path.is_file() and result.vlm_path.is_file()
        assert result.ok, (result.ocr_errors, result.vlm_errors)
        assert result.ocr["status"] == "ok"
        assert result.vlm["objects"]


def test_output_survives_reload_and_validates():
    with temp_dir() as root:
        page = _make_page(root / "page.png")
        pipeline.run_page(
            image_path=page,
            book_id="book02",
            page_no=1,
            data_dir=root,
            ocr_backend=StubOcrBackend("从前有座山"),
            vlm_backend=StubVlmBackend(),
        )
        ocr = writer.read_json(root / "json" / "book02_p01_ocr.json")
        vlm = writer.read_json(root / "json" / "book02_p01_vlm.json")
        assert validate.validate_ocr(ocr) == []
        assert validate.validate_vlm(vlm) == []
        assert ocr["text_blocks"][0]["block_id"] == "book02_p01_t01"


def test_large_image_bbox_stays_in_original_frame():
    with temp_dir() as root:
        page = _make_page(root / "big.png", size=(2400, 3600))  # 会被缩到工作副本
        result = pipeline.run_page(
            image_path=page,
            book_id="book03",
            page_no=2,
            data_dir=root,
            ocr_backend=StubOcrBackend("大图"),
            vlm_backend=StubVlmBackend(),
        )
        assert result.ocr["image_width"] == 2400
        assert result.ocr["image_height"] == 3600
        assert result.ok, (result.ocr_errors, result.vlm_errors)


class _BrokenOcr:
    name = "broken"

    def available(self):
        return True, ""

    def recognize(self, image):
        raise RuntimeError("模拟 OCR 崩溃")


class _BrokenVlm:
    name = "broken"

    def available(self):
        return True, ""

    def understand(self, image, ocr_text):
        raise RuntimeError("模拟 VLM 超时")


def test_backend_failure_writes_failed_ocr_but_no_vlm_file():
    with temp_dir() as root:
        page = _make_page(root / "page.png")
        result = pipeline.run_page(
            image_path=page,
            book_id="book04",
            page_no=1,
            data_dir=root,
            ocr_backend=_BrokenOcr(),
            vlm_backend=_BrokenVlm(),
        )
        # OCR：C1 允许 failed，照常落盘
        assert result.ocr["status"] == "failed"
        assert "error" not in result.ocr  # 附加字段默认关闭
        assert result.ocr_path.is_file()
        assert result.ocr_error is not None

        # VLM：公共 VLMData 无 failed 枚举，因此**不写文件**
        assert result.vlm is None
        assert result.vlm_path is None
        assert result.vlm_error is not None
        assert not (root / "json" / "book04_p01_vlm.json").exists()

        # 失败详情进日志，不丢
        log = root / "logs" / "book04_p01_vlm.error.json"
        assert log.is_file()
        payload = json.loads(log.read_text(encoding="utf-8"))
        assert payload["stage"] == "vlm" and payload["code"] == 2001

        assert result.ok is False


def test_empty_page_becomes_empty_status():
    with temp_dir() as root:
        page = _make_page(root / "page.png")
        result = pipeline.run_page(
            image_path=page,
            book_id="book05",
            page_no=1,
            data_dir=root,
            ocr_backend=StubOcrBackend(""),
            vlm_backend=StubVlmBackend(),
        )
        assert result.ocr["status"] == "empty"
        assert result.ocr["text_blocks"] == []
        assert result.ok
