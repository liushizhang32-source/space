"""内容安全结论（V1.2.1）：严格校验，不做任何类型宽恕。

判定门槛（全部满足才算“安全”）：

1. 原始响应里必须有 ``safety`` 对象；
2. ``safety.pass`` 必须是**原生 JSON 布尔 true**——字符串 ``"true"``、
   数字 ``1``、``"1"``、``"yes"`` 一律不放行；
3. ``safety.flags`` 必须是数组，元素必须是非空字符串，不允许空白/纯空格；
4. 结论必须来自模型响应本身（``safety_source == "model"``），
   由本地补出来的默认值不算数；
5. 只要有任何 flag，就按不安全处理（自相矛盾的“安全但有风险”同样拦截）。

任一条件不满足 → Worker 返回 3004，**不写 C2、不写 sidecar**。
3001 只表示“OCR 没识别到文字”，与安全无关。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .backends.base import VlmResult

ERROR_SAFETY_BLOCKED = 3004

TRUSTED_SOURCES = frozenset({"model"})
_MAX_REASONS = 8
_MAX_FLAG_LENGTH = 200


@dataclass(frozen=True)
class SafetyVerdict:
    passed: bool
    reasons: tuple[str, ...] = ()
    source: str = "unavailable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass": self.passed,
            "reasons": list(self.reasons),
            "source": self.source,
        }

    def message(self) -> str:
        if self.passed:
            return "safety_ok"
        return "safety_blocked:" + ",".join(self.reasons)


def strict_safety(payload: Any) -> tuple[bool, list[str]]:
    """严格解析原始 ``safety`` 对象，返回 ``(是否安全, 原因列表)``。

    只接受：``{"pass": true, "flags": []}``（flags 可为缺省）。
    其余一切形态都判不安全，并在原因里写明具体哪一条不合格。
    """
    reasons: list[str] = []
    if not isinstance(payload, dict):
        return False, ["safety_missing"]

    if "pass" not in payload:
        reasons.append("safety_pass_missing")
    else:
        value = payload["pass"]
        # 关键：只认 bool，不认 1 / "true" / "1"
        if value is not True:
            reasons.append("safety_pass_not_true")

    if "flags" in payload:
        flags = payload["flags"]
        if not isinstance(flags, list):
            reasons.append("safety_flags_not_list")
        else:
            for flag in flags:
                if not isinstance(flag, str):
                    reasons.append("safety_flag_not_string")
                    break
                text = flag.strip()
                if not text:
                    reasons.append("safety_flag_blank")
                    break
                if len(text) > _MAX_FLAG_LENGTH:
                    reasons.append("safety_flag_too_long")
                    break

    return (not reasons), reasons


def evaluate_vlm_safety(result: VlmResult) -> SafetyVerdict:
    """把后端结果收束成最终结论；任何不确定都拦截。"""
    reasons: list[str] = []

    source = getattr(result, "safety_source", "unavailable")
    if source not in TRUSTED_SOURCES:
        reasons.append("safety_source_untrusted")

    raw_flags = getattr(result, "safety_flags", None)
    flags: list[str] = []
    if raw_flags is None:
        reasons.append("safety_flags_missing")
    elif not isinstance(raw_flags, (list, tuple)):
        reasons.append("safety_flags_not_list")
    else:
        for flag in raw_flags:
            if not isinstance(flag, str) or not flag.strip():
                reasons.append("safety_flag_invalid")
                break
            flags.append(flag.strip())
        if len(flags) > _MAX_REASONS:
            reasons.append(f"flag_overflow:{len(flags) - _MAX_REASONS}")
            flags = flags[:_MAX_REASONS]

    for flag in flags:
        reasons.append(f"flag:{flag}")

    if getattr(result, "safety_pass", None) is not True:
        reasons.append("safety_not_asserted")
    elif flags:
        reasons.append("safety_conflict")

    unique = tuple(dict.fromkeys(reasons))
    return SafetyVerdict(passed=not unique, reasons=unique, source=str(source))


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
