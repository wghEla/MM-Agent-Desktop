"""S5 independent-review artifact contracts.

The parser intentionally accepts a few historical envelope aliases, but the
fields consumed by the Issue Ledger are validated before a review task can be
sealed as successful.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator


class ReviewOpinion(BaseModel):
    model_config = ConfigDict(extra="allow")

    级别: Literal["硬伤", "正确性", "叙述", "版式"]
    目标: Literal["算", "图", "文"]
    定位: str = Field(min_length=1)
    问题: str = Field(min_length=1)
    指令: str = Field(min_length=1)
    验收: str = Field(min_length=1)
    对应: str = ""
    来源: str = ""

    @field_validator("定位", "问题", "指令", "验收")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空白")
        return value


class ReviewVerdict(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    generation: int = Field(ge=0)
    裁定: Literal["已消解", "未消解"]
    理由: str = ""

    @field_validator("id")
    @classmethod
    def nonblank_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("id 不能为空白")
        return value


class ReviewEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    意见: list[ReviewOpinion] | ReviewOpinion | None = None
    最高优先级修改: list[ReviewOpinion] | ReviewOpinion | None = None
    裁定: list[ReviewVerdict] | ReviewVerdict | None = None
    逐条裁定: list[ReviewVerdict] | ReviewVerdict | None = None
    逐项: list[ReviewVerdict] | ReviewVerdict | None = None
    总分: float | None = Field(default=None, ge=0.0, le=10.0)
    分数: float | None = Field(default=None, ge=0.0, le=10.0)
    相对判断: Literal["更好", "持平", "更差"] | None = None
    相对: Literal["更好", "持平", "更差"] | None = None

    @model_validator(mode="before")
    @classmethod
    def require_recognized_consumer_field(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        recognized = {
            "意见",
            "最高优先级修改",
            "裁定",
            "逐条裁定",
            "逐项",
            "总分",
            "分数",
            "相对判断",
            "相对",
        }
        if not any(key in value for key in recognized):
            raise ValueError("审稿 envelope 缺少任何可消费字段")
        return value


class ReviewArtifact(RootModel[ReviewEnvelope | list[ReviewOpinion]]):
    """S5 review carrier accepted by the backward-compatible parser."""
