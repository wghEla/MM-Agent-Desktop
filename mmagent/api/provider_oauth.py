"""Compliant OAuth extension contract for provider authentication.

No provider is registered here by default. A future provider may opt in only when it
offers a documented third-party desktop OAuth/device flow and MM-Agent owns the client
registration it uses.

This module intentionally contains no browser-cookie, first-party-client impersonation,
or consumer-session-token integration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

OAuthFlow = Literal["authorization_code_pkce", "device_code"]


@dataclass(frozen=True)
class OAuthStartResult:
    """Non-secret information that may safely be shown to the desktop UI."""

    flow: OAuthFlow
    verification_uri: str
    user_code: str | None = None
    expires_in_s: int | None = None
    interval_s: int | None = None
    state_ref: str | None = None


@dataclass(frozen=True)
class OAuthCredentialResult:
    """Sensitive completion result.

    The credential must be handed directly to CredentialStore by the sidecar; it must
    never be returned to the UI, persisted in SQLite, logged, or included in evidence.
    """

    credential: str = field(repr=False)
    metadata: dict[str, Any] = field(default_factory=dict)


class ProviderOAuthAdapter(Protocol):
    provider_id: str
    flow: OAuthFlow

    async def start(self) -> OAuthStartResult: ...

    async def complete(self, state_ref: str | None = None) -> OAuthCredentialResult: ...

    async def revoke(self, credential: str) -> None: ...


class OAuthAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ProviderOAuthAdapter] = {}

    def register(self, adapter: ProviderOAuthAdapter) -> None:
        provider_id = adapter.provider_id.strip()
        if not provider_id:
            raise ValueError("OAuth adapter provider_id must be non-empty")
        if provider_id in self._adapters:
            raise ValueError(f"OAuth adapter already registered: {provider_id}")
        self._adapters[provider_id] = adapter

    def has(self, provider_id: str) -> bool:
        return provider_id in self._adapters

    def get(self, provider_id: str) -> ProviderOAuthAdapter:
        try:
            return self._adapters[provider_id]
        except KeyError as exc:
            raise LookupError(f"OAuth adapter not registered: {provider_id}") from exc

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


DEFAULT_OAUTH_REGISTRY = OAuthAdapterRegistry()
