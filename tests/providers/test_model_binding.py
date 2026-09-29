from __future__ import annotations

from mmagent.providers.base import BaseProvider, ModelBoundProvider
from mmagent.providers.capabilities import CapabilitySet
from mmagent.providers.normalized import (
    NormalizedMessage,
    NormalizedResponse,
    StopReason,
    TextPart,
)


class RecordingProvider(BaseProvider):
    protocol = "recording"

    def __init__(self):
        self.models: list[str] = []

    async def generate(
        self, messages, tools, *, model, reasoning=None,
        max_output_tokens=None, timeout_s=300.0,
    ):
        self.models.append(model)
        return NormalizedResponse(
            message=NormalizedMessage(role="assistant", content=[TextPart(text="done")]),
            stop_reason=StopReason.END_TURN,
            model=model,
            provider_protocol=self.protocol,
        )

    async def test_connection(self) -> dict:
        return {"ok": True, "detail": "recording"}

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(protocol=self.protocol, tool_calling=True)


def test_bound_provider_resolves_historical_mock_placeholder() -> None:
    inner = RecordingProvider()
    bound = ModelBoundProvider(inner, "actual-model")
    assert bound.resolve_model("mock") == "actual-model"
    assert bound.resolve_model("") == "actual-model"
    assert bound.resolve_model("explicit-model") == "explicit-model"


def test_unbound_provider_keeps_requested_model() -> None:
    provider = RecordingProvider()
    assert provider.resolve_model("mock") == "mock"
