"""Provider 基类：协议适配器的最小接口。

v0.1.0 只要求接口形状 + mock；五个真实协议适配器在 v0.3.0 实现
（offline contract-tested，无真实 key 时不声称 real-provider-tested）。
"""
from __future__ import annotations

import abc

from mmagent.providers.capabilities import CapabilitySet
from mmagent.providers.normalized import (
    NormalizedMessage,
    NormalizedResponse,
    NormalizedTool,
)


class BaseProvider(abc.ABC):
    """异步生成接口。实现必须：
    - 尊重 timeout_s 与 cancel（取消时抛 TaskCancelled 或返回 stop_reason=CANCELLED）；
    - 把各协议错误归一为 mmagent.agent.errors.ProviderError 家族；
    - 不在任何异常消息/日志里泄漏 api key。
    """

    protocol: str

    def resolve_model(self, requested: str) -> str:
        """Resolve a task-level model placeholder to the provider's effective model."""
        return requested

    @abc.abstractmethod
    async def generate(
        self,
        messages: list[NormalizedMessage],
        tools: list[NormalizedTool],
        *,
        model: str,
        reasoning: str | None = None,
        max_output_tokens: int | None = None,
        timeout_s: float = 300.0,
    ) -> NormalizedResponse: ...

    @abc.abstractmethod
    async def test_connection(self) -> dict:
        """设置页 Test Connection。返回 {"ok": bool, "detail": str}。"""

    @abc.abstractmethod
    def capabilities(self) -> CapabilitySet: ...


class ModelBoundProvider(BaseProvider):
    """Bind a concrete model to an existing protocol adapter.

    Pipeline roles may use the historical "mock" placeholder.  The bound
    provider converts that placeholder to the user's configured model while
    preserving explicit non-placeholder model requests.
    """

    def __init__(self, inner: BaseProvider, model: str):
        if not model.strip():
            raise ValueError("bound model must be non-empty")
        self.inner = inner
        self.model = model.strip()
        self.protocol = inner.protocol

    def resolve_model(self, requested: str) -> str:
        value = (requested or "").strip()
        return self.model if value in ("", "mock") else value

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
        return await self.inner.generate(
            messages,
            tools,
            model=self.resolve_model(model),
            reasoning=reasoning,
            max_output_tokens=max_output_tokens,
            timeout_s=timeout_s,
        )

    async def test_connection(self) -> dict:
        return await self.inner.test_connection()

    def capabilities(self) -> CapabilitySet:
        return self.inner.capabilities()
