"""S2 合同：假设台账 / 结果声明 / 红队报告 / 仲裁 / 换版清单。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AssumptionItem(BaseModel):
    """假设台账单条。"""

    假设号: str  # 如 "A1-1"
    内容: str
    生效位置: str  # 正文哪一节用到此假设
    依据: str = ""


class AssumptionLedger(BaseModel):
    """假设台账（建模师产物，每问一份）。"""

    问题编号: int
    条目: list[AssumptionItem] = Field(default_factory=list)


class ResultDeclaration(BaseModel):
    """结果声明（解读师产物，Frozen Truth carrier）。"""

    问题编号: int
    核心指标: dict[str, float] = Field(default_factory=dict)
    口径说明: str = ""  # 四段：数据/处理/统计/单位
    自检指标: dict[str, float] = Field(default_factory=dict)
    置信: str = ""


class RedTeamDiscrepancy(BaseModel):
    """红队分歧明细单条。"""

    键: str
    声明值: float | None = None
    复算值: float | None = None
    相对差: float = 0.0
    类型: str = "数值"  # 数值 | 口径


class RedTeamReport(BaseModel):
    """红队报告（围栏 schema）。"""

    问题编号: int
    复算方式: str = ""
    复算指标: list[dict[str, Any]] = Field(default_factory=list)  # [{键, 声明口径, 独立口径}]
    口径说明: str = ""
    口径对照: list[dict[str, str]] = Field(default_factory=list)  # P1 两套口径
    结论: str  # 对齐 | 不齐
    分歧明细: list[RedTeamDiscrepancy] = Field(default_factory=list)


class ArbitrationItem(BaseModel):
    """仲裁台账单条。"""

    条目: str
    定责: str  # 建模 | 红队 | 口径差异
    消解状态: str = "待处理"  # 待处理 | 已消解 | 已解释
    消解证据: str = ""
    应改方: str = ""  # 建模 | 红队


class ArbitrationLedger(BaseModel):
    """仲裁台账（解读师产物）。"""

    问题编号: int
    逐项: list[ArbitrationItem] = Field(default_factory=list)


class ChangeManifestItem(BaseModel):
    """换版清单单条。"""

    键: str
    旧值: str
    新值: str
    出现处: list[str] = Field(default_factory=list)  # 文件:位置


class ChangeManifest(BaseModel):
    """换版清单（建模师重算后必产，P3）。"""

    问题编号: int
    条目: list[ChangeManifestItem] = Field(default_factory=list)


from typing import Any  # noqa: E402
