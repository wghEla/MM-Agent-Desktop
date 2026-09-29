"""S4 paper-stage artifact contracts."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, RootModel, field_validator


class RequirementCoverageItem(BaseModel):
    """Evidence that one requirement is actually answered in the paper."""

    需求号: str = Field(min_length=1)
    章节: str = Field(min_length=1)
    证据: str = Field(min_length=1)
    图表: str = ""
    关键数字: str = ""

    @field_validator("需求号", "章节", "证据")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空白")
        return value


class RequirementCoverageDocument(RootModel[list[RequirementCoverageItem]]):
    """Top-level list written by the S4 draft leg."""


class ChapterReview(BaseModel):
    """Chapter-review envelope consumed by S4 retention logic."""

    总分: float = Field(ge=0.0, le=10.0)
    相对判断: Literal["更好", "持平", "更差"] | None = None
    问题: list[Any] = Field(default_factory=list)


class BlindReaderReview(BaseModel):
    """Closed-book reader score consumed by the S4 gate."""

    读者分: float = Field(ge=0.0, le=10.0)
    卡住: list[Any] = Field(default_factory=list)


class AbstractRestatementVerdict(BaseModel):
    """Closed-book abstract restatement verdict used by S4/S5a."""

    通过: bool
    分数: float = Field(ge=0.0, le=10.0)
