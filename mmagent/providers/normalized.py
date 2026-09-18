"""协议无关的归一化类型（Normalized*）。

所有 Adapter（OpenAI Responses / OpenAI Chat / Anthropic Messages / Gemini /
OpenAI-Compatible）的输入输出都归一到这组类型；Agent Runtime 只认识这里。
"""
from __future__ import annotations

import enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ContentPartType(enum.StrEnum):
    TEXT = "text"
    IMAGE = "image"


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImagePart(BaseModel):
    type: Literal["image"] = "image"
    b64: str
    media_type: str = "image/png"


ContentPart = TextPart | ImagePart


class NormalizedToolCall(BaseModel):
    id: str
    name: str
    arguments_json: str


class NormalizedMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: list[ContentPart] = Field(default_factory=list)
    tool_calls: list[NormalizedToolCall] = Field(default_factory=list)
    # role == "tool" 时：本条消息对应哪个 tool call
    tool_call_id: str | None = None
    name: str | None = None

    @property
    def text(self) -> str:
        return "".join(p.text for p in self.content if isinstance(p, TextPart))


class NormalizedTool(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class StopReason(enum.StrEnum):
    END_TURN = "end_turn"
    TOOL_CALLS = "tool_calls"
    MAX_TOKENS = "max_tokens"
    CANCELLED = "cancelled"


class NormalizedResponse(BaseModel):
    message: NormalizedMessage
    stop_reason: StopReason
    usage: Usage = Field(default_factory=Usage)
    model: str = ""
    provider_protocol: str = ""
    raw: dict[str, Any] | None = None
