from __future__ import annotations

import pytest

from mmagent.api.provider_oauth import (
    OAuthAdapterRegistry,
    OAuthCredentialResult,
    OAuthStartResult,
)


class FakeOAuthAdapter:
    provider_id = "fake"
    flow = "device_code"

    async def start(self):
        return OAuthStartResult(
            flow="device_code",
            verification_uri="https://example.invalid/device",
            user_code="ABCD-EFGH",
        )

    async def complete(self, state_ref=None):
        return OAuthCredentialResult(
            credential="secret-oauth-token",
            metadata={"account": "test"},
        )

    async def revoke(self, credential):
        return None


def test_oauth_registry_is_explicit_and_rejects_duplicates() -> None:
    registry = OAuthAdapterRegistry()
    assert registry.provider_ids() == ()
    assert registry.has("fake") is False

    adapter = FakeOAuthAdapter()
    registry.register(adapter)
    assert registry.has("fake") is True
    assert registry.get("fake") is adapter
    assert registry.provider_ids() == ("fake",)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeOAuthAdapter())


def test_oauth_registry_missing_provider_fails_closed() -> None:
    registry = OAuthAdapterRegistry()
    with pytest.raises(LookupError, match="not registered"):
        registry.get("missing")


def test_oauth_credential_repr_never_contains_secret() -> None:
    result = OAuthCredentialResult(
        credential="secret-oauth-token",
        metadata={"account": "test"},
    )
    rendered = repr(result)
    assert "secret-oauth-token" not in rendered
    assert "account" in rendered
