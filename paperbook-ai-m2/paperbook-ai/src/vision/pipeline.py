"""单页视觉流水线：图 → ocr.json / vlm.json。

契约要求（§1.12）：模块间不走 HTTP，只往 ``{DATA_DIR}/json/`` 写文件。

四条铁律（对应三轮验收意见）：
1. **VLM 阶段失败不写 vlm.json**——公共 `VLMData.status` 只有 ok / empty，
   不允许 failed，也不能把失败伪装成 empty。失败走 ``StageError`` +
   ``data/logs/{page_id}_vlm.error.json``。
2. **先校验再发布**——产物先过契约校验，不通过就不落盘。
3. **构造异常也不能中断**——坐标映射/构造/校验出错一律转成阶段错误，
   不能让畸形后端数据把整条流水线掀翻。
4. **成功后必须真的有产物**——后端返回 None 或文件没写成，都算阶段失败。
"""

from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import contracts, ids, preprocess, validate, writer
from .backends.base import OcrBackend, VlmBackend

ERROR_MODEL_CALL = 2001      # 模型调用失败（§1.3）
ERROR_TIMEOUT = 2002         # 超时（§1.3）
ERROR_CONTRACT = 9001        # 构造/校验不通过（内部错误通道）
ERROR_BACKEND_PROTOCOL = 9002  # 后端违反返回协议（如返回 None）


@dataclass(frozen=True)
class StageError:
    stage: str          # "ocr" / "vlm"
    code: int
    message: str
    elapsed_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True)
class VisionResult:
    page_id: str
    ocr: dict[str, Any] | None
    vlm: dict[str, Any] | None
    ocr_path: Path | None
    vlm_path: Path | None
    ocr_errors: list[str] = field(default_factory=list)
    vlm_errors: list[str] = field(default_factory=list)
    ocr_error: StageError | None = None
    vlm_error: StageError | None = None

    @property
    def ok(self) -> bool:
        """真正成功：两个选定的阶段都产出了合规文件且没有阶段错误。"""
        if self.ocr_error is not None or self.vlm_error is not None:
            return False
        if self.ocr_errors or self.vlm_errors:
            return False
        # 有错误日志残留也不影响；但"有阶段但没产物"必须判失败
        return True


def _is_timeout(exc: BaseException) -> bool:
    """沿异常链判断超时：HTTP 客户端常把超时包成 RuntimeError/URLError。"""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, socket.timeout)):
            return True
        if "timeout" in type(current).__name__.lower():
            return True
        reason = getattr(current, "reason", None)  # URLError.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return True
        current = current.__cause__ or current.__context__
    return False


def _safe_message(exc: BaseException) -> str:
    """默认只写异常类型；原文（可能含远端响应/用户文本）要显式开启。"""
    if os.getenv("VISION_LOG_VERBOSE") == "1":
        return f"{type(exc).__name__}: {str(exc)[:300]}".replace("\n", " ")
    return type(exc).__name__


def _stage_error(stage: str, exc: BaseException, elapsed_ms: int) -> StageError:
    code = ERROR_TIMEOUT if _is_timeout(exc) else ERROR_MODEL_CALL
    return StageError(stage, code, _safe_message(exc), elapsed_ms)


def _publish(
    data_dir: Path, page_id: str, kind: str, doc: dict[str, Any]
) -> tuple[dict[str, Any], Path]:
    path = writer.write_json_atomic(writer.json_path(data_dir, page_id, kind), doc)
    return doc, path


def _clear_error_log(data_dir: Path, page_id: str, stage: str) -> None:
    try:
        writer.error_log_path(data_dir, page_id, stage).unlink(missing_ok=True)
    except OSError:
        pass


def _record_failure(
    data_dir: Path, page_id: str, stage: str, error: StageError
) -> None:
    try:
        writer.write_error_log(
            data_dir, page_id, stage, {"page_id": page_id, **error.to_dict()}
        )
    except OSError:
        pass  # 日志写不出来不能反过来影响主流程


def _drop_stale(data_dir: Path, page_id: str, kind: str) -> None:
    try:
        writer.json_path(data_dir, page_id, kind).unlink(missing_ok=True)
    except OSError:
        pass


