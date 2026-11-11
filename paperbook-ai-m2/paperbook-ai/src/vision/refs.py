"""视觉实体 Sidecar（**候选协议** ``vision_refs/0.1``，未签认）。

用途：把 C2 里的物体转成“角色参考观察”，供 M3 Story Planner 做跨页一致性。
边界（M1 交接文档明确）：

- Sidecar **不是**公共 API。字段/路径在 U1/J1 签认前都是候选，
  因此本文件同时在顶层写 ``"contract_status": "candidate"``，
  任何校验器都应把它当候选协议而不是最终契约（V1.2.1 P0-4）；
- M2 **不得**定义 ``canonical_id`` / ``character_id`` / ``canonical_identity``，
  只输出观察 + 置信度 + ``identity_status ∈ {unknown, ambiguous}``；
- ``c2.sha256`` 必须是**落盘原始字节**的哈希（M1 会独立复算，不能重排 JSON）。

兼容性（与 M1 待共同确认的三处）：

1. ``identity`` 同时提供**嵌套对象**与**扁平字段**两份。M1 校验器若读
   ``refs["identity"]["job_id"]`` 走嵌套；若直接读 ``refs["job_id"]`` 走扁平。
   两种取值完全相同，不会出现分叉；签认后只保留一种。
2. ``appearance.clothing`` 允许 ``str | null``：当前模型不给服装信息，写 null；
   将来接入检测模型可写 "红色上衣" 这类字符串，不改成数组。
3. ``confidence`` 两种形态都带 ``calibrated`` 字段：
   ``{"value": 0.83, "kind": "model_estimate", "calibrated": false}`` 或
   ``{"value": null, "kind": "unavailable", "calibrated": false}``。
   M2 没有校准集，任何“已校准”声明都是假的。

当前模型的局限（如实记录，不编造）：VLM 只给 ``label + bbox + confidence``，
没有服装/外观字段，所以 ``clothing`` 为 null、``visible_features`` 为空。
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

SCHEMA_VERSION = "vision_refs/0.1"
CONTRACT_STATUS = "candidate"
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
        return {"value": None, "kind": "unavailable", "calibrated": False}
    try:
        number = float(value)
    except (TypeError, ValueError):
        return {"value": None, "kind": "unavailable", "calibrated": False}
    if math.isnan(number) or math.isinf(number) or not 0.0 <= number <= 1.0:
        return {"value": None, "kind": "unavailable", "calibrated": False}
    return {"value": round(number, 4), "kind": "model_estimate", "calibrated": False}


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
    c1_sha256: str | None = None,
) -> dict[str, Any]:
    """构造 sidecar；``c2_bytes`` 必须是磁盘上的原始字节。"""
    objects = c2_doc.get("objects") or []
    observations: list[dict[str, Any]] = []
    for index, obj in enumerate(objects):
        object_id = str(obj.get("object_id") or "")
        if not object_id.startswith(page_id):
            raise ValueError(f"object_id 不属于本页: {object_id!r}")
        observations.append(
            {
                "observation_id": f"obs_{index + 1:03d}",
                "object_id": object_id,
                "appearance": {"clothing": None, "visible_features": []},
                "visual_description": str(obj.get("label") or ""),
                "confidence": _confidence(obj.get("confidence")),
                "identity_status": "unknown",
                "source_ref": f"{c2_relative_path}#/objects/{index}",
            }
        )

    identity_block = {key: identity.get(key) for key in IDENTITY_FIELDS}
    refs: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_status": CONTRACT_STATUS,
        "identity": identity_block,
        "c2": {
            "asset_id": f"{page_id}_vlm",
            "schema_version": str(c2_doc.get("schema_version") or "1.0"),
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
    if c1_sha256:
        refs["c1_sha256"] = c1_sha256
    # 扁平镜像：兼容只读顶层字段的校验器（签认后二选一）
    for key, value in identity_block.items():
        refs[key] = value
    return refs
