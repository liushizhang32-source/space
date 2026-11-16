"""版面结构提取：把 C1 的文字块整理成列与阅读顺序。

只做确定性的几何计算，不引入新的公共契约：
- 输出是 sidecar，不修改 C1；
- 列数上限 ``MAX_COLUMNS``，超过时按最左侧的列合并，避免极端版面炸开；
- 不认识的版面（单块、无块）也返回合法结构。
"""

from __future__ import annotations

from typing import Any, Iterable

SCHEMA_VERSION = "vision_layout/0.1"
MAX_COLUMNS = 6
#: 两块横向重叠超过较窄者宽度的这个比例，就算同一列
_COLUMN_OVERLAP = 0.5


def _width(bbox: Iterable[float]) -> float:
    x1, _, x2, _ = bbox
    return max(0.0, float(x2) - float(x1))


def _overlap_ratio(a: Iterable[float], b: Iterable[float]) -> float:
    ax1, _, ax2, _ = (float(v) for v in a)
    bx1, _, bx2, _ = (float(v) for v in b)
    inter = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    narrow = min(ax2 - ax1, bx2 - bx1)
    if narrow <= 0:
        return 0.0
    return inter / narrow


def _columns(blocks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """按横向重叠把块分列，列内按 y 再 x 排序。"""
    columns: list[list[dict[str, Any]]] = []
    for block in sorted(blocks, key=lambda b: (float(b["bbox"][0]), float(b["bbox"][1]))):
        placed = False
        for column in columns:
            if _overlap_ratio(block["bbox"], column[0]["bbox"]) >= _COLUMN_OVERLAP:
                column.append(block)
                placed = True
                break
        if not placed:
            columns.append([block])

    # 列本身按左边界排序；列内按上边界、再左边界
    columns.sort(key=lambda col: min(float(b["bbox"][0]) for b in col))
    for column in columns:
        column.sort(key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0])))
    return columns


def build_layout(
    page_id: str,
    c1: dict[str, Any],
    *,
    max_columns: int = MAX_COLUMNS,
) -> dict[str, Any]:
    """从 C1 生成版面 sidecar。``c1`` 必须是已通过校验的 OCR 文档。"""
    if c1.get("page_id") != page_id:
        raise ValueError(f"page_id 不一致: {c1.get('page_id')!r} != {page_id!r}")

    raw_blocks = list(c1.get("text_blocks") or [])
    columns = _columns(raw_blocks)

    # 列过多时把最右侧的并进最后一列，保证输出规模可控
    truncated = False
    if len(columns) > max_columns:
        keep = columns[: max_columns - 1]
        rest = [b for col in columns[max_columns - 1 :] for b in col]
        rest.sort(key=lambda b: (float(b["bbox"][1]), float(b["bbox"][0])))
        keep.append(rest)
        columns = keep
        truncated = True

    layout_columns: list[dict[str, Any]] = []
    reading_order: list[str] = []
    order = 0
    for index, column in enumerate(columns, start=1):
        block_ids = [str(b["block_id"]) for b in column]
        reading_order.extend(block_ids)
        order += len(block_ids)
        xs = [float(v) for b in column for v in (b["bbox"][0], b["bbox"][2])]
        layout_columns.append(
            {
                "column_id": f"col_{index:02d}",
                "block_ids": block_ids,
                "x1": min(xs),
                "x2": max(xs),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "page_id": page_id,
        "has_text": bool(raw_blocks),
        "column_count": len(layout_columns),
        "columns": layout_columns,
        "reading_order": reading_order,
        "blocks": [
            {
                "block_id": str(b["block_id"]),
                "order": reading_order.index(str(b["block_id"])),
                "text": b.get("text", ""),
                "bbox": list(b["bbox"]),
            }
            for b in raw_blocks
        ],
        "truncated": truncated,
    }
