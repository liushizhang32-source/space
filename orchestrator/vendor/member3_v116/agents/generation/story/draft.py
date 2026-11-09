"""故事草稿的数据结构（生成器与模板共用）。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DraftSegment:
    narration: str
    scene: str = ""
    highlight_object_ids: list[str] | None = None


@dataclass
class StoryDraft:
    title: str
    segments: list[DraftSegment]
    model_name: str
    model_version: str = "1.0"
    extra: dict = field(default_factory=dict)

    @property
    def is_mock(self) -> bool:
        return self.model_name.startswith("mock")
