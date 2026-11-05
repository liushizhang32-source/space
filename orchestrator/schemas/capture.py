
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, HttpUrl, field_validator

from .common import APIResponse


class CaptureData(BaseModel):
    """
    Data returned after a page image is uploaded.
    """

    book_id: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9]{3,11}$",
        description="Unique ID of the picture book."
    )

    page_id: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9]{3,11}_p\d{2}$",
        description="Unique ID of the uploaded page."
    )

    page_no: int = Field(
        ...,
        ge=1,
        description="Page number in the picture book."
    )

    preview_url: str = Field(
        ...,
        description="URL of the stored page preview image."
    )

    image_width: int = Field(
        ...,
        gt=0,
        description="Original image width in pixels."
    )

    image_height: int = Field(
        ...,
        gt=0,
        description="Original image height in pixels."
    )

    @field_validator("preview_url")
    @classmethod
    def validate_preview_url(cls, value: str) -> str:
        # Validate without replacing the original string with a normalized URL.
        HttpUrl(value)
        if not urlsplit(value).hostname:
            raise ValueError("preview_url must contain a valid host.")
        return value


class CaptureResponse(APIResponse[CaptureData]):
    """
    Standard response for the capture API.
    """
    pass
