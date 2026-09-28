"""Provider/profile CRUD and adapter construction for the desktop settings UI."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from mmagent.api.provider_catalog import capability_descriptor
from mmagent.providers.anthropic_messages import AnthropicMessagesProvider
from mmagent.providers.base import BaseProvider, ModelBoundProvider
from mmagent.providers.gemini import GeminiProvider
from mmagent.providers.openai_chat import OpenAIChatProvider
from mmagent.providers.openai_compatible import OpenAICompatibleProvider
from mmagent.providers.openai_responses import OpenAIResponsesProvider
from mmagent.runtime.credentials import CredentialStore
from mmagent.state import repositories
from mmagent.state.db import Database

SUPPORTED_PROTOCOLS = frozenset(
    {
        "openai_chat",
        "openai_responses",
        "anthropic_messages",
        "gemini",
        "openai_compatible",
    }
)


@dataclass(frozen=True)
class ProviderProfile:
    provider_id: str
    model_profile_id: str
    name: str
    protocol: str
    base_url: str
    api_key_ref: str | None
    model: str
    reasoning: str | None
    max_output_tokens: int | None
    timeout_s: int | None
    extra: dict[str, Any]


def _credential_ref(provider_id: str) -> str:
    return f"provider/{provider_id}/api-key"


def _validate_base_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if not value:
        raise ValueError("base_url must be non-empty")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base_url must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(
            "base_url must not contain credentials; use Windows Credential Manager"
        )
    if parsed.query or parsed.fragment:
        raise ValueError(
            "base_url must not contain query/fragment credentials or parameters"
        )
    return value


_SECRET_HEADER_NAMES = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "cookie",
        "set-cookie",
    }
)


def _validate_extra_secret_boundary(extra: dict[str, Any] | None) -> dict[str, Any]:
    value = dict(extra or {})
    raw_headers = value.get("extra_headers")
    if raw_headers is None:
        return value
    if not isinstance(raw_headers, dict):
        raise ValueError("extra_headers must be an object")
    forbidden = sorted(
        str(name)
        for name in raw_headers
        if str(name).strip().lower() in _SECRET_HEADER_NAMES
    )
    if forbidden:
        raise ValueError(
            "secret-bearing extra_headers are forbidden; use Windows Credential Manager: "
            + ", ".join(forbidden)
        )
    return value


def create_provider_profile(
    db: Database,
    credentials: CredentialStore,
    *,
    name: str,
    protocol: str,
    base_url: str,
    model: str,
    api_key: str | None = None,
    reasoning: str | None = None,
    max_output_tokens: int | None = None,
    timeout_s: int | None = 300,
    extra: dict[str, Any] | None = None,
) -> ProviderProfile:
    protocol = protocol.strip()
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError(f"unsupported provider protocol: {protocol}")
    if not name.strip():
        raise ValueError("provider name must be non-empty")
    base_url = _validate_base_url(base_url)
    if not model.strip():
        raise ValueError("model must be non-empty")
    if timeout_s is not None and timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    if max_output_tokens is not None and max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be positive")

    extra = _validate_extra_secret_boundary(extra)

    provider_id = repositories.new_id("provider")
    model_profile_id = repositories.new_id("model")
    ref = _credential_ref(provider_id) if api_key else None
    if ref is not None:
        credentials.set(ref, api_key or "")

    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO providers(id, name, protocol, base_url, api_key_ref, extra_json, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    provider_id,
                    name.strip(),
                    protocol,
                    base_url,
                    ref,
                    json.dumps(extra, ensure_ascii=False),
                    repositories.now_iso(),
                ),
            )
            conn.execute(
                "INSERT INTO model_profiles(id, provider_id, model, reasoning,"
                " max_output_tokens, timeout_s, extra_json) VALUES (?,?,?,?,?,?,?)",
                (
                    model_profile_id,
                    provider_id,
                    model.strip(),
                    reasoning,
                    max_output_tokens,
                    timeout_s,
                    "{}",
                ),
            )
    except BaseException:
        if ref is not None:
            credentials.delete(ref)
        raise

    return get_provider_profile(db, model_profile_id)


def get_provider_profile(db: Database, model_profile_id: str) -> ProviderProfile:
    row = db.query_one(
        "SELECT p.id AS provider_id, mp.id AS model_profile_id, p.name, p.protocol,"
        " p.base_url, p.api_key_ref, p.extra_json, mp.model, mp.reasoning,"
        " mp.max_output_tokens, mp.timeout_s"
        " FROM model_profiles mp JOIN providers p ON p.id = mp.provider_id"
        " WHERE mp.id = ?",
        (model_profile_id,),
    )
    if row is None:
        raise LookupError(f"provider profile 不存在: {model_profile_id}")
    return ProviderProfile(
        provider_id=row["provider_id"],
        model_profile_id=row["model_profile_id"],
        name=row["name"],
        protocol=row["protocol"],
        base_url=row["base_url"],
        api_key_ref=row["api_key_ref"],
        model=row["model"],
        reasoning=row["reasoning"],
        max_output_tokens=row["max_output_tokens"],
        timeout_s=row["timeout_s"],
        extra=json.loads(row["extra_json"] or "{}"),
    )


def list_provider_profiles(db: Database) -> list[ProviderProfile]:
    rows = db.query("SELECT id FROM model_profiles ORDER BY rowid")
    return [get_provider_profile(db, row["id"]) for row in rows]


def update_provider_profile(
    db: Database,
    *,
    model_profile_id: str,
    name: str,
    protocol: str,
    base_url: str,
    model: str,
    reasoning: str | None = None,
    max_output_tokens: int | None = None,
    timeout_s: int | None = 300,
    extra: dict[str, Any] | None = None,
) -> ProviderProfile:
    current = get_provider_profile(db, model_profile_id)
    extra = _validate_extra_secret_boundary(extra)
    protocol = protocol.strip()
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError(f"unsupported provider protocol: {protocol}")
    if not name.strip():
        raise ValueError("provider name must be non-empty")
    base_url = _validate_base_url(base_url)
    if not model.strip():
        raise ValueError("model must be non-empty")
    if timeout_s is not None and timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    if max_output_tokens is not None and max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be positive")

    with db.transaction() as conn:
        conn.execute(
            "UPDATE providers SET name = ?, protocol = ?, base_url = ?, extra_json = ?"
            " WHERE id = ?",
            (
                name.strip(),
                protocol,
                base_url,
                json.dumps(extra, ensure_ascii=False),
                current.provider_id,
            ),
        )
        conn.execute(
            "UPDATE model_profiles SET model = ?, reasoning = ?, max_output_tokens = ?,"
            " timeout_s = ? WHERE id = ?",
            (
                model.strip(),
                reasoning,
                max_output_tokens,
                timeout_s,
                model_profile_id,
            ),
        )
    return get_provider_profile(db, model_profile_id)


def set_provider_credential(
    db: Database,
    credentials: CredentialStore,
    model_profile_id: str,
    api_key: str,
) -> ProviderProfile:
    if not api_key:
        raise ValueError("api_key must be non-empty")
    profile = get_provider_profile(db, model_profile_id)
    ref = profile.api_key_ref or _credential_ref(profile.provider_id)

    credentials.set(ref, api_key)
    if profile.api_key_ref is None:
        try:
            with db.transaction() as conn:
                conn.execute(
                    "UPDATE providers SET api_key_ref = ? WHERE id = ?",
                    (ref, profile.provider_id),
                )
        except BaseException:
            credentials.delete(ref)
            raise
    return get_provider_profile(db, model_profile_id)


def clear_provider_credential(
    db: Database,
    credentials: CredentialStore,
    model_profile_id: str,
) -> ProviderProfile:
    profile = get_provider_profile(db, model_profile_id)
    if profile.api_key_ref is None:
        return profile
    with db.transaction() as conn:
        conn.execute(
            "UPDATE providers SET api_key_ref = NULL WHERE id = ?",
            (profile.provider_id,),
        )
    credentials.delete(profile.api_key_ref)
    return get_provider_profile(db, model_profile_id)


def delete_provider_profile(
    db: Database, credentials: CredentialStore, model_profile_id: str
) -> None:
    profile = get_provider_profile(db, model_profile_id)
    with db.transaction() as conn:
        conn.execute("DELETE FROM model_profiles WHERE id = ?", (model_profile_id,))
        remaining = conn.execute(
            "SELECT COUNT(*) FROM model_profiles WHERE provider_id = ?",
            (profile.provider_id,),
        ).fetchone()[0]
        if not remaining:
            conn.execute("DELETE FROM providers WHERE id = ?", (profile.provider_id,))
    if profile.api_key_ref and not remaining:
        credentials.delete(profile.api_key_ref)


def build_provider(
    db: Database,
    credentials: CredentialStore,
    model_profile_id: str,
) -> BaseProvider:
    profile = get_provider_profile(db, model_profile_id)

    def key() -> str:
        if not profile.api_key_ref:
            return ""
        return credentials.get(profile.api_key_ref)

    extra = profile.extra
    if profile.protocol == "openai_chat":
        inner: BaseProvider = OpenAIChatProvider(
            profile.base_url, key, test_model=profile.model
        )
    elif profile.protocol == "openai_responses":
        inner = OpenAIResponsesProvider(profile.base_url, key)
    elif profile.protocol == "anthropic_messages":
        inner = AnthropicMessagesProvider(
            profile.base_url,
            key,
            api_version=str(extra.get("api_version") or "2023-06-01"),
            test_model=profile.model,
        )
    elif profile.protocol == "gemini":
        inner = GeminiProvider(profile.base_url, key)
    elif profile.protocol == "openai_compatible":
        models_path_raw = extra.get("models_path", "/models")
        inner = OpenAICompatibleProvider(
            profile.base_url,
            key,
            completions_path=str(extra.get("completions_path") or "/chat/completions"),
            models_path=(
                None
                if models_path_raw is None or not str(models_path_raw).strip()
                else str(models_path_raw)
            ),
            auth_style=str(extra.get("auth_style") or "bearer"),
            extra_headers=dict(extra.get("extra_headers") or {}),
            image_input=bool(extra.get("image_input", False)),
            reasoning_effort=bool(extra.get("reasoning_effort", False)),
            test_model=profile.model,
        )
    else:
        raise ValueError(f"unsupported provider protocol: {profile.protocol}")

    return ModelBoundProvider(
        inner,
        profile.model,
        reasoning=profile.reasoning,
        max_output_tokens=profile.max_output_tokens,
        timeout_s=float(profile.timeout_s) if profile.timeout_s else None,
    )


def public_profile(profile: ProviderProfile) -> dict[str, Any]:
    """Safe UI shape: never expose the credential value."""
    return {
        "provider_id": profile.provider_id,
        "model_profile_id": profile.model_profile_id,
        "name": profile.name,
        "protocol": profile.protocol,
        "base_url": profile.base_url,
        "has_api_key": bool(profile.api_key_ref),
        "model": profile.model,
        "reasoning": profile.reasoning,
        "max_output_tokens": profile.max_output_tokens,
        "timeout_s": profile.timeout_s,
        "extra": profile.extra,
        "auth_kind": "api_key" if profile.api_key_ref else "none",
        "capabilities": capability_descriptor(profile.protocol, profile.extra),
    }
