"""内容安全结论（V1.2.2）：从原始响应开始保留 safety 数据，任何异常都 fail-closed。

V1.2.1 的缺陷（被第三轮复审复现）：解析层把 ``safety.flags`` 换成了“原因列表”，
于是模型返回的 ``flags=["violence"]`` 在结果里变成 ``flags=[]``，
再加上 ``pass=true``，最终被判为安全并通过。V1.2.2 起：

1. ``safety`` 原始对象原样保存在 ``SafetyRecord.raw``，并计算规范化 SHA256；
2. ``flags`` 字段**必须存在**且必须是数组，缺失/类型错/空白/超长一律阻断；
3. **只要 flags 非空就阻断**（包括模型自己写 ``pass=true`` 却带 flag 的自相矛盾情形）；
4. ``pass`` 必须是原生 JSON ``true``，``"true"`` / ``1`` / ``"1"`` 全部阻断；
5. 结论必须来自可信来源（``safety_source == "model"``），不能只凭 Worker 自述；
6. ``evaluate_vlm_safety`` 会把后端结果与原始记录**逐字段对照**，
   一旦发现“解析丢了 flags”或“pass 被改写”，直接阻断（``safety_flags_mismatch``）。

任一条件不满足 → Worker 返回 3004，**不写 C2、不写 sidecar**，也不进入下游。
3001 只表示“OCR 没识别到文字”，与安全无关。
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 仅类型检查：运行期导入会与 backends 包形成循环
    from .backends.base import VlmResult

ERROR_SAFETY_BLOCKED = 3004

TRUSTED_SOURCES = frozenset({"model"})
_MAX_REASONS = 16
_MAX_FLAG_LENGTH = 200
_MAX_FLAGS = 32
# safety 对象只允许这两个键。任何额外键都可能是“未知风险标记”
# （例如 {"pass": true, "flags": [], "violence": true}），
# 不能当作无害字段丢弃 —— V1.2.6 P0-01 第 4 条。
_ALLOWED_SAFETY_KEYS = frozenset({"pass", "flags"})


class SafetyBlocked(RuntimeError):
    """安全拦截：调用方必须映射到 3004，并且不发布任何产物。"""

    code = ERROR_SAFETY_BLOCKED

    def __init__(self, verdict: "SafetyVerdict", *, page_id: str = "", stage: str = "vlm") -> None:
        super().__init__(verdict.message())
        self.verdict = verdict
        self.page_id = page_id
        self.stage = stage


@dataclass(frozen=True)
class SafetyRecord:
    """原始 ``safety`` 对象的解析结果；``raw`` 与 ``flags`` 都是原样的。"""

    present: bool
    pass_value: Any = None
    flags: tuple[str, ...] | None = None
    reasons: tuple[str, ...] = ()
    raw: dict[str, Any] | None = None
    evidence_sha256: str = ""

    @property
    def ok(self) -> bool:
        return not self.reasons

    def to_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "pass": self.pass_value,
            "flags": list(self.flags) if self.flags is not None else None,
            "reasons": list(self.reasons),
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True)
class SafetyVerdict:
    passed: bool
    reasons: tuple[str, ...] = ()
    source: str = "unavailable"
    flags: tuple[str, ...] = ()
    evidence_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass": self.passed,
            "reasons": list(self.reasons),
            "source": self.source,
            "flags": list(self.flags),
            "evidence_sha256": self.evidence_sha256,
        }

    def message(self) -> str:
        if self.passed:
            return "safety_ok"
        return "safety_blocked:" + ",".join(self.reasons)


def canonical_sha256(obj: Any) -> str:
    """对 JSON 可序列化对象求稳定哈希（键排序、紧凑分隔符、不转义中文）。"""
    try:
        blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        blob = repr(obj)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def parse_safety(payload: Any) -> SafetyRecord:
    """严格解析原始 ``safety`` 对象；不做任何类型宽恕，不丢任何 flag。"""
    if not isinstance(payload, dict):
        return SafetyRecord(present=False, reasons=("safety_missing",))

    reasons: list[str] = []
    raw = dict(payload)
    evidence = canonical_sha256(raw)

    # 未知键一律阻断：我们无法判断它是无关注释还是风险标记，
    # 静默忽略等于“丢弃未知风险内容”。
    for key in sorted(raw):
        if key not in _ALLOWED_SAFETY_KEYS:
            reasons.append(f"safety_unknown_field:{key}")

    pass_value = payload.get("pass")
    if "pass" not in payload:
        reasons.append("safety_pass_missing")
    elif pass_value is not True:
        # 只认 bool；1 / "true" / "1" 都在这里被拒
        reasons.append("safety_pass_not_true")

    flags: tuple[str, ...] | None
    if "flags" not in payload:
        # 缺失不等于空数组：无法证明“没有风险”，必须阻断
        flags = None
        reasons.append("safety_flags_missing")
    else:
        value = payload["flags"]
        if value is None:
            flags = None
            reasons.append("safety_flags_null")
        elif not isinstance(value, list):
            flags = None
            reasons.append("safety_flags_not_list")
        elif len(value) > _MAX_FLAGS:
            flags = tuple(str(x) for x in value[:_MAX_FLAGS])
            reasons.append(f"safety_flags_overflow:{len(value)}")
        else:
            collected: list[str] = []
            broken = False
            for flag in value:
                if not isinstance(flag, str):
                    reasons.append("safety_flag_not_string")
                    broken = True
                    break
                text = flag.strip()
                if not text:
                    reasons.append("safety_flag_blank")
                    broken = True
                    break
                if len(text) > _MAX_FLAG_LENGTH:
                    reasons.append("safety_flag_too_long")
                    broken = True
                    break
                collected.append(text)
            # 任一元素非法：整份 flags 不可信，保持 None（不是空数组）
            flags = None if broken else tuple(collected)

    if flags:
        # 只要模型给了风险标记，就按不安全处理；未知 flag 也照原样列出，不忽略
        for flag in flags:
            reasons.append(f"flag:{flag}")
        reasons.append("safety_flags_nonempty")

    unique = tuple(dict.fromkeys(reasons))
    return SafetyRecord(
        present=True,
        pass_value=pass_value,
        flags=flags,
        reasons=unique,
        raw=raw,
        evidence_sha256=evidence,
    )


def evaluate_vlm_safety(result: "VlmResult") -> SafetyVerdict:
    """把后端结果与原始 safety 记录对照，任何不一致都拦截。"""
    reasons: list[str] = []

    source = str(getattr(result, "safety_source", "unavailable"))
    if source not in TRUSTED_SOURCES:
        reasons.append("safety_source_untrusted")

    raw = getattr(result, "safety_raw", None)
    record = parse_safety(raw) if raw is not None else SafetyRecord(present=False, reasons=("safety_missing",))
    reasons.extend(record.reasons)

    # 后端结果里的 safety_pass / safety_flags 必须与原始记录一致：
    # 一旦解析层把 flags 弄丢，这里会报 safety_flags_mismatch 而不是放行。
    if record.present:
        if getattr(result, "safety_pass", None) is not True:
            if record.pass_value is True:
                reasons.append("safety_pass_mismatch")
        elif record.pass_value is not True:
            reasons.append("safety_pass_mismatch")

        result_flags = getattr(result, "safety_flags", None)
        expected_flags = list(record.flags) if record.flags is not None else None
        if result_flags is None:
            reasons.append("safety_flags_missing")
        elif expected_flags is None:
            reasons.append("safety_flags_mismatch")
        elif [str(x).strip() for x in result_flags] != expected_flags:
            reasons.append("safety_flags_mismatch")

        if getattr(result, "safety_evidence", "") and getattr(result, "safety_evidence") != record.evidence_sha256:
            reasons.append("safety_evidence_mismatch")

    flags = record.flags or ()
    unique = tuple(dict.fromkeys(reasons))[:_MAX_REASONS]
    return SafetyVerdict(
        passed=not unique,
        reasons=unique,
        source=source,
        flags=tuple(flags),
        evidence_sha256=record.evidence_sha256,
    )


def blocked_payload(
    verdict: SafetyVerdict, *, page_id: str, stage: str = "vlm"
) -> dict[str, Any]:
    """失败诊断载荷（Worker 写进 result.json 的 ``detail``）。"""
    return {
        "page_id": page_id,
        "stage": stage,
        "code": ERROR_SAFETY_BLOCKED,
        "verdict": verdict.to_dict(),
    }


# --------------------------------------------------------------- 安全放行凭证
#
# V1.2.6 P0-02：旧索引/缓存不能脱离“本次任务的安全判定”被单独读取。
# 做法是引入一次性凭证 —— 只有**刚刚通过门禁**的调用方才能拿到，
# 磁盘上的历史索引再有效，也拿不到这张凭证。


@dataclass(frozen=True)
class SafetyClearance:
    """一次安全放行的凭证；只有 verdict.passed 才能签发。"""

    page_id: str
    token: str
    issued_at: float
    evidence_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "token": self.token,
            "issued_at": self.issued_at,
            "evidence_sha256": self.evidence_sha256,
        }


def issue_clearance(page_id: str, verdict: SafetyVerdict) -> SafetyClearance:
    if not verdict.passed:
        raise SafetyBlocked(verdict, page_id=page_id)
    return SafetyClearance(
        page_id=page_id,
        token=uuid.uuid4().hex,
        issued_at=time.time(),
        evidence_sha256=verdict.evidence_sha256,
    )


def clearance_for_document(page_id: str, doc: dict[str, Any]) -> SafetyClearance:
    """给离线脚本用：先按门禁规则复检这份 C1/C2 的 safety，再签发凭证。"""
    record = parse_safety(doc.get("safety"))
    verdict = SafetyVerdict(
        passed=record.ok,
        reasons=record.reasons,
        source="document",
        flags=record.flags or (),
        evidence_sha256=record.evidence_sha256,
    )
    return issue_clearance(page_id, verdict)