def run_page(
    *,
    image_path: str | Path,
    book_id: str,
    page_no: int,
    data_dir: str | Path,
    ocr_backend: OcrBackend | None = None,
    vlm_backend: VlmBackend | None = None,
    run_ocr: bool = True,
    run_vlm: bool = True,
) -> VisionResult:
    if run_ocr and ocr_backend is None:
        raise ValueError("run_ocr=True 但没有提供 ocr_backend")
    if run_vlm and vlm_backend is None:
        raise ValueError("run_vlm=True 但没有提供 vlm_backend")

    page_id = ids.make_page_id(book_id, page_no)
    page = preprocess.load_page_image(image_path)
    width, height = page.width, page.height
    to_original = page.to_original_bbox
    data_path = Path(data_dir)

    ocr_doc: dict[str, Any] | None = None
    ocr_path: Path | None = None
    ocr_error: StageError | None = None

    if run_ocr:
        started = time.perf_counter()
        try:
            lines = ocr_backend.recognize(page.image)
        except Exception as exc:  # noqa: BLE001 - 后端异常
            ocr_error = _stage_error("ocr", exc, int((time.perf_counter() - started) * 1000))
        else:
            elapsed = int((time.perf_counter() - started) * 1000)
            try:
                doc = contracts.build_ocr_document(
                    book_id=book_id,
                    page_id=page_id,
                    page_no=page_no,
                    image_width=width,
                    image_height=height,
                    lines=lines,
                    elapsed_ms=elapsed,
                    backend=getattr(ocr_backend, "name", "unknown"),
                    to_original=to_original,
                )
                errors = validate.validate_ocr(doc)
                if errors:
                    raise ValueError(errors[0])
                ocr_doc, ocr_path = _publish(data_path, page_id, writer.OCR_KIND, doc)
            except Exception as exc:  # noqa: BLE001 - 构造/校验异常也不许掀翻流水线
                ocr_error = StageError(
                    "ocr", ERROR_CONTRACT, _safe_message(exc), elapsed
                )

        if ocr_error is not None:
            # OCR 失败仍按 C1 落 status=failed（OCRData 允许），便于中枢降级
            try:
                fallback = contracts.failed_ocr_document(
                    book_id=book_id, page_id=page_id, page_no=page_no,
                    width=width, height=height, elapsed_ms=ocr_error.elapsed_ms,
                    backend=getattr(ocr_backend, "name", "unknown"),
                    code=ocr_error.code, msg=ocr_error.message,
                )
                if not validate.validate_ocr(fallback):
                    ocr_doc, ocr_path = _publish(
                        data_path, page_id, writer.OCR_KIND, fallback
                    )
            except Exception:  # noqa: BLE001 - 连失败契约都写不了就放弃落盘
                ocr_doc, ocr_path = None, None
            _record_failure(data_path, page_id, "ocr", ocr_error)
        else:
            _clear_error_log(data_path, page_id, "ocr")

    vlm_doc: dict[str, Any] | None = None
    vlm_path: Path | None = None
    vlm_error: StageError | None = None

    if run_vlm:
        ocr_text = "\n".join(b["text"] for b in (ocr_doc or {}).get("text_blocks", []))
        started = time.perf_counter()
        try:
            result = vlm_backend.understand(page.image, ocr_text)
        except Exception as exc:  # noqa: BLE001
            vlm_error = _stage_error("vlm", exc, int((time.perf_counter() - started) * 1000))
        else:
            elapsed = int((time.perf_counter() - started) * 1000)
            if result is None:
                # 后端不抛异常但没返回结果：不能当成功（第三轮 R03）
                vlm_error = StageError(
                    "vlm", ERROR_BACKEND_PROTOCOL, "后端返回 None", elapsed
                )
            else:
                try:
                    doc = contracts.build_vlm_document(
                        book_id=book_id,
                        page_id=page_id,
                        page_no=page_no,
                        image_width=width,
                        image_height=height,
                        description=result.description,
                        objects=result.objects,
                        scene_tags=result.scene_tags,
                        safety_pass=result.safety_pass,
                        safety_flags=result.safety_flags,
                        elapsed_ms=elapsed,
                        backend=getattr(vlm_backend, "name", "unknown"),
                        to_original=to_original,
                    )
                    errors = validate.validate_vlm(doc)
                    if errors:
                        raise ValueError(errors[0])
                    vlm_doc, vlm_path = _publish(data_path, page_id, writer.VLM_KIND, doc)
                except Exception as exc:  # noqa: BLE001
                    vlm_error = StageError(
                        "vlm", ERROR_CONTRACT, _safe_message(exc), elapsed
                    )

        # 成功必须有产物，否则也算失败
        if vlm_error is None and (vlm_doc is None or vlm_path is None):
            vlm_error = StageError(
                "vlm", ERROR_CONTRACT, "阶段未产出 vlm.json",
                int((time.perf_counter() - started) * 1000),
            )

        if vlm_error is not None:
            # 失败：先记日志，再清旧文件；日志写失败也要清理
            _record_failure(data_path, page_id, "vlm", vlm_error)
            _drop_stale(data_path, page_id, writer.VLM_KIND)
            vlm_doc, vlm_path = None, None
        else:
            _clear_error_log(data_path, page_id, "vlm")

    return VisionResult(
        page_id=page_id,
        ocr=ocr_doc,
        vlm=vlm_doc,
        ocr_path=ocr_path,
        vlm_path=vlm_path,
        ocr_errors=validate.validate_ocr(ocr_doc) if ocr_doc else [],
        vlm_errors=validate.validate_vlm(vlm_doc) if vlm_doc else [],
        ocr_error=ocr_error,
        vlm_error=vlm_error,
    )
