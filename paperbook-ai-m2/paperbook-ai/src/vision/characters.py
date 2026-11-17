"""跨页对象目录与人物/物体关联（候选，不是身份识别）。

边界：
- 只做**可解释的候选关联**：按类别 + 标签归并，``identity_status`` 恒为
  ``unknown``，不产出 canonical_id / character_id（这些归 M1 决定）；
- 输出是 sidecar，不修改 C2；
- 所有结果确定性排序，便于复现与比对。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "vision_objects/0.1"
MAX_CLUSTERS = 50

#: 标签 → 类别。只收录绘本/动画里常见词，未收录的归 other。
_LABELS: dict[str, set[str]] = {
    "person": {
        "人物", "男孩", "女孩", "孩子", "儿童", "男人", "女人", "妈妈", "爸爸",
        "老师", "老人", "婴儿", "小朋友", "人",
    },
    "animal": {
        "狗", "小狗", "猫", "小猫", "兔子", "小鸟", "鸟", "鸭子", "熊", "狐狸",
        "老鼠", "鱼", "马", "牛", "羊", "猪", "鸡", "大象", "狮子", "老虎", "动物",
    },
    "scene": {"天空", "夜空", "星星", "月亮", "太阳", "云", "树", "森林", "草地",
              "沙滩", "海", "房子", "房间", "街道", "花园", "山"},
    "object": {"袋子", "纸袋", "书", "书页", "文字", "桌子", "椅子", "床", "门",
               "窗", "灯", "杯子", "碗", "球", "玩具", "胡萝卜", "花", "钟", "手表"},
}

_ALIAS: dict[str, str] = {label: cat for cat, labels in _LABELS.items() for label in labels}


def category_of(label: str) -> str:
    """把模型给的标签归到 person/animal/scene/object/other。"""
    text = (label or "").strip()
    if text in _ALIAS:
        return _ALIAS[text]
    # 去掉常见修饰后重试，例如“小男孩”“一只狗”
    for prefix in ("一个", "一只", "一位", "小", "大"):
        if text.startswith(prefix) and text[len(prefix):] in _ALIAS:
            return _ALIAS[text[len(prefix):]]
    return "other"


def _iter_objects(pages: Mapping[str, dict[str, Any]]) -> Iterable[tuple[str, dict[str, Any]]]:
    for page_id in sorted(pages):
        doc = pages[page_id]
        if doc.get("page_id") != page_id:
            raise ValueError(f"page_id 不一致: {doc.get('page_id')!r} != {page_id!r}")
        if doc.get("status") not in ("ok", "empty"):
            raise ValueError(f"{page_id} 状态不可用于关联: {doc.get('status')!r}")
        for obj in doc.get("objects") or []:
            yield page_id, obj


def build_object_catalog(pages: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    """把多页 C2 合成一份点读用对象目录。"""
    objects: list[dict[str, Any]] = []
    for page_id, obj in _iter_objects(pages):
        object_id = str(obj.get("object_id") or "")
        if not object_id.startswith(f"{page_id}_"):
            raise ValueError(f"object_id 与页面不匹配: {object_id!r} / {page_id!r}")
        objects.append(
            {
                "object_id": object_id,
                "page_id": page_id,
                "label": str(obj.get("label") or ""),
                "category": category_of(str(obj.get("label") or "")),
                "bbox": list(obj.get("bbox") or []),
                "confidence": obj.get("confidence"),
            }
        )
    objects.sort(key=lambda o: (o["page_id"], o["object_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "page_ids": sorted(pages),
        "objects": objects,
    }


def cluster_objects(
    pages: Mapping[str, dict[str, Any]],
    *,
    max_clusters: int = MAX_CLUSTERS,
) -> dict[str, Any]:
    """按类别 + 规范化标签把跨页对象归并成候选簇。

    这不是身份识别：同一角色出现在不同页会进同一簇，但不同角色若标签相同
    也会进同一簇，因此每个簇都标 ``identity_status="unknown"``，供上游人工
    或后续模型再判别。
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for page_id, obj in _iter_objects(pages):
        label = str(obj.get("label") or "").strip()
        key = (category_of(label), label)
        groups.setdefault(key, []).append(
            {
                "page_id": page_id,
                "object_id": str(obj.get("object_id") or ""),
                "bbox": list(obj.get("bbox") or []),
                "confidence": obj.get("confidence"),
            }
        )

    clusters: list[dict[str, Any]] = []
    for index, ((category, label), instances) in enumerate(
        sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])), start=1
    ):
        if index > max_clusters:
            break
        instances.sort(key=lambda i: (i["page_id"], i["object_id"]))
        clusters.append(
            {
                "cluster_id": f"cc_{index:03d}",
                "category": category,
                "label": label,
                "identity_status": "unknown",
                "method": "label_heuristic",
                "page_ids": sorted({i["page_id"] for i in instances}),
                "instances": instances,
            }
        )

    links: list[dict[str, Any]] = []
    for cluster in clusters:
        by_page: dict[str, list[dict[str, Any]]] = {}
        for inst in cluster["instances"]:
            by_page.setdefault(inst["page_id"], []).append(inst)
        page_ids = sorted(by_page)
        for i, left in enumerate(page_ids):
            for right in page_ids[i + 1:]:
                links.append(
                    {
                        "cluster_id": cluster["cluster_id"],
                        "from_page": left,
                        "to_page": right,
                        "from_object_ids": [o["object_id"] for o in by_page[left]],
                        "to_object_ids": [o["object_id"] for o in by_page[right]],
                        "method": "label_heuristic",
                        "identity_status": "unknown",
                    }
                )

    return {
        "schema_version": SCHEMA_VERSION,
        "clusters": clusters,
        "links": links,
        "truncated": len(groups) > len(clusters),
    }
