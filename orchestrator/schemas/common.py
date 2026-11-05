
from typing import Generic, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """
    Unified API response format.
    """

    code: int = Field(
        default=0,
        description="Response status code. 0 means success."
    )

    msg: str = Field(
        default="ok",
        description="Response message."
    )

    data: T | None = Field(
        default=None,
        description="Response data."
    )

    trace_id: str = Field(
        ...,
        pattern=r"^tr_[0-9A-HJKMNP-TV-Z]{26}$",
        description="Unique request tracking ID."
    )
