
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class VLMObject(BaseModel):
    """An object detected in the picture-book page."""

    object_id: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9]{3,11}_p\d{2}_o\d{2}$",
        description="Unique object ID, e.g. book01_p03_o01."
    )

    label: str = Field(
        ...,
        description="Chinese name of the detected object."
    )

    bbox: tuple[StrictInt, StrictInt, StrictInt, StrictInt] = Field(
        ...,
        description="Bounding box [x1, y1, x2, y2] in original image pixels."
    )

    confidence: float = Field(
        ...,
        ge=0,
        le=1,
        description="Detection confidence, from 0 to 1."
    )

    @model_validator(mode="after")
    def validate_bbox(self):
        x1, y1, x2, y2 = self.bbox

        if x1 < 0 or y1 < 0:
            raise ValueError(
                "bbox coordinates cannot be negative."
            )

        if x1 >= x2 or y1 >= y2:
            raise ValueError(
                "bbox must satisfy x1 < x2 and y1 < y2."
            )

        return self


class VLMSafety(BaseModel):
    """Safety inspection result."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    pass_: bool = Field(
        ...,
        alias="pass",
        description="Whether the page passes safety inspection."
    )

    flags: list[str] = Field(
        default_factory=list,
        description="Safety flags, if any."
    )


class VLMData(BaseModel):
    """Visual understanding result for one picture-book page."""

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

    status: Literal["ok", "empty"]

    image_width: int = Field(
        ...,
        gt=0
    )

    image_height: int = Field(
        ...,
        gt=0
    )

    description: str

    objects: list[VLMObject] = Field(
        default_factory=list
    )

    scene_tags: list[str] = Field(
        default_factory=list
    )

    safety: VLMSafety

    elapsed_ms: int = Field(
        ...,
        ge=0
    )

    @model_validator(mode="after")
    def validate_page_data(self):
        # 1. Check page ID consistency
        expected_page_id = (
            f"{self.book_id}_p{self.page_no:02d}"
        )

        if self.page_id != expected_page_id:
            raise ValueError(
                "page_id must match book_id and page_no."
            )

        # 2. Check object ID uniqueness
        object_ids = [
            obj.object_id for obj in self.objects
        ]

        if len(object_ids) != len(set(object_ids)):
            raise ValueError(
                "object_id must be unique."
            )

        # 3. Check empty status
        if self.status == "empty" and self.objects:
            raise ValueError(
                "Empty VLM result cannot contain objects."
            )

        if self.status == "ok" and not self.objects:
            raise ValueError(
                "No detected objects must use status='empty'."
            )

        # 4. Check object IDs and image boundaries
        for obj in self.objects:
            if not obj.object_id.startswith(
                self.page_id + "_o"
            ):
                raise ValueError(
                    "object_id must belong to the current page."
                )

            x1, y1, x2, y2 = obj.bbox

            if (
                x2 > self.image_width
                or y2 > self.image_height
            ):
                raise ValueError(
                    "bbox exceeds original image dimensions."
                )

        return self
