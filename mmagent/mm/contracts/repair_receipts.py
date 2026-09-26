"""Repair receipt schemas — 回执在被 seal 前必须过 Pydantic 校验。

被程序消费的字段：
- issue_id: 对应台账条目
- 改动: 做了什么修改
- receipt_id: 幂等键（UUID or caller-provided）
- 证据: 文件:行 或 新数值

非消费字段（人类存档可选）不强制 schema 化。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RepairReceipt(BaseModel):
    """S5 repair lane 回执（write back to ledger before seal）。"""

    id: str  # issue id, e.g. "审-1-01"
    改动: str = Field(min_length=1, max_length=400)
    证据: str = Field(default="", max_length=300)
    receipt_id: str = Field(default="", max_length=64)
    generation: int = Field(default=0, ge=0)


class BeautyReceipt(BaseModel):
    """S5b beauty lane 回执。"""

    id: str
    目标: str = Field(default="文")  # 图 | 文
    改动: str = Field(min_length=1, max_length=400)
    证据: str = Field(default="", max_length=300)
    receipt_id: str = Field(default="", max_length=64)


class G5RepairReceipt(BaseModel):
    """G5 publication gate repair receipt。"""

    id: str
    目标: str = Field(default="文")  # 算 | 图 | 文
    改动: str = Field(min_length=1, max_length=400)
    证据: str = Field(default="", max_length=300)
    receipt_id: str = Field(default="", max_length=64)


class S6TerminalReceipt(BaseModel):
    """S6 final page review terminal receipt。"""

    id: str
    页码: int = Field(ge=1)
    改动: str = Field(min_length=1, max_length=400)
    receipt_id: str = Field(default="", max_length=64)
