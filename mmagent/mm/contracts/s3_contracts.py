"""S3 figure-review artifact contracts."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FigureReview(BaseModel):
    """One visual-review batch verdict consumed by S3."""

    总分: float = Field(ge=0.0, le=10.0)
    问题: list[Any] = Field(default_factory=list)
