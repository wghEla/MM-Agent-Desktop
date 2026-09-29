"""S1 strategic-tournament contracts."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class RouteCandidate(BaseModel):
    路线名: str
    方法: str
    方法理由: str = ""
    原型目标: str = ""


class RouteScoutQuestion(BaseModel):
    编号: int
    路线: list[RouteCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def nonempty_routes(self):
        if not self.路线:
            raise ValueError(f"问{self.编号} 没有候选路线")
        names = [x.路线名 for x in self.路线]
        if len(names) != len(set(names)):
            raise ValueError(f"问{self.编号} 路线名重复")
        return self


class RouteScout(BaseModel):
    问题清单: list[RouteScoutQuestion] = Field(default_factory=list)
    最难问题编号: int | None = None


class PrototypeEvidence(BaseModel):
    问题编号: int
    路线名: str
    脚本: str
    rc: int
    stdout_tail: str = ""
    stderr_tail: str = ""


class PrototypeResults(BaseModel):
    条目: list[PrototypeEvidence] = Field(default_factory=list)
