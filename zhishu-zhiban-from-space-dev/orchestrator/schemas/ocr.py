
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class OCRTextBlock(BaseModel):
    """A recognized text block on the picture-book page."""

    block_id: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9]{3,11}_p\d{2}_t\d{2}$",
        description="Unique text block ID."
    )

    order: int = Field(
        ...,
        ge=1,
        description="Reading order, starting from 1."
    )

    text: str = Field(
        ...,
        description="Recognized text content."
    )

    bbox: tuple[int, int, int, int] = Field(
        ...,
        description="Bounding box [x1, y1, x2, y2] in original image pixels."
    )

    confidence: float = Field(
        ...,
        ge=0,
        le=1,
        description="Recognition confidence, from 0 to 1."
    )

    @model_validator(mode="after")
    def validate_bbox(self):
        x1, y1, x2, y2 = self.bbox

        if x1 < 0 or y1 < 0:
            raise ValueError("bbox coordinates cannot be negative.")

        if x1 >= x2 or y1 >= y2:
            raise ValueError("bbox must satisfy x1 < x2 and y1 < y2.")

        return self


class OCRData(BaseModel):
    """OCR result for one picture-book page."""

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

    status: Literal["ok", "empty", "failed"]

    image_width: int = Field(
        ...,
        gt=0
    )

    image_height: int = Field(
        ...,
        gt=0
    )

    text_blocks: list[OCRTextBlock] = Field(
        default_factory=list
    )

    page_confidence: float = Field(
        ...,
        ge=0,
        le=1
    )

    elapsed_ms: int = Field(
        ...,
        ge=0
    )

    @model_validator(mode="after")
    def validate_page_data(self):
        expected_page_id = f"{self.book_id}_p{self.page_no:02d}"

        if self.page_id != expected_page_id:
            raise ValueError(
                "page_id must match book_id and page_no."
            )

        orders = [block.order for block in self.text_blocks]

        if sorted(orders) != list(range(1, len(orders) + 1)):
            raise ValueError(
                "Text block orders must start at 1 without gaps."
            )

        for block in self.text_blocks:
            if not block.block_id.startswith(self.page_id + "_t"):
                raise ValueError(
                    "block_id must belong to the current page."
                )

            x1, y1, x2, y2 = block.bbox

            if x2 > self.image_width or y2 > self.image_height:
                raise ValueError(
                    "bbox exceeds original image dimensions."
                )

        if self.status == "empty":
            if self.text_blocks:
                raise ValueError(
                    "Empty OCR result cannot contain text blocks."
                )

            if self.page_confidence != 0:
                raise ValueError(
                    "Empty OCR result must have page_confidence 0."
                )

        return self
