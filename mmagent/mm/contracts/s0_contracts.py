"""S0 合同层：题面契约 / 数据档案 / 需求追踪矩阵 / 典型答卷预测。

这些 Pydantic 模型是 schema 唯一事实来源（总方案 §23；原 Skill 契约表思想）。
消费者只能 import，不得复写字段（contract tests 强制）。
字段名保留中文（与原 Skill 交付习惯一致，见 ARCHITECTURE §7）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

PROBLEM_CONTRACT_REQUIRED_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "赛题",
    "标题",
    "问题",
    "硬约束清单",
    "歧义裁定",
    "附件清单",
)

DATA_ARCHIVE_REQUIRED_TOP_LEVEL_KEYS: tuple[str, ...] = ("条目",)



class RequirementItem(BaseModel):
    """单条需求（销号依据，最小可验收粒度）。"""

    需求号: str  # 格式 {问号}-{序号}，如 "1-1"
    内容: str
    评分点推测: str = ""  # 评委会找什么证据


class AmbiguityItem(BaseModel):
    """歧义裁定。"""

    条目: str
    候选解释: list[str] = Field(default_factory=list)
    裁定: str  # 必须选定一个，不许含糊
    理由: str = ""
    影响范围: str = ""


class HardConstraint(BaseModel):
    """硬约束。"""

    约束号: str
    内容: str
    出处: str = ""


class AttachmentInfo(BaseModel):
    """附件清单条目。"""

    文件: str
    内容概述: str = ""
    关联问题: list[int] = Field(default_factory=list)


class ProblemEntry(BaseModel):
    """单问结构化题意。"""

    编号: int
    原文摘录: str
    解读: str
    可交付物: list[str] = Field(default_factory=list)
    需求条目: list[RequirementItem] = Field(default_factory=list)


class ProblemContract(BaseModel):
    """题面契约（S0 读题官主产物，全流程唯一权威题意来源）。"""

    赛题: str
    标题: str = ""
    问题: list[ProblemEntry] = Field(default_factory=list)
    硬约束清单: list[HardConstraint] = Field(default_factory=list)
    歧义裁定: list[AmbiguityItem] = Field(default_factory=list)
    附件清单: list[AttachmentInfo] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_g0_required_semantics(self) -> ProblemContract:
        """Reject producer artifacts that are guaranteed to fail G0."""
        if not self.问题:
            raise ValueError("问题不能为空")
        for prob in self.问题:
            if not prob.原文摘录.strip():
                raise ValueError(f"问{prob.编号} 原文摘录不能为空")
            if not prob.解读.strip():
                raise ValueError(f"问{prob.编号} 解读不能为空")
            if not prob.需求条目:
                raise ValueError(f"问{prob.编号} 需求条目不能为空")
        for idx, ambiguity in enumerate(self.歧义裁定, 1):
            if not ambiguity.裁定.strip():
                raise ValueError(f"歧义裁定第{idx}条 裁定不能为空")
            if not ambiguity.理由.strip():
                raise ValueError(f"歧义裁定第{idx}条 理由不能为空")
        return self

    @model_validator(mode="after")
    def check_requirement_ids(self) -> ProblemContract:
        """需求号格式与连续性（G0 判据）。"""
        for prob in self.问题:
            nums: list[int] = []
            prefix = f"{prob.编号}-"
            for req in prob.需求条目:
                if not req.需求号.startswith(prefix):
                    raise ValueError(
                        f"问{prob.编号} 需求号 {req.需求号!r} 不以前缀 {prefix!r} 开头"
                    )
                suffix = req.需求号[len(prefix):]
                if not suffix.isdigit():
                    raise ValueError(f"问{prob.编号} 需求号 {req.需求号!r} 序号非数字")
                nums.append(int(suffix))
            if nums and sorted(nums) != list(range(1, len(nums) + 1)):
                raise ValueError(
                    f"问{prob.编号} 需求号不连续: {sorted(nums)}"
                )
        return self


class DataArchiveEntry(BaseModel):
    """数据档案单条：一个附件文件的结构化描述。"""

    文件: str
    类型: str = ""  # xlsx | csv | pdf | docx | txt | 其他
    行数: int | None = None
    列数: int | None = None
    列说明: list[dict[str, str]] = Field(default_factory=list)  # [{列名, 类型, 缺失, 备注}]
    异常: list[str] = Field(default_factory=list)
    概述: str = ""


class DataArchive(BaseModel):
    """数据档案（S0 读题官产物：附件体检结果）。"""

    条目: list[DataArchiveEntry] = Field(default_factory=list)


class RequirementMatrixItem(BaseModel):
    """需求追踪矩阵条目（S0.4 机械生成，S5 审稿销号用）。"""

    需求号: str
    问题编号: int
    内容: str
    状态: str = "未落位"  # 未落位 | 已落位
    章节: str = ""
    图表: str = ""
    关键数字: str = ""


class RouteEntry(BaseModel):
    """锦标赛单条路线。"""

    路线名: str
    方法: str
    方法理由: str = ""
    原型脚本: str = ""  # 求解/问题N/原型_路线名.py
    关键假设: list[str] = Field(default_factory=list)


class PlanEntry(BaseModel):
    """单问计划（规划师产物，计划.json 的问题清单条目）。"""

    编号: int
    标题: str = ""
    输入: list[str] = Field(default_factory=list)
    输出: list[str] = Field(default_factory=list)
    主方法: str = ""
    备选方法: list[str] = Field(default_factory=list)
    方法理由: str = ""
    本题定制改造: str = ""
    验证方案: dict[str, str] = Field(default_factory=dict)
    依赖问题: list[int] = Field(default_factory=list)
    蜂群变体: list[dict[str, str]] = Field(default_factory=list)
    锦标赛: dict[str, str] = Field(default_factory=dict)  # {参赛路线: [], 优胜: "", 依据: ""}


class PlanDocument(BaseModel):
    """计划.json 全文档（S1 规划师定稿产物）。"""

    问题清单: list[PlanEntry] = Field(default_factory=list)
    论文结构: list[dict[str, Any_]] = Field(default_factory=list)  # 逐章结构
    叙事主线: str = ""
    偏离点: list[dict[str, str]] = Field(default_factory=list)


# 类型别名（避免与 typing.Any 冲突）
from typing import Any as Any_  # noqa: E402
