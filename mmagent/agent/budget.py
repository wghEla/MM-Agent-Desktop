"""预算护栏（v0.1 骨架）。

复现原 Skill MAX_LEGS / MAX_HOURS 语义：
- 腿数/用时到顶 → BudgetExhausted，编排层转应急收尾，不算任务失败；
- v0.5 起由编排层在 S2 逐问检查（上游教训：只查阶段级等于没查）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from mmagent.agent.errors import BudgetExhausted


@dataclass
class Budget:
    max_legs: int = 600
    max_hours: float = 40.0
    _legs: int = field(default=0, repr=False)
    _start: float = field(default_factory=time.monotonic, repr=False)

    def add_leg(self, n: int = 1) -> None:
        self._legs += n

    @property
    def legs(self) -> int:
        return self._legs

    @property
    def elapsed_hours(self) -> float:
        return (time.monotonic() - self._start) / 3600

    def check(self) -> None:
        if self._legs >= self.max_legs:
            raise BudgetExhausted(f"腿数到顶: {self._legs}/{self.max_legs}")
        if self.elapsed_hours >= self.max_hours:
            raise BudgetExhausted(f"用时到顶: {self.elapsed_hours:.1f}h/{self.max_hours}h")

    def ok(self) -> bool:
        try:
            self.check()
            return True
        except BudgetExhausted:
            return False
