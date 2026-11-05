
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class StoryModelInfo(BaseModel):
    """Information about the model used for story generation."""

    name: str = Field(
        ...,
        description="Name of the generation model."
    )

    version: str = Field(
        ...,
        description="Version of the generation model."
    )


class StorySegment(BaseModel):
    """One narration segment of a picture-book story."""

    segment_id: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9]{3,11}_p\d{2}_s\d{2}$",
        description="Unique segment ID."
    )

    order: int = Field(
        ...,
        ge=1,
        description="Segment order, starting from 1."
    )

    narration: str = Field(
        ...,
        min_length=1,
        description="Narration text for TTS."
    )

    scene: str = Field(
        ...,
        min_length=1,
        description="Visual scene description."
    )

    image_prompt: str | None = Field(
        default=None,
        description="Optional image generation prompt."
    )

    duration_sec: float = Field(
        ...,
        gt=0,
        description="Actual or estimated segment duration in seconds."
    )

    duration_source: Literal["tts", "estimate"]

    audio_url: str | None = Field(
        default=None,
        description="TTS audio URL, required when duration_source is tts."
    )

    highlight_object_ids: list[
        Annotated[str, Field(pattern=r"^[a-z][a-z0-9]{3,11}_p\d{2}_o\d{2}$")]
    ] = Field(
        default_factory=list,
        description="Object IDs highlighted in this segment."
    )

    @model_validator(mode="after")
    def validate_audio(self):
        if self.duration_source == "tts" and not self.audio_url:
            raise ValueError(
                "audio_url is required when duration_source is tts."
            )

        return self


class StoryData(BaseModel):
    """Generated story for one picture-book page."""

    schema_version: Literal["1.0"]

    book_id: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9]{3,11}$"
    )

    page_id: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9]{3,11}_p\d{2}$"
    )

    page_no: int = Field(
        ...,
        ge=1
    )

    title: str = Field(
        ...,
        min_length=1,
        description="Story title."
    )

    age_level: Literal["3-6", "6-9"]

    status: Literal["ok"]

    segments: list[StorySegment] = Field(
        ...,
        min_length=1
    )

    total_duration_sec: float = Field(
        ...,
        gt=0
    )

    safety_pass: bool

    safety_flags: list[str] = Field(
        default_factory=list
    )

    model: StoryModelInfo

    elapsed_ms: int = Field(
        ...,
        ge=0
    )

    @model_validator(mode="after")
    def validate_story_data(self):
        # 1. Check page ID consistency
        expected_page_id = (
            f"{self.book_id}_p{self.page_no:02d}"
        )

        if self.page_id != expected_page_id:
            raise ValueError(
                "page_id must match book_id and page_no."
            )

        # 2. Check segment ID uniqueness
        segment_ids = [
            segment.segment_id
            for segment in self.segments
        ]

        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError(
                "segment_id must be unique."
            )

        # 3. Check segment order
        orders = [
            segment.order
            for segment in self.segments
        ]

        if sorted(orders) != list(
            range(1, len(self.segments) + 1)
        ):
            raise ValueError(
                "Segment orders must start at 1 without gaps."
            )

        # 4. Check segment IDs and highlighted objects
        for segment in self.segments:
            if not segment.segment_id.startswith(
                self.page_id + "_s"
            ):
                raise ValueError(
                    "segment_id must belong to the current page."
                )

            for object_id in segment.highlight_object_ids:
                if not object_id.startswith(
                    self.page_id + "_o"
                ):
                    raise ValueError(
                        "highlight_object_id must belong to the current page."
                    )

        return self
