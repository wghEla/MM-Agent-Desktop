"""Mock Provider：脚本化响应序列，供内核/流水线测试与失败注入。

用法：
    script = MockScript([
        MockTurn(tool_calls=[("call_1", "fs.write", {"path": "...", "content": "..."})]),
        MockTurn(tool_calls=[("call_2", "python.run", {"path": "..."})]),
        MockTurn(text="done"),
    ])
    provider = MockProvider(script)
    # 失败注入：
    provider.queue_error(RateLimitError("429", retry_after_s=1))
    # 断言收到的消息形状：
    provider.turns[0].assert_saw_tool("fs.read")
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from mmagent.agent.errors import MMAgentError
from mmagent.providers.base import BaseProvider
from mmagent.providers.capabilities import CapabilitySet
from mmagent.providers.normalized import (
    NormalizedMessage,
    NormalizedResponse,
    NormalizedTool,
    NormalizedToolCall,
    StopReason,
    TextPart,
    Usage,
)


@dataclass
class MockTurn:
    """一个预设的模型回合。text 与 tool_calls 互斥使用（都可空 = 空回合）。"""

    text: str | None = None
    tool_calls: list[tuple[str, str, dict]] = field(default_factory=list)  # (id, name, args)
    stop_reason: StopReason | None = None
    usage: Usage = field(default_factory=Usage)
    saw_tool_calls: list[str] = field(default_factory=list)  # 断言用：本回合收到的历史里出现过的 tool 名

    def respond(
        self,
        messages: list[NormalizedMessage],
        tools: list[NormalizedTool],
    ) -> NormalizedResponse:
        # 记录断言面：本轮请求历史里出现过的 tool 结果名
        self.saw_tool_calls = [
            tc.name for m in messages for tc in (m.tool_calls or [])
        ]
        if self.tool_calls:
            return NormalizedResponse(
                message=NormalizedMessage(
                    role="assistant",
                    tool_calls=[
                        NormalizedToolCall(id=cid, name=name, arguments_json=json.dumps(args, ensure_ascii=False))
                        for cid, name, args in self.tool_calls
                    ],
                ),
                stop_reason=self.stop_reason or StopReason.TOOL_CALLS,
                usage=self.usage,
                model="mock-1",
                provider_protocol="mock",
            )
        return NormalizedResponse(
            message=NormalizedMessage(role="assistant", content=[TextPart(text=self.text or "")]),
            stop_reason=self.stop_reason or StopReason.END_TURN,
            usage=self.usage,
            model="mock-1",
            provider_protocol="mock",
        )

    def assert_saw_tool(self, name: str) -> None:
        assert name in self.saw_tool_calls, f"mock 期望历史里出现过工具调用 {name}，实际 {self.saw_tool_calls}"


@dataclass
class MockScript:
    turns: list[MockTurn]
    cursor: int = 0

    def next(self) -> MockTurn | None:
        if self.cursor >= len(self.turns):
            return None
        t = self.turns[self.cursor]
        self.cursor += 1
        return t


class MockProvider(BaseProvider):
    protocol = "mock"

    def __init__(self, script: MockScript, capabilities: CapabilitySet | None = None):
        self.script = script
        self._caps = capabilities or CapabilitySet(
            protocol="mock",
            tool_calling=True,
            image_input=True,
            streaming=False,
            reasoning_levels=frozenset({"low", "medium", "high", "xhigh"}),
        )
        self.pending_errors: list[MMAgentError] = []
        self.turns = script.turns

    def queue_error(self, err: MMAgentError) -> None:
        """在下一次 generate() 时抛出（失败注入）。"""
        self.pending_errors.append(err)

    async def generate(
        self,
        messages: list[NormalizedMessage],
        tools: list[NormalizedTool],
        *,
        model: str,
        reasoning: str | None = None,
        max_output_tokens: int | None = None,
        timeout_s: float = 300.0,
    ) -> NormalizedResponse:
        if self.pending_errors:
            raise self.pending_errors.pop(0)
        turn = self.script.next()
        if turn is None:
            raise AssertionError(
                "MockProvider 脚本耗尽：模型在预期之外又发起了回合"
                f"（最后一条消息 role={messages[-1].role if messages else None}）"
            )
        return turn.respond(messages, tools)

    async def test_connection(self) -> dict:
        return {"ok": True, "detail": "mock provider"}

    def capabilities(self) -> CapabilitySet:
        return self._caps
