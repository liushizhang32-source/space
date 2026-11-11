"""M2 单次 Worker（V1.2.1）：一次进程只跑一个 stage，由 M1 Supervisor 拉起。

调用方式（M1 交接文档约定）：

    python -m vision.worker <request.json 绝对路径>

边界（V1.2.1 复核后）：

- 只做一次 OCR 或一次 VLM；不排队、不重试、不做整页超时、不写全局状态机；
- 30 秒硬墙、进程树终止、重试与退避、generation fencing 全归 M1；
- 产物只写 M1 指定的 ``outputs`` 路径：**独立路径、已存在即拒绝**；
- VLM 必须消费 M1 传入的 C1（含 SHA256），不允许在本进程里“顺手再跑一次 OCR”；
- 安全 fail-closed：只有模型响应里的原生 ``"pass": true`` 且无 flag 才放行，
  否则 3004，且不写 C2 / sidecar；
- 3001 只表示 OCR 没识别到文字（本实现用 ``code=0 + 合法空 C1`` 表达）；
- 超量输入（OCR 字数/块数、objects 数量）明确拒绝（1004 + detail），不静默截断。
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import contracts, ids, input_guard, preprocess, refs, safety, validate, writer
from .backends import build_ocr_backend, build_vlm_backend
from .backends.base import OcrBackend, VlmBackend, VlmObject, VlmResult
from .backends.qwen_vl import VlmOutputOverflow
from .pipeline import _is_timeout

PROTOCOL = "m1-vision-worker/0.1"
STAGES = ("ocr", "vlm")

MODULE_ROOT = Path(__file__).resolve().parents[2]
_ENV_PATH_VARS = ("PADDLE_PDX_CACHE_HOME", "PADDLE_OCR_MODEL_DIR")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BAD_REQUEST = 2

ERROR_INPUT_TOO_LARGE = 1004
ERROR_INPUT_UNSUPPORTED = 1006
ERROR_MODEL_CALL = 2001
ERROR_TIMEOUT = 2002
ERROR_CONFIG = 2004
ERROR_SAFETY_BLOCKED = safety.ERROR_SAFETY_BLOCKED  # 3004
ERROR_CONTRACT = 9001

IDENTITY_FIELDS = refs.IDENTITY_FIELDS
_INT_IDENTITY = ("input_revision", "epoch")

# 超量阈值：冻结契约 v1.0 的既有上限，不擅自放大（V1.2.1 P1-7/P1-8）
MAX_OCR_BLOCKS = int(os.getenv("M2_MAX_OCR_BLOCKS", "99"))
MAX_OCR_CHARS = int(os.getenv("M2_MAX_OCR_CHARS", "20000"))


@dataclass
class WorkerOutcome:
    code: int = 0
    msg: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)
    transient: bool = False
    identity: dict[str, Any] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)

    def envelope(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "protocol": PROTOCOL,
            "identity": self.identity,
            "code": self.code,
            "msg": self.msg,
            "artifacts": self.artifacts,
        }
        if self.code != 0:
            payload["transient"] = bool(self.transient)
            if self.detail:
                payload["detail"] = self.detail
        return payload


class RequestError(ValueError):
    """请求不符合 ``m1-vision-worker/0.1``（退出码 2）。"""


class ContractViolation(RuntimeError):
    """产物构造/校验/输入关联失败（9001，不重试）。"""


class LimitExceeded(RuntimeError):
    """超量输入（1004，结构化拒绝，不截断）。"""

    def __init__(self, kind: str, actual: int, limit: int) -> None:
        super().__init__(f"{kind} 超量: {actual} > {limit}")
        self.kind = kind
        self.actual = actual
        self.limit = limit

    def detail(self) -> dict[str, Any]:
        return {"kind": self.kind, "actual": self.actual, "limit": self.limit}


# --------------------------------------------------------------------------
# 路径安全（symlink / junction / 已存在 / 路径碰撞，P0-3 + P1-6）
# --------------------------------------------------------------------------


_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT


def _is_linklike(path: Path) -> bool:
    """符号链接、目录联接（junction）、其它重解析点一律视为 link-like。"""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & _REPARSE_POINT)


def _reject_link_components(root: Path, target: Path, field_name: str) -> None:
    probe = root
    try:
        parts = target.relative_to(root).parts
    except ValueError as exc:
        raise RequestError(f"{field_name} 越出 attempt 目录") from exc
    for part in parts:
        probe = probe / part
        if _is_linklike(probe):
            raise RequestError(f"{field_name} 的路径组件是符号链接/联接点: {part}")


def _resolve_under(
    cwd: Path,
    relative: Any,
    *,
    field_name: str,
    must_not_exist: bool = False,
) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise RequestError(f"{field_name} 必须是非空相对路径")
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.drive:
        raise RequestError(f"{field_name} 必须是相对路径: {relative!r}")
    if ".." in candidate.parts:
        raise RequestError(f"{field_name} 不得包含 '..': {relative!r}")

    root = cwd.resolve()
    _reject_link_components(root, root / candidate, field_name)
    target = (root / candidate).resolve()
    if target != root and root not in target.parents:
        raise RequestError(f"{field_name} 越出 attempt 目录: {relative!r}")
    if must_not_exist and os.path.lexists(target):
        raise RequestError(f"{field_name} 已存在，拒绝覆盖: {relative!r}")
    return target


def _key(path: Path) -> str:
    return os.path.normcase(str(path))


def _outputs_for(
    request: dict[str, Any],
    cwd: Path,
    stage: str,
    result_path: Path,
) -> dict[str, Path]:
    outputs = request.get("outputs")
    if not isinstance(outputs, dict):
        raise RequestError("outputs 必须是对象")
    required = ("c1",) if stage == "ocr" else ("c2", "sidecar")
    resolved: dict[str, Path] = {}
    for key in required:
        if key not in outputs:
            raise RequestError(f"stage={stage} 缺少 outputs.{key}")
        # 先只做路径规范化/越界检查，**不与磁盘状态挂钩**，
        # 这样“产物撞 result.json”能报出准确的碰撞原因而不是“已存在”。
        resolved[key] = _resolve_under(
            cwd,
            outputs[key],
            field_name=f"outputs.{key}",
            must_not_exist=False,
        )

    # 产物之间、产物与 result.json 之间不得同路径（大小写不敏感）
    seen: dict[str, str] = {_key(result_path): "result_path"}
    for key, path in resolved.items():
        token = _key(path)
        if token in seen:
            raise RequestError(f"outputs.{key} 与 {seen[token]} 路径相同，拒绝覆盖")
        seen[token] = f"outputs.{key}"

    # 存在性单独校验：已存在（含符号链接/联接）一律拒绝，避免覆盖 M1 的既有文件
    for key, path in resolved.items():
        if _is_linklike(path):
            raise RequestError(f"outputs.{key} 是符号链接/联接点，拒绝写入")
        if path.exists():
            raise RequestError(f"outputs.{key} 已存在，拒绝覆盖: {path.name!r}")
    return resolved


def _result_path(request: dict[str, Any], cwd: Path) -> Path:
    raw = request.get("result_path", "result.json")
    return _resolve_under(cwd, raw, field_name="result_path")


# --------------------------------------------------------------------------
# 请求解析
# --------------------------------------------------------------------------


def _identity_from(raw: Any) -> dict[str, Any]:
    identity: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return identity
    for key in IDENTITY_FIELDS:
        if key in raw:
            identity[key] = raw[key]
    return identity


def _validate_identity(request: dict[str, Any]) -> dict[str, Any]:
    identity: dict[str, Any] = {}
    for key in IDENTITY_FIELDS:
        if key not in request:
            raise RequestError(f"缺少 identity 字段: {key}")
        value = request[key]
        if key in _INT_IDENTITY:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RequestError(f"{key} 必须是非负整数")
        else:
            if not isinstance(value, str) or not value.strip():
                raise RequestError(f"{key} 必须是非空字符串")
        identity[key] = value
    return identity


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except OSError as exc:
        raise ContractViolation(f"读取失败: {type(exc).__name__}") from exc
    except json.JSONDecodeError as exc:
        raise ContractViolation("不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise ContractViolation("顶层不是 JSON 对象")
    return payload


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular_file(path: Path, *, field_name: str) -> bytes:
    """按已解析路径读文件；拒绝 link-like 与非普通文件。"""
    if _is_linklike(path):
        raise RequestError(f"{field_name} 是符号链接/联接点，拒绝读取")
    try:
        info = path.stat()
    except OSError as exc:
        raise ContractViolation(f"{field_name} 不可读: {type(exc).__name__}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ContractViolation(f"{field_name} 不是普通文件")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ContractViolation(f"{field_name} 读取失败: {type(exc).__name__}") from exc


def _check_image_sha256(request: dict[str, Any], digest: str) -> None:
    inputs = request.get("inputs")
    if not isinstance(inputs, dict):
        raise ContractViolation("VLM stage 必须提供 inputs.c1 / c1_sha256 / image_sha256")
    expected = inputs.get("image_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ContractViolation("inputs.image_sha256 缺失或格式非法（需要 64 位十六进制）")
    if expected.lower() != digest:
        raise ContractViolation("图片 SHA256 与 M1 给出的 image_sha256 不一致")


# --------------------------------------------------------------------------
# 阶段执行
# --------------------------------------------------------------------------


def _prompt_sha256(component_mode: str) -> str:
    if component_mode != "real":
        return refs.sha256_bytes(b"stub")
    from .backends.qwen_vl import SYSTEM_PROMPT, USER_PROMPT

    return refs.sha256_bytes((SYSTEM_PROMPT + "\n" + USER_PROMPT).encode("utf-8"))


def _model_ref(component_mode: str, backend: Any) -> str:
    if component_mode != "real":
        return "stub"
    return os.getenv("QWEN_VL_MODEL") or getattr(backend, "model", "unknown")


def _component_mode(backend: Any) -> str:
    return "stub" if getattr(backend, "name", "") == "stub" else "real"


def _check_ocr_limits(lines: list[Any]) -> None:
    if len(lines) > MAX_OCR_BLOCKS:
        raise LimitExceeded("ocr_blocks", len(lines), MAX_OCR_BLOCKS)
    chars = sum(len(getattr(line, "text", "") or "") for line in lines)
    if chars > MAX_OCR_CHARS:
        raise LimitExceeded("ocr_chars", chars, MAX_OCR_CHARS)


def _classify(exc: BaseException) -> tuple[int, bool, dict[str, Any]]:
    if isinstance(exc, input_guard.InputRejected):
        return exc.code, False, {"kind": "input_rejected", "reason": exc.reason}
    if isinstance(exc, preprocess.ImageLoadError):
        return ERROR_INPUT_UNSUPPORTED, False, {"kind": "image", "reason": str(exc)[:200]}
    return ERROR_CONTRACT, False, {"kind": "contract", "reason": type(exc).__name__}


def _run_ocr_stage(
    *,
    request: dict[str, Any],
    cwd: Path,
    image_path: Path,
    image_bytes: bytes,
    ocr_backend: OcrBackend,
) -> WorkerOutcome:
    out = WorkerOutcome()
    started = time.perf_counter()
    try:
        page = preprocess.load_page_image(image_path, data=image_bytes)
        lines = ocr_backend.recognize(page.image)
        _check_ocr_limits(lines)
        elapsed = int((time.perf_counter() - started) * 1000)
        book_id, page_no = ids.parse_page_id(request["page_id"])
        doc = contracts.build_ocr_document(
            book_id=book_id,
            page_id=request["page_id"],
            page_no=page_no,
            image_width=page.width,
            image_height=page.height,
            lines=lines,
            elapsed_ms=elapsed,
            backend=getattr(ocr_backend, "name", "unknown"),
            to_original=page.to_original_bbox,
        )
        errors = validate.validate_ocr(doc)
        if errors:
            raise ContractViolation(errors[0])

        target = _outputs_for(request, cwd, "ocr", _result_path(request, cwd))["c1"]
        writer.write_json_exclusive(target, doc)
        out.code = 0
        out.msg = "ok"
        out.artifacts = {"c1": str(target.relative_to(cwd.resolve())).replace("\\", "/")}
        if not lines:
            out.detail = {"empty": True}
        return out
    except LimitExceeded as exc:
        out.code = ERROR_INPUT_TOO_LARGE
        out.msg = f"input_limit: {exc.kind} {exc.actual}>{exc.limit}"
        out.detail = exc.detail()
        return out
    except (input_guard.InputRejected, preprocess.ImageLoadError) as exc:
        code, transient, detail = _classify(exc)
        out.code, out.transient, out.detail = code, transient, detail
        out.msg = f"input_rejected: {detail.get('reason', '')}"[:300]
        return out
    except ContractViolation as exc:
        out.code = ERROR_CONTRACT
        out.msg = f"contract_error: {str(exc)[:200]}"
        out.detail = {"kind": "contract", "reason": str(exc)[:200]}
        return out
    except Exception as exc:  # noqa: BLE001 - 统一映射成错误码
        elapsed = int((time.perf_counter() - started) * 1000)
        out.code = ERROR_TIMEOUT if _is_timeout(exc) else ERROR_MODEL_CALL
        out.transient = True
        out.msg = f"ocr_failed: {type(exc).__name__}（{elapsed}ms）"
        out.detail = {"kind": "model", "reason": type(exc).__name__}
        return out


def _ocr_text_from_c1(c1: dict[str, Any]) -> str:
    blocks = c1.get("text_blocks") or []
    return "\n".join(str(block.get("text", "")) for block in blocks)


def _validate_c1_input(
    request: dict[str, Any],
    cwd: Path,
    c1_path: Path,
    page_width: int,
    page_height: int,
) -> tuple[str, dict[str, Any], str]:
    """校验 M1 传入的 C1：page_id、尺寸、SHA256 三重关联。"""
    inputs = request.get("inputs")
    if not isinstance(inputs, dict):
        raise ContractViolation("VLM stage 必须提供 inputs.c1 / c1_sha256 / image_sha256")
    expected_sha = inputs.get("c1_sha256")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise ContractViolation("inputs.c1_sha256 缺失或格式非法（需要 64 位十六进制）")

    raw = _read_regular_file(c1_path, field_name="inputs.c1")
    actual = _sha256(raw)
    if actual.lower() != expected_sha.lower():
        raise ContractViolation("C1 SHA256 不匹配：传入的不是 M1 校验过的那份")
    try:
        c1 = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractViolation("inputs.c1 不是合法 JSON") from exc
    if not isinstance(c1, dict):
        raise ContractViolation("inputs.c1 顶层不是对象")

    if c1.get("page_id") != request["page_id"]:
        raise ContractViolation("C1 的 page_id 与请求不一致（跨页）")
    book_id, page_no = ids.parse_page_id(request["page_id"])
    if c1.get("book_id") not in (None, book_id) or c1.get("page_no") not in (None, page_no):
        raise ContractViolation("C1 的 book_id/page_no 与 page_id 不一致")
    if c1.get("status") not in ("ok", "empty"):
        raise ContractViolation(f"C1 status={c1.get('status')!r} 不可用于 VLM")
    if c1.get("image_width") != page_width or c1.get("image_height") != page_height:
        raise ContractViolation("C1 的图像尺寸与当前图片不一致（旧 revision？）")
    # 返回**原始字节**的 SHA256：sidecar 绑定的必须与 M1 校验的是同一份字节，
    # 不能用重新序列化后的 JSON（键序/空白不同会得到不同哈希）。
    return _ocr_text_from_c1(c1), c1, actual


def _result_from_payload(payload: dict[str, Any]) -> VlmResult:
    objects = [
        VlmObject(
            label=str(item.get("label", "")),
            bbox=[float(v) for v in item.get("bbox", [])],
            confidence=float(item.get("confidence", 0.0) or 0.0),
        )
        for item in payload.get("objects") or []
        if isinstance(item, dict) and len(item.get("bbox") or []) == 4
    ]
    return VlmResult(
        description=str(payload.get("description", "")),
        objects=objects,
        scene_tags=[str(t) for t in payload.get("scene_tags") or []],
        safety_pass=payload.get("safety_pass") is True,
        safety_flags=[str(f) for f in payload.get("safety_flags") or []],
        safety_source=str(payload.get("safety_source", "unavailable")),
        confidence_missing=int(payload.get("confidence_missing", 0) or 0),
    )


def _run_child(argv: list[str], *, cwd: Path, timeout: float) -> tuple[int, str]:
    """跑一个必须能被真正终止的子进程；超时则杀进程树并等待回收。"""
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, (stdout or "") + (stderr or "")
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - 极端情况
            proc.kill()
        raise


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):  # pragma: no cover
            pass
    try:
        proc.kill()
    except OSError:  # pragma: no cover
        pass


def _understand_via_child(
    *,
    request: dict[str, Any],
    cwd: Path,
    image_bytes: bytes,
    ocr_text: str,
    timeout: float,
) -> VlmResult:
    """把 VLM 调用放进独立子进程：M1 杀进程树时能真正终止客户端。"""
    work = Path(tempfile.mkdtemp(prefix=".m2vlm_", dir=str(cwd)))
    image_file = work / "input.bin"
    image_file.write_bytes(image_bytes)
    job = {
        "image_path": str(image_file),
        "ocr_text": ocr_text,
        "out_path": str(work / "out.json"),
        "page_id": request["page_id"],
    }
    job_path = work / "job.json"
    job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    argv = [sys.executable, "-m", "vision.vlm_child", str(job_path)]
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(MODULE_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", ""))
    proc = subprocess.Popen(
        argv,
        cwd=str(work),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
        raise TimeoutError("VLM 子进程超时，已终止并回收")
    out_path = Path(job["out_path"])
    if not out_path.is_file():
        raise RuntimeError(
            f"VLM 子进程未产出结果（exit={proc.returncode}）: {(stderr or '')[-200:]}"
        )
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    if payload.get("ok") is not True:
        raise RuntimeError(f"VLM 子进程失败: {payload.get('reason', 'unknown')}")
    return _result_from_payload(payload)


def _run_vlm_stage(
    *,
    request: dict[str, Any],
    cwd: Path,
    image_path: Path,
    image_bytes: bytes,
    vlm_backend: VlmBackend,
) -> WorkerOutcome:
    out = WorkerOutcome()
    started = time.perf_counter()
    try:
        page = preprocess.load_page_image(image_path, data=image_bytes)
        inputs = request.get("inputs")
        if not isinstance(inputs, dict) or not inputs.get("c1"):
            raise ContractViolation("VLM stage 必须带 M1 提供的 inputs.c1（禁止进程内重跑 OCR）")
        c1_path = _resolve_under(cwd, inputs["c1"], field_name="inputs.c1")
        ocr_text, c1_doc, c1_digest = _validate_c1_input(
            request, cwd, c1_path, page.width, page.height
        )

        mode = "subprocess" if os.getenv("M2_VLM_EXEC", "inproc") == "subprocess" else "inproc"
        if mode == "subprocess":
            timeout = float(os.getenv("QWEN_VL_TIMEOUT", "60"))
            result = _understand_via_child(
                request=request,
                cwd=cwd,
                image_bytes=image_bytes,
                ocr_text=ocr_text,
                timeout=timeout,
            )
        else:
            result = vlm_backend.understand(page.image, ocr_text)
        elapsed = int((time.perf_counter() - started) * 1000)
        if result is None:
            raise ContractViolation("后端返回 None")

        verdict = safety.evaluate_vlm_safety(result)
        if not verdict.passed:
            # 安全拦截：不写 C2 / sidecar，由 M1 判 blocked
            out.code = ERROR_SAFETY_BLOCKED
            out.msg = verdict.message()[:300]
            out.detail = safety.blocked_payload(verdict, page_id=request["page_id"])
            return out

        book_id, page_no = ids.parse_page_id(request["page_id"])
        doc = contracts.build_vlm_document(
            book_id=book_id,
            page_id=request["page_id"],
            page_no=page_no,
            image_width=page.width,
            image_height=page.height,
            description=result.description,
            objects=result.objects,
            scene_tags=result.scene_tags,
            safety_pass=result.safety_pass,
            safety_flags=result.safety_flags,
            elapsed_ms=elapsed,
            backend=getattr(vlm_backend, "name", "unknown"),
            to_original=page.to_original_bbox,
        )
        errors = validate.validate_vlm(doc)
        if errors:
            raise ContractViolation(errors[0])

        result_path = _result_path(request, cwd)
        targets = _outputs_for(request, cwd, "vlm", result_path)
        c2_target = targets["c2"]
        writer.write_json_exclusive(c2_target, doc)
        c2_bytes = c2_target.read_bytes()

        identity = {key: request[key] for key in IDENTITY_FIELDS}
        component_mode = _component_mode(vlm_backend)
        c2_rel = str(c2_target.relative_to(cwd.resolve())).replace("\\", "/")
        sidecar = refs.build_refs(
            identity=identity,
            page_id=request["page_id"],
            c2_doc=doc,
            c2_relative_path=c2_rel,
            c2_bytes=c2_bytes,
            component_mode=component_mode,
            model_ref=_model_ref(component_mode, vlm_backend),
            prompt_sha256=_prompt_sha256(component_mode),
            evidence_ref=c2_rel,
            c1_sha256=c1_digest,
        )
        sidecar_target = targets["sidecar"]
        writer.write_json_exclusive(sidecar_target, sidecar)

        out.code = 0
        out.msg = "ok"
        out.artifacts = {
            "c2": c2_rel,
            "sidecar": str(sidecar_target.relative_to(cwd.resolve())).replace("\\", "/"),
        }
        if result.confidence_missing:
            out.detail = {"confidence_missing": int(result.confidence_missing)}
        return out
    except LimitExceeded as exc:
        out.code = ERROR_INPUT_TOO_LARGE
        out.msg = f"input_limit: {exc.kind} {exc.actual}>{exc.limit}"
        out.detail = exc.detail()
        return out
    except VlmOutputOverflow as exc:
        out.code = ERROR_INPUT_TOO_LARGE
        out.msg = f"model_output_overflow: objects {exc.count}>{exc.limit}"
        out.detail = {"kind": "objects", "actual": exc.count, "limit": exc.limit}
        return out
    except (input_guard.InputRejected, preprocess.ImageLoadError) as exc:
        code, transient, detail = _classify(exc)
        out.code, out.transient, out.detail = code, transient, detail
        out.msg = f"input_rejected: {detail.get('reason', '')}"[:300]
        return out
    except (ContractViolation, ValueError, TypeError, ids.IdError) as exc:
        out.code = ERROR_CONTRACT
        out.msg = f"contract_error: {type(exc).__name__}: {str(exc)[:200]}"
        out.detail = {"kind": "contract", "reason": str(exc)[:200]}
        return out
    except Exception as exc:  # noqa: BLE001
        elapsed = int((time.perf_counter() - started) * 1000)
        out.code = ERROR_TIMEOUT if _is_timeout(exc) else ERROR_MODEL_CALL
        out.transient = True
        out.msg = f"vlm_failed: {type(exc).__name__}（{elapsed}ms）"
        out.detail = {"kind": "model", "reason": type(exc).__name__}
        return out


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


def _build_backend(factory, name: str) -> Any:
    try:
        return factory()
    except Exception as exc:  # noqa: BLE001 - 初始化失败必须结构化返回
        raise ContractViolation(f"{name} 后端初始化失败: {type(exc).__name__}") from exc


def process_request(
    request: dict[str, Any],
    *,
    cwd: Path,
    ocr_backend: OcrBackend | None = None,
    vlm_backend: VlmBackend | None = None,
) -> tuple[dict[str, Any], int]:
    """执行一次请求，返回 ``(result.json 内容, 进程退出码)``。"""
    identity = _identity_from(request)
    try:
        if not isinstance(request, dict):
            raise RequestError("请求必须是 JSON 对象")
        if request.get("protocol") != PROTOCOL:
            raise RequestError(f"protocol 必须是 {PROTOCOL!r}")
        stage = request.get("stage")
        if stage not in STAGES:
            raise RequestError(f"stage 必须是 {STAGES}")
        identity = _validate_identity(request)
        page_id = request.get("page_id")
        if not isinstance(page_id, str) or not page_id.strip():
            raise RequestError("page_id 必须是非空字符串")
        ids.parse_page_id(page_id)
        image_raw = request.get("image_path")
        if not isinstance(image_raw, str) or not image_raw.strip():
            raise RequestError("image_path 必须是非空字符串")
        image_path = Path(image_raw)
        if not image_path.is_absolute():
            raise RequestError("image_path 必须是绝对路径")
        result_path = _result_path(request, cwd)
        _outputs_for(request, cwd, stage, result_path)
    except (RequestError, ids.IdError) as exc:
        outcome = WorkerOutcome(code=ERROR_CONTRACT, msg=f"bad_request: {exc}", identity=identity)
        envelope = outcome.envelope()
        _write_result_best_effort(request, cwd, envelope)
        return envelope, EXIT_BAD_REQUEST

    started = time.perf_counter()
    try:
        image_bytes = _read_regular_file(image_path, field_name="image_path")
        input_guard.guard_image(image_path, data=image_bytes)
    except (input_guard.InputRejected, preprocess.ImageLoadError, ContractViolation) as exc:
        code, transient, detail = _classify(exc)
        if isinstance(exc, ContractViolation):
            code, transient, detail = ERROR_CONTRACT, False, {"kind": "input"}
        outcome = WorkerOutcome(code=code, msg=f"input_rejected: {detail}", identity=identity)
        outcome.transient = transient
        outcome.detail = detail
        outcome.msg += f"（{int((time.perf_counter() - started) * 1000)}ms）"
        return _finish(request, cwd, outcome)

    try:
        if stage == "ocr":
            backend = ocr_backend if ocr_backend is not None else _build_backend(build_ocr_backend, "OCR")
            outcome = _run_ocr_stage(
                request=request,
                cwd=cwd,
                image_path=image_path,
                image_bytes=image_bytes,
                ocr_backend=backend,
            )
        else:
            digest = _sha256(image_bytes)
            try:
                _check_image_sha256(request, digest)
            except ContractViolation as exc:
                outcome = WorkerOutcome(
                    code=ERROR_CONTRACT,
                    msg=f"contract_error: {exc}",
                    identity=identity,
                    detail={"kind": "image_sha256"},
                )
                return _finish(request, cwd, outcome)
            backend = vlm_backend if vlm_backend is not None else _build_backend(build_vlm_backend, "VLM")
            outcome = _run_vlm_stage(
                request=request,
                cwd=cwd,
                image_path=image_path,
                image_bytes=image_bytes,
                vlm_backend=backend,
            )
    except ContractViolation as exc:
        outcome = WorkerOutcome(
            code=ERROR_CONFIG if "初始化失败" in str(exc) else ERROR_CONTRACT,
            msg=f"setup_error: {str(exc)[:200]}",
            identity=identity,
            transient="初始化失败" in str(exc),
            detail={"kind": "backend_init"},
        )

    outcome.identity = identity
    return _finish(request, cwd, outcome)


def _write_result_best_effort(request: Any, cwd: Path, envelope: dict[str, Any]) -> None:
    """best-effort 写 result.json：请求本身非法时也要让 M1 拿到结构化结果。"""
    try:
        if isinstance(request, dict):
            target = _result_path(request, cwd)
        else:
            target = cwd / "result.json"
        _write_result_file(target, envelope)
    except Exception as exc:  # noqa: BLE001 - 只能靠退出码兜底
        print(f"[m2-worker] WARN 无法写 result.json: {type(exc).__name__}", file=sys.stderr)


def _write_result_file(target: Path, envelope: dict[str, Any]) -> None:
    """result.json 是**诊断/握手文件**，允许原子替换（不跟随符号链接）。

    ``os.replace`` 替换的是链接本身，不会写穿到链接目标；
    同目录重复执行时也能安全覆盖上一次的结果。
    """
    writer.write_json_atomic(target, envelope)


def _finish(
    request: dict[str, Any], cwd: Path, outcome: WorkerOutcome
) -> tuple[dict[str, Any], int]:
    envelope = outcome.envelope()
    try:
        _write_result_file(_result_path(request, cwd), envelope)
    except Exception as exc:  # noqa: BLE001 - result 写不出来只能靠退出码
        print(f"[m2-worker] FATAL 无法写 result.json: {type(exc).__name__}", file=sys.stderr)
        return envelope, EXIT_FAILED
    if outcome.code == 0:
        print(f"[m2-worker] stage={request.get('stage')} page={request.get('page_id')} code=0")
        return envelope, EXIT_OK
    print(
        f"[m2-worker] stage={request.get('stage')} page={request.get('page_id')} "
        f"code={outcome.code} transient={outcome.transient}"
    )
    return envelope, EXIT_FAILED


def _normalize_env_paths() -> None:
    """把相对的模型缓存路径锚到模块根，避免随 attempt 的 cwd 漂移。"""
    for name in _ENV_PATH_VARS:
        raw = os.getenv(name)
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            os.environ[name] = str((MODULE_ROOT / path).resolve())
    if not os.getenv("MPLCONFIGDIR"):
        cache = MODULE_ROOT / "models" / ".mplconfig"
        try:
            cache.mkdir(parents=True, exist_ok=True)
            os.environ["MPLCONFIGDIR"] = str(cache)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m vision.worker <request.json>", file=sys.stderr)
        return EXIT_BAD_REQUEST
    request_path = Path(args[0])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[m2-worker] FATAL 请求不可读: {type(exc).__name__}", file=sys.stderr)
        try:
            writer.write_json_atomic(Path.cwd() / "result.json",
                {
                    "protocol": PROTOCOL,
                    "identity": {},
                    "code": ERROR_CONTRACT,
                    "msg": f"bad_request: 请求不可读 {type(exc).__name__}",
                    "artifacts": {},
                    "transient": False,
                },
            )
        except Exception:  # noqa: BLE001
            pass
        return EXIT_BAD_REQUEST
    _normalize_env_paths()
    envelope, code = process_request(request, cwd=Path.cwd())
    return code


if __name__ == "__main__":  # pragma: no cover - 走 main 的路径由集成测试覆盖
    raise SystemExit(main())


