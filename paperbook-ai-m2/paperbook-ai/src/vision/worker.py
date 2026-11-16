"""M2 单次 Worker（OFFLINE PROTOCOL V1.0）：一次进程只跑一个 stage。

调用方式（正式协议 FIELD_CONTRACT）：

    [已审核解释器绝对路径, -m vision.worker, <request.json 绝对路径>]

边界（M1/M2 OFFLINE PROTOCOL V1.0，2026-11-13 冻结）：

- 只做一次 OCR 或一次 VLM；不排队、不重试、不做整页超时、不写全局状态机；
- 30 秒硬墙、进程树终止、重试与退避、generation fencing 全归 M1；
- request/result/sidecar 的线格式由 :mod:`vision.protocol` 严格校验：未声明字段、
  原生类型不符、路径不规范一律拒绝（exit 2 / 9001），不静默忽略；
- 产物只写协议规定的三个规范路径：``json/{page}_ocr.json``、
  ``json/{page}_vlm.json``、``json/{page}_refs.json``，已存在即拒绝；
- VLM 必须消费 M1 传入的 C1（绝对路径 + c1_binding 原始字节 SHA256），
  不允许在本进程里“顺手再跑一次 OCR”；
- 安全 fail-closed：只有模型响应里的原生 ``"pass": true`` 且 flags 为空才放行，
  否则 3004，且不写 C2 / sidecar；
- 3001 只表示 OCR 没识别到文字（本实现用 ``code=0 + 合法空 C1`` 表达）；
- 超量输入（OCR 字数/块数、objects 数量）明确拒绝（1004），不静默截断；
- 环境变量只消费 allowlist：``VISION_BACKEND``/``VISION_MODEL``/``VISION_BASE_URL``/
  ``VISION_API_KEY``；离线只允许 ``fixture``/``stub``，``real`` 在本范围禁用。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import (
    backend_task,
    contracts,
    ids,
    input_guard,
    preprocess,
    protocol,
    refs,
    safety,
    validate,
    writer,
)
from .strictjson import StrictJsonError, loads_object as strict_loads_object
from .backends import build_ocr_backend, build_vlm_backend
from .backends.base import OcrBackend, VlmBackend, VlmObject, VlmResult
from .backends.qwen_vl import VlmIncompleteOutput, VlmOutputOverflow, VlmUnsafeOutput
from .pipeline import _is_timeout

PROTOCOL = protocol.PROTOCOL
STAGES = protocol.STAGES

MODULE_ROOT = Path(__file__).resolve().parents[2]

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
# 离线协议不引入未批准的 D02 数值：上限是本地硬常量，超量即拒绝。
MAX_OCR_BLOCKS = 99
MAX_OCR_CHARS = 20000
# 离线参考配置：不读 M2_*/QWEN_VL_*/PADDLE_* 等非 allowlist 变量。
_OFFLINE_BACKENDS = ("fixture", "stub")


@dataclass
class WorkerOutcome:
    code: int = 0
    msg: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)
    transient: bool = False
    identity: dict[str, Any] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)

    def envelope(self) -> dict[str, Any]:
        # WORKER_RESULT_SCHEMA：顶层没有 detail；artifacts 只允许三个协议键。
        artifacts = {
            key: str(value) for key, value in self.artifacts.items() if key in protocol.ARTIFACT_KEYS
        }
        return protocol.build_result(
            identity=self.identity,
            code=self.code,
            msg=self.msg,
            artifacts=artifacts,
            transient=self.transient,
        )


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
    """校验协议规定的三个产物路径，并返回本 stage 真正要写的那些。

    FIELD_CONTRACT 要求两个阶段都声明 c1/c2/sidecar 三键，且路径精确等于
    ``json/{page}_ocr.json`` / ``json/{page}_vlm.json`` / ``json/{page}_refs.json``。
    """
    outputs = request.get("outputs")
    if not isinstance(outputs, dict):
        raise RequestError("outputs 必须是对象")
    if set(outputs) != set(protocol.OUTPUT_KEYS):
        raise RequestError("outputs 必须恰好包含 c1/c2/sidecar 三个键")
    page_id = request.get("page_id")
    if not isinstance(page_id, str) or not page_id:
        raise RequestError("page_id 非法，无法推导规范产物路径")
    expected = protocol.canonical_outputs(page_id)

    resolved: dict[str, Path] = {}
    for key in protocol.OUTPUT_KEYS:
        value = outputs[key]
        if value != expected[key]:
            raise RequestError(f"outputs.{key} 必须是 {expected[key]!r}，收到 {value!r}")
        # 先只做路径规范化/越界检查，**不与磁盘状态挂钩**，
        # 这样“产物撞 result.json”能报出准确的碰撞原因而不是“已存在”。
        resolved[key] = _resolve_under(
            cwd,
            value,
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

    wanted = ("c1",) if stage == "ocr" else ("c2", "sidecar")
    # 存在性单独校验：本 stage 要写的文件已存在（含符号链接/联接）一律拒绝
    for key in wanted:
        path = resolved[key]
        if _is_linklike(path):
            raise RequestError(f"outputs.{key} 是符号链接/联接点，拒绝写入")
        if path.exists():
            raise RequestError(f"outputs.{key} 已存在，拒绝覆盖: {path.name!r}")
    return {key: resolved[key] for key in wanted}


def _result_path(request: dict[str, Any], cwd: Path) -> Path:
    raw = request.get("result_path", "result.json")
    if raw != "result.json":
        raise RequestError('result_path 必须是 "result.json"')
    return _resolve_under(cwd, raw, field_name="result_path")


def _discard(paths: list[Path]) -> None:
    """失败后清理半成品：C2/sidecar 不能留下“看似成功”的残留文件。"""
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


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
    try:
        return protocol.validate_identity(request, field_name="request")
    except protocol.ProtocolRequestError as exc:
        raise RequestError(str(exc)) from exc


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except OSError as exc:
        raise ContractViolation(f"读取失败: {type(exc).__name__}") from exc
    except StrictJsonError as exc:
        raise ContractViolation(f"JSON 结构不可信: {exc.kind}"
                                + (f" ({exc.key})" if exc.key else "")) from exc
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
    """协议 FIELD_CONTRACT：``image_sha256`` 只在请求**顶层**，且必须 hex64。"""
    expected = request.get("image_sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ContractViolation("image_sha256 缺失或格式非法（需要 64 位小写十六进制）")
    if expected != digest:
        raise ContractViolation("图片 SHA256 与 M1 给出的 image_sha256 不一致")
    binding = request.get("c1_binding")
    if isinstance(binding, dict):
        bound = binding.get("image_sha256")
        if isinstance(bound, str) and bound != expected:
            raise ContractViolation("c1_binding.image_sha256 与请求 image_sha256 不一致")


# --------------------------------------------------------------------------
# 阶段执行
# --------------------------------------------------------------------------


def _prompt_sha256(component_mode: str) -> str:
    """PROMPT_HASH_SPEC：对“最终有序消息列表”的规范字节做 SHA256。

    离线 fixture/stub 下 adapter 未被真实调用，但 promopt 列表仍是声明值；
    这里用与真实适配器一致的 system/user 两条消息，键顺序固定 role,content。
    """
    from .backends.qwen_vl import SYSTEM_PROMPT, USER_PROMPT

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT},
    ]
    return protocol.prompt_sha256(messages)


def _model_ref(component_mode: str, backend: Any) -> str:
    """离线不注入真实端点/模型：fixture/stub 用固定引用，不读环境变量。"""
    return "fixture-toy-ocr/1" if component_mode == "fixture" else "stub"


def _component_mode(backend: Any) -> str:
    """协议枚举只有 fixture|stub；real 在本离线范围禁用（不得伪装）。"""
    name = str(getattr(backend, "name", "") or "").lower()
    if name.startswith(("fixture", "fake")):
        return "fixture"
    if name.startswith("stub"):
        return "stub"
    raise ContractViolation(
        f"component_mode={name or 'unknown'!r} 不在离线协议范围（只允许 fixture/stub）"
    )


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
    except contracts.ContractLimitError as exc:
        # 契约层超量不再静默截断：明确 1004，且不写任何产物
        out.code = ERROR_INPUT_TOO_LARGE
        out.msg = f"contract_limit: {exc.kind} {exc.actual}>{exc.limit}"
        out.detail = exc.to_dict()
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


_BINDING_FIELDS = (
    "job_id",
    "page_id",
    "generation_id",
    "input_revision",
    "epoch",
    "attempt_id",
)


_IDENTITY_TYPES = {
    "job_id": str,
    "page_id": str,
    "generation_id": str,
    "input_revision": int,
    "epoch": int,
    "attempt_id": str,
    "fencing_token": str,
}
# OCR 与 VLM attempt 必然不同：只比较共享五元（gate.py:36-38/83-85 同口径）
_SHARED_IDENTITY = ("job_id", "page_id", "generation_id", "input_revision", "epoch")


def _require_identity(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractViolation(f"{label} 必须是对象")
    for key, kind in _IDENTITY_TYPES.items():
        if key not in value:
            raise ContractViolation(f"{label} 缺少字段 {key}")
        item = value[key]
        if kind is int:
            if type(item) is not int or item < 1:
                raise ContractViolation(f"{label}.{key} 必须是正整数（bool 不算）")
        elif type(item) is not str or not item:
            raise ContractViolation(f"{label}.{key} 必须是非空字符串")
    return value


def _m1_native_binding(request: dict[str, Any]) -> bool:
    binding = request.get("c1_binding")
    return isinstance(binding, dict) and isinstance(binding.get("identity"), dict)


def _resolve_c1_path(cwd: Path, raw: Any, *, require_absolute: bool = False) -> Path:
    """M1 基准：``inputs.c1`` 是**绝对路径**（supervisor.py:283 写入 ``str(work/'c1.json')``）。

    旧版相对路径仅作兼容；``require_absolute=True`` 时拒绝相对路径。
    不论哪种形式，都必须是普通文件（拒绝符号链接/联接点/硬链接）。
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ContractViolation("inputs.c1 缺失")
    candidate = Path(raw)
    if require_absolute and not candidate.is_absolute():
        raise ContractViolation("inputs.c1 必须是 M1 分配的绝对路径")
    if not candidate.is_absolute():
        candidate = cwd / candidate
    if _is_linklike(candidate):
        raise ContractViolation("inputs.c1 是符号链接/联接点，拒绝读取")
    resolved = candidate.resolve()
    if not resolved.is_file():
        raise ContractViolation("inputs.c1 不是普通文件")
    try:
        if resolved.stat().st_nlink != 1:
            raise ContractViolation("inputs.c1 是硬链接，拒绝读取")
    except OSError as exc:
        raise ContractViolation(f"inputs.c1 不可读: {type(exc).__name__}") from exc
    return resolved


