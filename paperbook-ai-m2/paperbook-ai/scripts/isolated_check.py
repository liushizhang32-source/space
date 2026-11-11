"""隔离自检：不联网、不调模型，只验证核心逻辑与契约。

    python scripts/isolated_check.py
    python scripts/isolated_check.py --keep     # 保留临时目录便于排查

设计前提（对应第四轮审查建议）：
- 临时 DATA_DIR，不碰正式 data/；
- 只用 stub / 假后端，**默认禁网**（不发任何 HTTP）；
- 关闭 verbose（`VISION_LOG_VERBOSE` 强制清零），日志不含原文；
- 同页串行执行，不测试并发。

退出码：0 全部通过；1 有失败项或结果输出失败；2 清理本次临时目录失败
（详见 stderr 与 data/_isolated_cleanup.log）。原始业务异常的优先级最高，
清理/输出故障只写日志，不会替换它。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TEMP_ROOT = ROOT / "data"
CLEANUP_LOG = TEMP_ROOT / "_isolated_cleanup.log"
_TEMP_NAME = re.compile(r"^_isolated_[0-9a-f]{8}$")

# 先禁用网络相关开关与 verbose，再 import 视觉模块
os.environ.pop("VISION_LOG_VERBOSE", None)
os.environ.pop("QWEN_VL_BASE_URL", None)

from PIL import Image, ImageDraw  # noqa: E402

from vision import contracts, pipeline, validate  # noqa: E402
from vision.backends.base import OcrLine, VlmObject, VlmResult  # noqa: E402
from vision.backends.qwen_vl import QwenVlBackend, parse_safety  # noqa: E402
from vision.backends.stub import StubOcrBackend, StubVlmBackend  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str):
    def wrapper(fn):
        try:
            detail = fn() or ""
            RESULTS.append((name, True, detail))
        except Exception as exc:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(exc).__name__}: {exc}"[:160]))
        return fn

    return wrapper


def _image(path: Path, size=(600, 800)) -> Path:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([50, 50, size[0] - 50, size[1] // 2], outline="black", width=3)
    try:
        draw.text((60, size[1] - 120), "sample page", fill="black")  # 只用 ASCII，避免 CI 缺中文字体
    except Exception:  # noqa: BLE001 - 画字失败不影响几何断言
        pass
    image.save(path)
    return path


class _BrokenOcr:
    name = "broken-ocr"

    def available(self):
        return True, ""

    def recognize(self, image):
        raise RuntimeError("模拟 OCR 崩溃")


class _BrokenVlm:
    name = "broken-vlm"

    def available(self):
        return True, ""

    def understand(self, image, ocr_text):
        raise TimeoutError("模拟超时")


class _NoneVlm:
    name = "none-vlm"

    def available(self):
        return True, ""

    def understand(self, image, ocr_text):
        return None


class _MalformedOcr:
    name = "malformed-ocr"

    def available(self):
        return True, ""

    def recognize(self, image):
        return [
            OcrLine("正常", [10, 10, 100, 50], 0.9),
            OcrLine("短框", [10, 10, 100], 0.9),
            OcrLine("无穷", [float("inf"), 0, 10, 10], 0.9),
            OcrLine(123, [20, 20, 80, 60], 0.8),
        ]


def run(data: Path) -> None:
    page = _image(data / "page.png")

    @check("01 正常页产出 ocr.json + vlm.json")
    def _normal():
        result = pipeline.run_page(
            image_path=page, book_id="isobook1", page_no=1, data_dir=data,
            ocr_backend=StubOcrBackend("小兔子出门了"), vlm_backend=StubVlmBackend(),
        )
        assert result.ok, (result.ocr_error, result.vlm_error)
        assert set(result.ocr) == {
            "schema_version", "book_id", "page_id", "page_no", "status",
            "image_width", "image_height", "text_blocks", "page_confidence", "elapsed_ms",
        }
        assert result.vlm["status"] in ("ok", "empty")
        assert validate.validate_ocr(result.ocr) == []
        assert validate.validate_vlm(result.vlm) == []
        return f"ocr={result.ocr['status']} vlm={result.vlm['status']}"

    @check("02 stub 的 safety 必须是 false（打桩≠已审查）")
    def _stub_safety():
        result = pipeline.run_page(
            image_path=page, book_id="isobook2", page_no=1, data_dir=data,
            ocr_backend=None, vlm_backend=StubVlmBackend(), run_ocr=False,
        )
        assert result.vlm["safety"]["pass"] is False
        assert "stub_mock" in result.vlm["safety"]["flags"]
        return "safety=false + stub_mock"

    @check("03 无字页 → ocr empty 且 page_confidence=0")
    def _empty():
        result = pipeline.run_page(
            image_path=page, book_id="isobook3", page_no=1, data_dir=data,
            ocr_backend=StubOcrBackend(""), vlm_backend=StubVlmBackend(),
        )
        assert result.ocr["status"] == "empty"
        assert result.ocr["page_confidence"] == 0
        return "empty/0"

    @check("04 OCR 崩溃 → failed 文件 + 错误日志")
    def _ocr_fail():
        result = pipeline.run_page(
            image_path=page, book_id="isobook4", page_no=1, data_dir=data,
            ocr_backend=_BrokenOcr(), vlm_backend=StubVlmBackend(),
        )
        assert result.ocr["status"] == "failed"
        assert result.ocr_error is not None
        assert (data / "logs" / "isobook4_p01_ocr.error.json").is_file()
        return f"code={result.ocr_error.code}"

    @check("05 VLM 崩溃 → 不产出 vlm.json + 日志")
    def _vlm_fail():
        result = pipeline.run_page(
            image_path=page, book_id="isobook5", page_no=1, data_dir=data,
            ocr_backend=None, vlm_backend=_BrokenVlm(), run_ocr=False,
        )
        assert result.vlm is None and result.vlm_error is not None
        assert not (data / "json" / "isobook5_p01_vlm.json").exists()
        assert (data / "logs" / "isobook5_p01_vlm.error.json").is_file()
        # 超时必须映射成 2002（异常链判定）
        assert result.vlm_error.code == 2002, result.vlm_error
        return f"code={result.vlm_error.code}"

    @check("06 VLM 返回 None → 9002，不算成功")
    def _vlm_none():
        result = pipeline.run_page(
            image_path=page, book_id="isobook6", page_no=1, data_dir=data,
            ocr_backend=None, vlm_backend=_NoneVlm(), run_ocr=False,
        )
        assert result.vlm is None and result.vlm_error.code == 9002
        assert result.ok is False
        return "code=9002"

    @check("07 畸形 OCR 数据不中断流水线")
    def _malformed():
        result = pipeline.run_page(
            image_path=page, book_id="isobook7", page_no=1, data_dir=data,
            ocr_backend=_MalformedOcr(), vlm_backend=None, run_ocr=True, run_vlm=False,
        )
        assert result.ocr is not None and result.ocr_error is None
        texts = [b["text"] for b in result.ocr["text_blocks"]]
        assert "正常" in texts and "123" in texts
        assert "短框" not in texts and "无穷" not in texts
        return f"blocks={len(texts)}"

    @check("08 EXIF=6 图片：image_width 是文件尺寸")
    def _exif():
        src = Image.open(page).convert("RGB")
        raw = src.rotate(90, expand=True)
        exif = Image.Exif()
        exif[0x0112] = 6
        rotated = data / "rotated.jpg"
        raw.save(rotated, quality=95, exif=exif)

        result = pipeline.run_page(
            image_path=rotated, book_id="isobook8", page_no=1, data_dir=data,
            ocr_backend=StubOcrBackend("旋转页"), vlm_backend=None,
            run_ocr=True, run_vlm=False,
        )
        assert (result.ocr["image_width"], result.ocr["image_height"]) == raw.size
        for block in result.ocr["text_blocks"]:
            x1, y1, x2, y2 = block["bbox"]
            assert 0 <= x1 < x2 <= raw.size[0] and 0 <= y1 < y2 <= raw.size[1]
        return f"{raw.size[0]}x{raw.size[1]}"

    @check("09 safety 缺失/未知 → 判不安全")
    def _safety():
        assert parse_safety(None) == (False, ["safety_missing"])
        passed, flags = parse_safety({"pass": "maybe"})
        assert passed is False and "safety_unparsed" in flags
        content = '{"description":"x","objects":[],"scene_tags":[],"safety":{"pass":"false"}}'
        assert QwenVlBackend._parse(content, (100, 100)).safety_pass is False
        return "fail-closed"

    @check("10 超过 99 块 → 截断而不是整页失败")
    def _cap():
        lines = [OcrLine(f"行{i}", [1, 1 + i % 50, 60, 2 + i % 50], 0.9) for i in range(120)]
        doc = contracts.build_ocr_document(
            book_id="isobook9", page_id="isobook9_p01", page_no=1,
            image_width=100, image_height=100, lines=lines, elapsed_ms=1, backend="stub",
        )
        assert len(doc["text_blocks"]) == 99
        return "99"

    @check("11 省略 safety 参数 → 构造即报错")
    def _explicit_safety():
        try:
            contracts.build_vlm_document(
                book_id="isobook1", page_id="isobook1_p01", page_no=1,
                image_width=100, image_height=100, description="x",
            )
        except TypeError:
            return "TypeError"
        raise AssertionError("省略 safety_pass 必须报错")

    @check("12 目录里没有残留的 vlm.json 失败文件")
    def _no_failed_vlm():
        for path in (data / "json").glob("*_vlm.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            assert doc["status"] in ("ok", "empty"), f"{path.name} status={doc['status']}"
        return "ok/empty only"

    @check("13 HTTP 超时包装链 → 错误码 2002")
    def _http_timeout():
        import socket
        import urllib.error

        from vision.backends import qwen_vl

        backend = qwen_vl.QwenVlBackend(base_url="http://127.0.0.1:9/v1", model="m", timeout=1)
        original = qwen_vl.urllib.request.urlopen

        def _raise(*args, **kwargs):
            raise urllib.error.URLError(socket.timeout("timed out"))

        qwen_vl.urllib.request.urlopen = _raise
        try:
            try:
                backend._post({"messages": []})
            except qwen_vl.VlmTimeout as exc:
                error = pipeline._stage_error("vlm", exc, 1)
                assert error.code == 2002, error
                return "URLError(timeout) → 2002"
            raise AssertionError("应抛 VlmTimeout")
        finally:
            qwen_vl.urllib.request.urlopen = original


def _make_workdirs(data: Path) -> None:
    """初始化第一步：在本次临时目录内建出产物子目录。"""
    (data / "json").mkdir(parents=True, exist_ok=True)
    (data / "logs").mkdir(parents=True, exist_ok=True)


def _preflight(data: Path) -> None:
    """初始化第二步：确认目录可写（写一个探针再删掉，不留残留）。"""
    probe = data / ".write_probe"
    probe.write_bytes(b"ok")
    probe.unlink()


def _assert_owned(data: Path) -> None:
    """只允许清理本次运行的临时目录，越界一律拒绝。"""
    if not _TEMP_NAME.match(data.name):
        raise RuntimeError(f"拒绝清理：目录名不是本次运行的临时目录（{data.name}）")
    if data.resolve().parent != TEMP_ROOT.resolve():
        raise RuntimeError(f"拒绝清理：目录不在临时根目录下（{data}）")


def _safe_stderr(text: str) -> None:
    """向 stderr 写一行；写不出去就静默放弃。

    stderr 本身可能损坏（编码错误、BrokenPipe、被替换的流），
    日志通路绝不能成为新的异常来源，更不能覆盖调用方的原始异常。
    """
    try:
        print(text, file=sys.stderr, flush=True)
    except BaseException:  # noqa: BLE001 - 日志通路失败不得传播
        pass


def _log_failure(tag: str, data: Path, exc: BaseException) -> None:
    """记录清理/报告失败。两条通路各自保护，任何一条失败都不影响另一条。"""
    line = (
        f"[{tag}] {datetime.now().isoformat(timespec='seconds')} "
        f"{data} {type(exc).__name__}: {exc}"
    )
    _safe_stderr(line)
    try:
        CLEANUP_LOG.parent.mkdir(parents=True, exist_ok=True)
        with CLEANUP_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except BaseException as log_exc:  # noqa: BLE001 - 落盘失败只降级为 stderr
        _safe_stderr(f"[{tag}] 日志写入失败：{type(log_exc).__name__}: {log_exc}")


def _cleanup(data: Path, *, keep: bool = False) -> bool:
    """清理本次临时目录。绝不抛异常，绝不掩盖调用方的业务异常。"""
    try:
        if keep:
            try:
                print(f"已保留：{data}")
            except BaseException:  # noqa: BLE001 - 输出通路失败不影响保留语义
                pass
            return True
        if not data.exists():
            return True
        _assert_owned(data)
        shutil.rmtree(data)
    except Exception as exc:  # noqa: BLE001 - 清理失败只记录，不改变原始异常
        _log_failure("CLEANUP-FAIL", data, exc)
        return False
    return True


def _safe_report() -> BaseException | None:
    """输出结果，返回报告失败的原因（正常时返回 None）。绝不抛异常。"""
    try:
        _report()
    except BaseException as exc:  # noqa: BLE001 - 报告失败不得阻断清理
        return exc
    return None


def _report() -> None:
    failures = [name for name, ok, _ in RESULTS if not ok]
    for name, ok, detail in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    print("-" * 66)
    print(f"{len(RESULTS) - len(failures)}/{len(RESULTS)} 通过")
    if failures:
        print("失败项：" + "、".join(failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="隔离自检（无网、无模型）")
    parser.add_argument("--keep", action="store_true", help="保留临时目录")
    args = parser.parse_args(argv)

    data = TEMP_ROOT / f"_isolated_{uuid.uuid4().hex[:8]}"
    created = False
    cleanup_ok = True
    error: BaseException | None = None
    report_error: BaseException | None = None

    try:
        data.mkdir(parents=True)
        created = True

        print("=" * 66)
        print("视觉模块 · 隔离自检（无网络 / 无模型 / 临时目录）")
        print(f"临时目录：{data}")
        print("=" * 66)

        _make_workdirs(data)
        _preflight(data)
        run(data)
    except BaseException as exc:  # noqa: BLE001 - 先记下，清理后再按原样抛出
        error = exc
    finally:
        # 1) 先做资源释放：只依赖文件系统，不依赖任何输出通路，
        #    因此报告打印失败、stdout 损坏都不会阻断下面这行。
        if created:
            cleanup_ok = _cleanup(data, keep=args.keep)
        # 2) 再输出结果：失败只记录，既不阻断清理，也不顶替原始异常。
        report_error = _safe_report()
        if report_error is not None:
            _log_failure("REPORT-FAIL", data, report_error)

    # 3) 原始业务异常优先级最高：清理/报告故障都只留在日志里。
    if error is not None:
        raise error
    if not cleanup_ok:
        return 2
    if report_error is not None:
        return 1
    return 1 if any(not ok for _, ok, _ in RESULTS) else 0


if __name__ == "__main__":
    raise SystemExit(main())
