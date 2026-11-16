"""视觉实体 Sidecar（``vision_refs/0.1``）——M1/M2 OFFLINE PROTOCOL V1.0。

字段白名单来自协议包 ``SIDECAR_SCHEMA.json`` + ``FIELD_CONTRACT.md``：

- 根对象：``schema_version`` + 七元身份（**扁平**，不嵌套）+ ``c2`` + ``source`` +
  ``observations``；``additionalProperties: false``，所以**不能**再写
  ``identity`` 镜像 / ``contract_status`` / ``c1_sha256`` 这些扩展字段。
- ``source.component_mode`` 离线只允许 ``fixture|stub``（``real`` 在本范围禁用）。
- ``appearance`` 允许空对象；``clothing`` 要么是**非空白字符串**，要么整个键缺省，
  不允许 ``null``（协议 F04）。当前 VLM 不给服装信息，所以默认省略。
- ``confidence``：``kind`` + ``calibrated`` 必填；``unavailable`` 时 value 为
  ``null``（或缺省），``model_estimate`` 时是有限原生数且落在 ``[0,1]``；
  M2 没有校准集，``calibrated`` 永远是 ``false``（协议禁止 true）。
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

SCHEMA_VERSION = "vision_refs/0.1"
C2_SCHEMA_VERSION = "1.0"
COMPONENT_MODES = ("fixture", "stub")
IDENTITY_FIELDS = (
    "job_id",
    "page_id",
    "generation_id",
    "input_revision",
    "epoch",
    "attempt_id",
    "fencing_token",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _confidence(value: Any) -> dict[str, Any]:
    """置信度归一化：非法/缺失一律 unavailable，绝不伪装成校准值。"""
    if isinstance(value, bool) or value is None:
        return {"kind": "unavailable", "value": None, "calibrated": False}
    try:
        number = float(value)
    except (TypeError, ValueError):
        return {"kind": "unavailable", "value": None, "calibrated": False}
    if math.isnan(number) or math.isinf(number) or not 0.0 <= number <= 1.0:
        return {"kind": "unavailable", "value": None, "calibrated": False}
    return {"kind": "model_estimate", "value": round(number, 4), "calibrated": False}


def _appearance(clothing: str | None) -> dict[str, Any]:
    appearance: dict[str, Any] = {"visible_features": []}
    if clothing is not None:
        if not isinstance(clothing, str) or not clothing.strip():
            raise ValueError("clothing 必须是非空字符串或缺省（协议禁止 null/空白）")
        appearance["clothing"] = clothing
    return appearance


def build_refs(
    *,
    identity: dict[str, Any],
    page_id: str,
    c2_doc: dict[str, Any],
    c2_relative_path: str,
    c2_bytes: bytes,
    component_mode: str,
    model_ref: str,
    prompt_sha256: str,
    evidence_ref: str,
    clothing: str | None = None,
) -> dict[str, Any]:
    """构造 sidecar；``c2_bytes`` 必须是磁盘上的**原始字节**。"""
    if component_mode not in COMPONENT_MODES:
        raise ValueError(f"component_mode 只能是 {COMPONENT_MODES}，收到 {component_mode!r}")
    if not isinstance(identity, dict):
        raise ValueError("identity 必须是对象")
    identity_block: dict[str, Any] = {}
    for key in IDENTITY_FIELDS:
        if key not in identity:
            raise ValueError(f"identity 缺少字段 {key}")
        identity_block[key] = identity[key]

    observations: list[dict[str, Any]] = []
    for index, obj in enumerate(c2_doc.get("objects") or []):
        object_id = str(obj.get("object_id") or "")
        if not object_id.startswith(page_id):
            raise ValueError(f"object_id 不属于本页: {object_id!r}")
        observations.append(
            {
                "observation_id": f"obs_{index + 1:03d}",
                "object_id": object_id,
                "identity_status": "unknown",
                "visual_description": str(obj.get("label") or ""),
                "source_ref": f"{c2_relative_path}#/objects/{index}",
                "appearance": _appearance(clothing),
                "confidence": _confidence(obj.get("confidence")),
            }
        )

    refs = dict(identity_block)
    refs.update(
        {
            "schema_version": SCHEMA_VERSION,
            "c2": {
                "asset_id": f"{page_id}_vlm",
                "schema_version": C2_SCHEMA_VERSION,
                "relative_path": c2_relative_path,
                "sha256": sha256_bytes(c2_bytes),
            },
            "source": {
                "component_mode": component_mode,
                "model_ref": model_ref,
                "prompt_sha256": prompt_sha256,
                "evidence_ref": evidence_ref,
            },
            "observations": observations,
        }
    )
    return refs
