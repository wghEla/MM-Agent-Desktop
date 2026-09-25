"""Late-stage page-review and publication-review contracts."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator


class PageReviewIssue(BaseModel):
    model_config = ConfigDict(extra="allow")

    页: int = Field(ge=1)
    目标: Literal["图", "文"]
    严重度: int | str
    问题: str = Field(min_length=1)
    修改指令: str = Field(min_length=1)
    定位: str = ""

    @field_validator("问题", "修改指令")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空白")
        return value

    @field_validator("严重度")
    @classmethod
    def severity_present(cls, value: int | str) -> int | str:
        if isinstance(value, str) and not value.strip():
            raise ValueError("严重度不能为空白")
        return value


class PageReviewEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    页问题: list[PageReviewIssue] | PageReviewIssue | None = None
    问题: list[PageReviewIssue] | PageReviewIssue | None = None
    美观分: float | None = Field(default=None, ge=0.0, le=10.0)

    @model_validator(mode="before")
    @classmethod
    def require_issue_container(cls, value: Any) -> Any:
        if isinstance(value, dict) and not any(key in value for key in ("页问题", "问题")):
            raise ValueError("页审 envelope 必须显式包含 页问题 或 问题")
        return value


class PageReviewArtifact(RootModel[PageReviewEnvelope | list[PageReviewIssue]]):
    """Carrier used by S5b beautification and S6 final page review."""


class PublicationReviewVerdict(BaseModel):
    model_config = ConfigDict(extra="allow")

    通过: bool
    依据版本: str = Field(min_length=1)
    页码: list[int] | int | str | None = None

    @field_validator("依据版本")
    @classmethod
    def nonblank_version(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("依据版本不能为空白")
        return value