def _validate_c1_input(
    request: dict[str, Any],
    cwd: Path,
    c1_path: Path,
    page_width: int,
    page_height: int,
) -> tuple[str, dict[str, Any], str]:
    """校验 M1 传入的 C1：嵌套 c1_binding + 原始字节 SHA256 + 页面/尺寸关联。

    协议结构（REQUEST_SCHEMA，两个分支都 additionalProperties=false）::

        inputs     = {"c1": "<绝对路径>"}
        c1_binding = {"identity": {七元}, "sha256": "<C1 原始字节>", "image_sha256": "<图片>"}

    identity 是 **OCR attempt** 的七元；attempt_id/fencing_token 与本次 VLM 不同，
    只比较 job/page/generation/input_revision/epoch（FIELD_CONTRACT 同口径）。
    """
    if not isinstance(request.get("inputs"), dict):
        raise ContractViolation("VLM stage 必须提供 inputs.c1")
    binding = request.get("c1_binding")
    if not isinstance(binding, dict):
        raise ContractViolation("VLM stage 必须提供 c1_binding")
    nested = binding.get("identity")
    if not isinstance(nested, dict):
        raise ContractViolation("c1_binding.identity 缺失")
    try:
        nested_identity = protocol.validate_identity(nested, field_name="c1_binding.identity")
    except protocol.ProtocolRequestError as exc:
        raise ContractViolation(str(exc)) from exc
    for key in protocol.SHARED_IDENTITY_FIELDS:
        if nested_identity[key] != request.get(key):
            raise ContractViolation(f"c1_binding.identity.{key} 与请求 identity 不一致")
    expected_sha = binding.get("sha256")
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ContractViolation("c1_binding.sha256 缺失或格式非法（需要 64 位小写十六进制）")

    raw = _read_regular_file(c1_path, field_name="inputs.c1")
    actual = _sha256(raw)
    if actual != expected_sha:
        raise ContractViolation("C1 SHA256 不匹配：传入的不是 M1 校验过的那份")
    try:
        c1 = strict_loads_object(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractViolation("inputs.c1 不是合法 JSON") from exc

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
    raw_flags = payload.get("safety_flags")
    raw_safety = payload.get("safety_raw")
    return VlmResult(
        description=str(payload.get("description", "")),
        objects=objects,
        scene_tags=[str(t) for t in payload.get("scene_tags") or []],
        safety_pass=payload.get("safety_pass") is True,
        # None ≠ []：模型没给 flags 就必须保持 None，让门禁 fail-closed
        safety_flags=[str(f) for f in raw_flags] if isinstance(raw_flags, list) else None,
        safety_reasons=tuple(str(r) for r in payload.get("safety_reasons") or ()),
        safety_raw=raw_safety if isinstance(raw_safety, dict) else None,
        safety_evidence=str(payload.get("safety_evidence", "")),
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


def _parse_child_payload(text: str) -> dict[str, Any]:
    """严格解析子进程产物：重复键一律拒绝，避免后者覆盖安全字段。"""
    try:
        return strict_loads_object(text)
    except StrictJsonError as exc:
        raise ContractViolation(f"子进程结果结构不可信: {exc.kind}") from exc


def _result_or_raise(payload: dict[str, Any]) -> VlmResult:
    """把子进程 payload 变成结果；安全类失败必须保持 3004 语义。"""
    if payload.get("ok") is not True:
        if payload.get("error_kind") == "VlmUnsafeOutput":
            raise VlmUnsafeOutput(
                str(payload.get("kind") or "duplicate_key"),
                key=str(payload.get("key") or ""),
            )
        raise RuntimeError(f"VLM 子进程失败: {payload.get('reason', 'unknown')}")
    return _result_from_payload(payload)


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
    payload = _parse_child_payload(out_path.read_text(encoding="utf-8"))
    return _result_or_raise(payload)


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
        c1_path = _resolve_c1_path(
            cwd, inputs["c1"], require_absolute=_m1_native_binding(request)
        )
        ocr_text, c1_doc, c1_digest = _validate_c1_input(
            request, cwd, c1_path, page.width, page.height
        )

        # 离线协议只允许进程内适配器（fixture/stub），子进程/外部取消属未部署能力。
        mode = "inproc"
        # 每次模型调用登记一个 backend_task_id：与 job/generation/attempt 绑定，
        # 取消是否成功、有无终止确认全部落盘（候选能力，离线不宣称真实终止）。
        task = backend_task.new_task(
            backend=getattr(vlm_backend, "name", "unknown"),
            model="offline",
            endpoint="",
            job_id=str(request.get("job_id", "")),
            page_id=str(request.get("page_id", "")),
            generation_id=str(request.get("generation_id", "")),
            attempt_id=str(request.get("attempt_id", "")),
            fencing_token=str(request.get("fencing_token", "")),
        )
        task_path = cwd / "backend_task.json"
        try:
            if mode == "subprocess":
                timeout = 60.0
                try:
                    result = _understand_via_child(
                        request=request,
                        cwd=cwd,
                        image_bytes=image_bytes,
                        ocr_text=ocr_text,
                        timeout=timeout,
                    )
                except Exception:
                    # 子进程被杀后，服务端是否停止计算并不由我们决定：
                    # 离线参考配置没有取消接口，如实记 connection_close + 未确认。
                    backend_task.cancel(task, url_template="")
                    raise
            else:
                result = vlm_backend.understand(page.image, ocr_text)
            backend_task.finish(task)
        finally:
            backend_task.write_record(task_path, task)
        elapsed = int((time.perf_counter() - started) * 1000)
        if result is None:
            raise ContractViolation("后端返回 None")

        result_path = _result_path(request, cwd)
        targets = _outputs_for(request, cwd, "vlm", result_path)
        c2_target = targets["c2"]
        sidecar_target = targets["sidecar"]
        c2_rel = str(c2_target.relative_to(cwd.resolve())).replace("\\", "/")
        canonical_c2 = f"json/{request['page_id']}_vlm.json"
        if c2_rel != canonical_c2:
            # M1 Gate（gate.py:109-113）只接受这个相对路径；不一致时提前失败，
            # 不产出下游必然拒收的 sidecar。
            raise ContractViolation(
                f"outputs.c2 必须是 {canonical_c2}（M1 Gate 约定），收到 {c2_rel}"
            )

        verdict = safety.evaluate_vlm_safety(result)
        if not verdict.passed:
            # 安全拦截：不写 C2 / sidecar；同时清掉同目录里可能残留的旧产物，
            # 避免下游把上一轮的“成功文件”当成本次结果（V1.2.4 P0-1 第 5 条）。
            _discard([c2_target, sidecar_target])
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
            safety_flags=list(result.safety_flags or ()),
            elapsed_ms=elapsed,
            backend=getattr(vlm_backend, "name", "unknown"),
            to_original=page.to_original_bbox,
        )
        errors = validate.validate_vlm(doc)
        if errors:
            raise ContractViolation(errors[0])
        if doc["status"] == "ok" and not doc["objects"] and not doc["description"].strip():
            raise ContractViolation("VLM 产物既无物体也无描述，不接受为成功")

        identity = {key: request[key] for key in IDENTITY_FIELDS}
        component_mode = _component_mode(vlm_backend)

        try:
            writer.write_json_exclusive(c2_target, doc)
            c2_bytes = c2_target.read_bytes()
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
            )
            writer.write_json_exclusive(sidecar_target, sidecar)
            sidecar_rel = str(sidecar_target.relative_to(cwd.resolve())).replace("\\", "/")
        except BaseException:
            # 部分写入（例如 C2 成功、sidecar 失败）不能留下半套产物
            _discard([c2_target, sidecar_target])
            raise

        out.code = 0
        out.msg = "ok"
        out.artifacts = {"c2": c2_rel, "sidecar": sidecar_rel}
        if result.confidence_missing:
            out.detail = {"confidence_missing": int(result.confidence_missing)}
        return out
    except contracts.ContractLimitError as exc:
        # 契约层超量不再静默截断：明确 1004，且不写任何产物
        out.code = ERROR_INPUT_TOO_LARGE
        out.msg = f"contract_limit: {exc.kind} {exc.actual}>{exc.limit}"
        out.detail = exc.to_dict()
        return out
    except LimitExceeded as exc:
        out.code = ERROR_INPUT_TOO_LARGE
        out.msg = f"input_limit: {exc.kind} {exc.actual}>{exc.limit}"
        out.detail = exc.detail()
        return out
    except VlmUnsafeOutput as exc:
        # 重复键/非有限数字：安全数据可能已被覆盖，直接按安全拦截处理
        out.code = ERROR_SAFETY_BLOCKED
        out.msg = f"safety_blocked:model_output_{exc.kind}"[:300]
        out.detail = {"kind": exc.kind, "key": exc.key, "stage": "vlm"}
        return out
    except VlmIncompleteOutput as exc:
        # 截断/半截 JSON 不再“修复成成功”：按模型调用失败处理，产物一律不写
        out.code = ERROR_MODEL_CALL
        out.transient = True
        out.msg = "model_output_incomplete"[:300]
        out.detail = {"kind": "incomplete", "reason": str(exc)[:200]}
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


