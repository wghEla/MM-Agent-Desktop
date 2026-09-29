"""S6 retrospective / feedback ledger schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RetrospectiveBottleneck(BaseModel):
    """瓶颈环节。"""

    环节: str  # e.g. "S2 红队仲裁"
    次数: int = Field(ge=0)
    耗时占比: float = Field(default=0.0, ge=0.0, le=1.0)
    说明: str = ""


class RetrospectiveRuleSuggestion(BaseModel):
    """规则库修改建议。"""

    建议编号: str  # e.g. "R1"
    类型: str = ""  # 提示词 | 链路 | 阈值
    现状: str = ""
    建议: str = ""
    预期收益: str = ""


class RetrospectiveReport(BaseModel):
    """复盘报告（S6 复盘官产物）。"""

    总评: str = ""
    瓶颈环节: list[RetrospectiveBottleneck] = Field(default_factory=list)
    规则库修改建议: list[RetrospectiveRuleSuggestion] = Field(default_factory=list)
    回流账: dict[str, int] = Field(default_factory=dict)  # {类型: 次数}
    质量指标: dict[str, float] = Field(default_factory=dict)  # {指标: 值}
    降级放行: list[dict[str, str]] = Field(default_factory=list)
    已知限制: list[str] = Field(default_factory=list)


class RunMetrics(BaseModel):
    """Run metrics（流水线自动统计）。"""

    total_legs: int = Field(default=0, ge=0)
    total_tasks: int = Field(default=0, ge=0)
    total_tool_calls: int = Field(default=0, ge=0)
    total_duration_s: float = Field(default=0.0, ge=0.0)
    gates_passed: int = Field(default=0, ge=0)
    gates_failed: int = Field(default=0, ge=0)
    rework_count: int = Field(default=0, ge=0)
    escalation_count: int = Field(default=0, ge=0)
    downgrade_count: int = Field(default=0, ge=0)
    fuse_count: int = Field(default=0, ge=0)
    compile_count: int = Field(default=0, ge=0)
    provider_errors: int = Field(default=0, ge=0)
    rate_limits: int = Field(default=0, ge=0)
