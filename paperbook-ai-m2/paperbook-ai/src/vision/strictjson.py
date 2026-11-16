"""严格 JSON 解析：拒绝重复键与非有限数字（V1.2.2 P0-1）。

背景：Python 的 ``json.loads`` 遇到同名键时**静默保留最后一个**。
模型如果输出::

    {"safety": {"pass": true, "flags": ["violence"], "flags": []}}

解析后变成 ``{"pass": true, "flags": []}``——风险标记被悄悄覆盖掉了。
安全判定再往后做多少校验都没用，因为坏数据在进入判定之前就已经“洗干净”了。

所以必须在**最外层解析**就拒绝重复键，并且是递归的：
``object_pairs_hook`` 对每一层对象都会调用，嵌套对象里的重复键同样会命中。

设计取舍：
- 只做拒绝，不做“取第一个/合并”之类的容错——安全字段没有“更可信的一份”。
- 同时拒绝 ``NaN`` / ``Infinity``（``json`` 默认接受，但它们不是合法 JSON）。
- 失败一律 fail-closed：调用方必须当作“没有得到可信结构”，不得继续产出 C2/Sidecar。
"""

from __future__ import annotations

import json
from typing import Any


class StrictJsonError(ValueError):
    """解析失败；``kind`` 区分重复键 / 非法常量 / 语法错误。"""

    def __init__(self, kind: str, *, key: str = "", detail: str = "") -> None:
        self.kind = kind
        self.key = key
        self.detail = detail
        if kind == "duplicate_key":
            message = f"JSON 对象出现重复键 {key!r}（拒绝覆盖，fail-closed）"
        elif kind == "non_finite_number":
            message = "JSON 含 NaN/Infinity 等非有限数字"
        else:
            message = f"JSON 解析失败: {detail or kind}"
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "key": self.key, "detail": self.detail}


def _pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise StrictJsonError("duplicate_key", key=key)
        seen.add(key)
    return dict(pairs)


def _reject_constant(text: str) -> Any:
    raise StrictJsonError("non_finite_number", detail=text)


def loads(text: str) -> Any:
    """解析 JSON 文本，重复键/非法常量直接抛 ``StrictJsonError``。"""
    try:
        return json.loads(
            text,
            object_pairs_hook=_pairs_hook,
            parse_constant=_reject_constant,
        )
    except StrictJsonError:
        raise
    except json.JSONDecodeError as exc:
        raise StrictJsonError("invalid_json", detail=f"{exc.msg} at {exc.pos}") from exc


def loads_object(text: str) -> dict[str, Any]:
    """同 ``loads``，但要求顶层是对象。"""
    data = loads(text)
    if not isinstance(data, dict):
        raise StrictJsonError("not_object", detail=type(data).__name__)
    return data
