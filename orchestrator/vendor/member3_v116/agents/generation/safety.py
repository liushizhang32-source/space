"""内容安全检查：生成前、生成后、落盘前各一道闸。

契约依据：
  - §1.7 三级状态：任一层 safety=false → 页面 blocked；
  - §1.14 降级矩阵：安全拦截不产出；
  - 公告：不合格产物不能进入最终输出。

开关默认关闭（Q8：v1 字段与分支必须实现，开关默认关），
但上游 vlm.json 里 safety.pass=false 是成员 2 已经做出的结论，无条件生效。
"""

from __future__ import annotations

from .config import Settings
from .errors import AppError, ErrorCode


def find_flags(texts: list[str], blocklist: tuple[str, ...]) -> list[str]:
    """返回命中的词；空列表表示干净。"""
    terms = [term for term in blocklist if term and term.strip()]
    hits: list[str] = []
    for text in texts:
        if not text:
            continue
        for term in terms:
            if term in text and term not in hits:
                hits.append(term)
    return hits


def ensure_safe(texts: list[str], settings: Settings, *, stage: str) -> None:
    """开关打开且命中词表时抛 3004；关闭时是空操作。"""
    if not settings.safety_enabled:
        return
    flags = find_flags(texts, settings.safety_blocklist)
    if flags:
        raise AppError(
            ErrorCode.SAFETY_BLOCKED,
            f"内容安全拦截（{stage}）",
            detail=",".join(flags),
        )


def story_texts(doc: dict) -> list[str]:
    """收集 story.json 里所有会被展示/朗读的文本，用于落盘前复检。"""
    texts: list[str] = []
    title = doc.get("title")
    if isinstance(title, str):
        texts.append(title)
    for segment in doc.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        for key in ("narration", "scene"):
            value = segment.get(key)
            if isinstance(value, str):
                texts.append(value)
    return texts


def ensure_story_safe(story: dict, settings: Settings, *, stage: str) -> None:
    """Story 产物（dict）的统一安全入口，供 Video 等下游独立调用时复用。"""
    ensure_safe(story_texts(story), settings, stage=stage)


def guard_text(text: str, settings: Settings, *, stage: str) -> None:
    """单段文本的统一安全入口，供 TTS 独立入口复用。"""
    ensure_safe([text], settings, stage=stage)