def _offline_backend_name() -> str:
    """环境 allowlist：只读 ``VISION_BACKEND``，离线只允许 fixture/stub。"""
    name = (os.getenv("VISION_BACKEND") or "stub").strip().lower()
    if name not in _OFFLINE_BACKENDS:
        raise ContractViolation(
            f"VISION_BACKEND={name!r} 不在离线协议范围（只允许 fixture/stub）"
        )
    return name


class _FixtureProxy:
    """给 stub 适配器贴上 fixture 名字：只用于离线夹具，不伪装真实模型。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.name = "fixture"

    def __getattr__(self, item: str) -> Any:  # pragma: no cover - 透传
        return getattr(self._inner, item)


def _build_offline_backends() -> tuple[Any, Any]:
    name = _offline_backend_name()
    return build_ocr_backend(name), build_vlm_backend(name)


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
        spec = protocol.validate_request(request)
        stage = spec["stage"]
        identity = spec["identity"]
        page_id = spec["page_id"]
        ids.parse_page_id(page_id)
        image_path = Path(spec["image_path"])
        result_path = _result_path(request, cwd)
        _outputs_for(request, cwd, stage, result_path)
    except (protocol.ProtocolRequestError, RequestError, ids.IdError) as exc:
        # 协议 F02：请求结构不可信时无法构造合法 identity，写 result.json 反而会
        # 产出一个违反冻结 Result Schema 的“伪结果”。这里只返回诊断信息并退出 2。
        envelope = {
            "protocol": PROTOCOL,
            "code": ERROR_CONTRACT,
            "msg": f"bad_request: {exc}"[:300],
            "artifacts": {},
            "transient": False,
        }
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
            backend = ocr_backend if ocr_backend is not None else _build_offline_backends()[0]
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
            backend = vlm_backend if vlm_backend is not None else _build_offline_backends()[1]
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
    """离线协议不使用模型缓存环境变量；保留空实现以显式声明“不读非 allowlist 变量”。"""
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m vision.worker <request.json>", file=sys.stderr)
        return EXIT_BAD_REQUEST
    request_path = Path(args[0])
    try:
        request = strict_loads_object(request_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        # 请求本身不可读：M1 会按“缺 result / envelope 非法”处理（1002），
        # M2 不伪造一个 identity 不合法的 result。
        print(f"[m2-worker] FATAL 请求不可读: {type(exc).__name__}", file=sys.stderr)
        return EXIT_BAD_REQUEST
    _normalize_env_paths()
    envelope, code = process_request(request, cwd=Path.cwd())
    return code


if __name__ == "__main__":  # pragma: no cover - 走 main 的路径由集成测试覆盖
    raise SystemExit(main())



