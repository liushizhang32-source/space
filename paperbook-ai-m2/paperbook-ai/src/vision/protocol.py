"""M1/M2 OFFLINE PROTOCOL V1.0 的线格式校验（冻结版，2026-11-13）。

本模块只做**协议层**的两件事：

1. 严格校验 M1 下发的 ``request.json``（REQUEST_SCHEMA + FIELD_CONTRACT）；
2. 构造/校验 M2 回报的 ``result.json``（WORKER_RESULT_SCHEMA）。

线格式细节来自协议包
``M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113/``：

- ``REQUEST_SCHEMA.json`` / ``WORKER_RESULT_SCHEMA.json`` / ``SIDECAR_SCHEMA.json``
- ``FINAL_ACCEPTANCE_REPORT.md``（FROZEN / OWNER_APPROVED）
- ``PROMPT_HASH_SPEC.md``

设计约束（对应协议 FIELD_CONTRACT）：

- **未声明字段是 unknown，不是 optional**：多一个键就拒绝，不能静默忽略；
- 所有 ``oneOf`` 分支用 ``additionalProperties: false``，这里逐个键白名单；
- 类型必须是原生类型：``bool`` 不能当 ``int``，``1.0`` 不能当 ``integer``；
- 错误只返回**结构化原因**，不把内部细节写进 result（result 顶层没有 ``detail``）。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

PROTOCOL = "m1-vision-worker/0.1"
RESULT_PROTOCOL = "m1-vision-worker/0.1"
SIDECAR_SCHEMA_VERSION = "vision_refs/0.1"
C2_SCHEMA_VERSION = "1.0"

STAGES = ("ocr", "vlm")
IDENTITY_FIELDS = (
    "job_id",
    "page_id",
    "generation_id",
    "input_revision",
    "epoch",
    "attempt_id",
    "fencing_token",
)
# 协议 FIELD_CONTRACT：M1 只比较这五个共享身份字段；attempt_id/fencing_token
# 在 OCR 与 VLM 两次 attempt 之间**可以不同**（F03）。
SHARED_IDENTITY_FIELDS = ("job_id", "page_id", "generation_id", "input_revision", "epoch")
INT_IDENTITY_FIELDS = ("input_revision", "epoch")

OUTPUT_KEYS = ("c1", "c2", "sidecar")
ARTIFACT_KEYS = ("c1", "c2", "sidecar")
RESULT_KEYS = ("protocol", "identity", "code", "msg", "artifacts", "transient")
REQUEST_COMMON_KEYS = (
    "protocol",
    "job_id",
    "page_id",
    "generation_id",
    "input_revision",
    "epoch",
    "attempt_id",
    "fencing_token",
    "stage",
    "image_path",
    "image_sha256",
    "result_path",
    "outputs",
)
REQUEST_VLM_KEYS = REQUEST_COMMON_KEYS + ("inputs", "c1_binding")

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_PAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ProtocolRequestError(ValueError):
    """请求不符合冻结协议（M1 侧应当拒绝该 attempt）。"""


def canonical_outputs(page_id: str) -> dict[str, str]:
    """协议 FIELD_CONTRACT 规定的三个产物路径（相对 attempt 根）。"""
    return {
        "c1": f"json/{page_id}_ocr.json",
        "c2": f"json/{page_id}_vlm.json",
        "sidecar": f"json/{page_id}_refs.json",
    }


def _fail(message: str) -> None:
    raise ProtocolRequestError(message)


def _require_exact_keys(payload: Any, allowed: tuple[str, ...], *, field_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        _fail(f"{field_name} 必须是 JSON 对象")
    extra = [key for key in payload if key not in allowed]
    if extra:
        _fail(f"{field_name} 含未声明字段: {sorted(extra)}")
    missing = [key for key in allowed if key not in payload]
    if missing:
        _fail(f"{field_name} 缺失必需字段: {sorted(missing)}")
    return payload


def _require_string(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail(f"{field_name} 必须是字符串")
    if not allow_empty and value == "":
        _fail(f"{field_name} 不能是空字符串")
    return value


def _require_int(value: Any, field_name: str, *, minimum: int = 1) -> int:
    # 原生 int 才接受：bool 是 int 子类，1.0 是 float，都必须拒绝。
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{field_name} 必须是原生整数")
    if value < minimum:
        _fail(f"{field_name} 必须 >= {minimum}")
    return value


def _require_hex64(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        _fail(f"{field_name} 必须是 64 位小写十六进制 SHA256")
    return value


def validate_identity(payload: Any, *, field_name: str = "identity") -> dict[str, Any]:
    """校验七元身份：原生 str/int、非空、revision/epoch >= 1。"""
    _require_exact_keys(payload, IDENTITY_FIELDS, field_name=field_name)
    identity: dict[str, Any] = {}
    for key in IDENTITY_FIELDS:
        value = payload[key]
        if key in INT_IDENTITY_FIELDS:
            identity[key] = _require_int(value, f"{field_name}.{key}")
        else:
            identity[key] = _require_string(value, f"{field_name}.{key}")
    return identity


def validate_request(request: Any) -> dict[str, Any]:
    """严格校验并规范化一次 Worker 请求。

    返回值的 ``outputs`` 只含本 stage 真正要写的键，但校验时要求三个键齐全。
    """
    if not isinstance(request, dict):
        _fail("请求必须是 JSON 对象")
    stage = request.get("stage")
    if stage not in STAGES:
        _fail(f"stage 必须是 {STAGES} 之一")
    allowed = REQUEST_VLM_KEYS if stage == "vlm" else REQUEST_COMMON_KEYS
    _require_exact_keys(request, allowed, field_name="request")

    if request.get("protocol") != PROTOCOL:
        _fail(f"protocol 必须是 {PROTOCOL!r}")
    missing = [key for key in IDENTITY_FIELDS if key not in request]
    if missing:
        _fail(f"request 缺失身份字段: {missing}")
    identity = validate_identity(
        {key: request[key] for key in IDENTITY_FIELDS}, field_name="request"
    )

    page_id = identity["page_id"]
    if not _PAGE_ID.fullmatch(page_id):
        _fail(f"page_id 含非法字符: {page_id!r}")

    image_path = _require_string(request["image_path"], "image_path")
    if not _is_absolute(image_path):
        _fail("image_path 必须是绝对路径")
    _require_hex64(request["image_sha256"], "image_sha256")

    if request["result_path"] != "result.json":
        _fail('result_path 必须是 "result.json"')

    outputs = request["outputs"]
    _require_exact_keys(outputs, OUTPUT_KEYS, field_name="outputs")
    expected = canonical_outputs(page_id)
    for key in OUTPUT_KEYS:
        value = _require_string(outputs[key], f"outputs.{key}")
        if value != expected[key]:
            _fail(f"outputs.{key} 必须是 {expected[key]!r}，收到 {value!r}")

    spec: dict[str, Any] = {
        "stage": stage,
        "identity": identity,
        "page_id": page_id,
        "image_path": image_path,
        "image_sha256": request["image_sha256"],
        "outputs": {("c1" if stage == "ocr" else "c2"): expected[("c1" if stage == "ocr" else "c2")]},
    }
    if stage == "ocr":
        spec["outputs"] = {"c1": expected["c1"]}
        return spec

    inputs = request["inputs"]
    _require_exact_keys(inputs, ("c1",), field_name="inputs")
    c1_path = _require_string(inputs["c1"], "inputs.c1")
    if not _is_absolute(c1_path):
        _fail("inputs.c1 必须是绝对路径")

    binding = request["c1_binding"]
    _require_exact_keys(binding, ("identity", "sha256", "image_sha256"), field_name="c1_binding")
    binding_identity = validate_identity(binding["identity"], field_name="c1_binding.identity")
    for key in SHARED_IDENTITY_FIELDS:
        if binding_identity[key] != identity[key]:
            _fail(f"c1_binding.identity.{key} 与请求不一致")
    _require_hex64(binding["sha256"], "c1_binding.sha256")
    _require_hex64(binding["image_sha256"], "c1_binding.image_sha256")
    if binding["image_sha256"] != request["image_sha256"]:
        _fail("c1_binding.image_sha256 与请求 image_sha256 不一致")

    spec.update(
        {
            "c1_path": c1_path,
            "c1_sha256": binding["sha256"],
            "outputs": {"c2": expected["c2"], "sidecar": expected["sidecar"]},
        }
    )
    return spec


def _is_absolute(path: str) -> bool:
    """判断是否为**当前平台**的绝对路径。

    协议只要求“绝对路径”，没有绑定 Windows 形式；CI 在 Linux 上运行时
    ``/tmp/...`` 同样是绝对路径，不能误判为相对路径。
    同时拒绝 Windows 的驱动器相对路径（``C:foo``）。
    """
    if path.startswith(("\\\\", "//")):
        return True
    if os.name == "nt":
        return bool(re.match(r"^[A-Za-z]:[\\/]", path))
    return path.startswith("/")


def validate_result(payload: Any) -> dict[str, Any]:
    """校验 result.json；供 M2 自查与测试使用（M1 侧还有独立实现）。"""
    _require_exact_keys(payload, RESULT_KEYS, field_name="result")
    if payload["protocol"] != RESULT_PROTOCOL:
        _fail(f"result.protocol 必须是 {RESULT_PROTOCOL!r}")
    identity = validate_identity(payload["identity"], field_name="result.identity")
    _require_int(payload["code"], "result.code", minimum=0)
    _require_string(payload["msg"], "result.msg", allow_empty=True)
    if not isinstance(payload["transient"], bool):
        _fail("result.transient 必须是布尔")
    artifacts = payload["artifacts"]
    if not isinstance(artifacts, dict):
        _fail("result.artifacts 必须是对象")
    extra = [key for key in artifacts if key not in ARTIFACT_KEYS]
    if extra:
        _fail(f"result.artifacts 含未声明键: {sorted(extra)}")
    for key, value in artifacts.items():
        _require_string(value, f"result.artifacts.{key}")
    return {"identity": identity, "code": payload["code"], "artifacts": dict(artifacts)}


def build_result(
    *,
    identity: dict[str, Any],
    code: int,
    msg: str = "",
    artifacts: dict[str, str] | None = None,
    transient: bool = False,
) -> dict[str, Any]:
    """按 WORKER_RESULT_SCHEMA 组装结果；**不包含 detail**。"""
    payload: dict[str, Any] = {
        "protocol": RESULT_PROTOCOL,
        "identity": {key: identity.get(key) for key in IDENTITY_FIELDS},
        "code": int(code),
        "msg": str(msg or ""),
        "artifacts": dict(artifacts or {}),
    }
    if code != 0:
        payload["transient"] = bool(transient)
    return payload


# --------------------------------------------------------------------------
# PROMPT_HASH_SPEC
# --------------------------------------------------------------------------


def canonical_messages_bytes(messages: list[dict[str, str]]) -> bytes:
    """把“最终有序消息列表”编码成规范字节串。

    协议要求：每项恰好 ``{role, content}``；UTF-8 无 BOM；
    ``ensure_ascii=false``、``separators=(",", ":")``、``allow_nan=false``；
    不 trim、不归一化 Unicode、不改变顺序。
    """
    if not isinstance(messages, list) or not messages:
        raise ValueError("最终消息列表不能为空")
    normalized: list[dict[str, str]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise ValueError(f"messages[{index}] 必须恰好包含 role/content")
        role = message["role"]
        content = message["content"]
        if not isinstance(role, str) or not isinstance(content, str):
            raise ValueError(f"messages[{index}] 的 role/content 必须是字符串")
        if role == "":
            raise ValueError(f"messages[{index}].role 不能为空")
        normalized.append({"role": role, "content": content})
    text = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:  # 例如孤立 surrogate
        raise ValueError(f"最终消息列表含无法编码的字符: {exc}") from exc


def prompt_sha256(messages: list[dict[str, str]]) -> str:
    import hashlib

    return hashlib.sha256(canonical_messages_bytes(messages)).hexdigest()
