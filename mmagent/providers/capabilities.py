"""能力声明（CapabilitySet）。

原则：Provider 不支持的能力必须如实声明 unsupported，不允许伪装
（reasoning 档位不支持时按普通请求执行并记录差异，不伪造）。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CapabilitySet:
    protocol: str
    tool_calling: bool = True
    image_input: bool = False
    streaming: bool = False
    reasoning_levels: frozenset[str] = field(default_factory=frozenset)  # e.g. {"low","medium","high","xhigh"}
    max_output_tokens_limit: int | None = None

    def supports_reasoning(self, level: str | None) -> bool:
        if not level:
            return True
        return level in self.reasoning_levels

    def describe(self) -> dict:
        return {
            "protocol": self.protocol,
            "tool_calling": self.tool_calling,
            "image_input": self.image_input,
            "streaming": self.streaming,
            "reasoning_levels": sorted(self.reasoning_levels),
            "max_output_tokens_limit": self.max_output_tokens_limit,
        }
