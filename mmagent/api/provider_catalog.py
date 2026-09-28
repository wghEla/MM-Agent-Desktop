"""Provider catalog, capability descriptors and safe model discovery for Desktop UI.

This module owns *presentation metadata* for supported provider presets and read-only
model discovery.  It does not change the runtime protocol adapters or credential truth.

OAuth is represented explicitly but only exposed when a documented third-party flow is
actually implemented.  The current registry intentionally contains no OAuth adapters.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

import httpx

from mmagent.api.provider_oauth import DEFAULT_OAUTH_REGISTRY
from mmagent.api.provider_validation import (
    validate_provider_base_url,
    validate_provider_extra,
)
from mmagent.providers._http_util import redacted
from mmagent.providers.capabilities import CapabilitySet

AuthKind = Literal["api_key", "oauth", "none"]


@dataclass(frozen=True)
class OAuthDescriptor:
    flow: Literal["authorization_code_pkce", "device_code"]
    authorize_path: str
    token_path: str


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    label: str
    protocol: str
    base_url: str
    auth_methods: tuple[AuthKind, ...]
    discover_models: bool
    base_url_editable: bool = False
    oauth: OAuthDescriptor | None = None
    note: str = ""


# OAuth is deliberately absent until a provider documents and supports a third-party
# desktop flow that MM-Agent can register for under its own client identity.
PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        "openai",
        "OpenAI",
        "openai_responses",
        "https://api.openai.com/v1",
        ("api_key",),
        True,
        note="OpenAI API Platform credential",
    ),
    ProviderPreset(
        "anthropic",
        "Anthropic",
        "anthropic_messages",
        "https://api.anthropic.com",
        ("api_key",),
        True,
        note="Anthropic API credential",
    ),
    ProviderPreset(
        "gemini",
        "Gemini",
        "gemini",
        "https://generativelanguage.googleapis.com",
        ("api_key",),
        True,
        note="Gemini API credential",
    ),
    ProviderPreset(
        "groq",
        "Groq",
        "openai_compatible",
        "https://api.groq.com/openai/v1",
        ("api_key",),
        True,
        note="OpenAI-compatible API",
    ),
    ProviderPreset(
        "deepseek",
        "DeepSeek",
        "openai_compatible",
        "https://api.deepseek.com",
        ("api_key",),
        True,
        note="OpenAI-compatible API",
    ),
    ProviderPreset(
        "zcode",
        "ZCode",
        "openai_compatible",
        "",
        ("api_key",),
        True,
        base_url_editable=True,
        note="Configure the endpoint supplied by your ZCode API account",
    ),
    ProviderPreset(
        "compatible",
        "OpenAI Compatible",
        "openai_compatible",
        "",
        ("api_key", "none"),
        True,
        base_url_editable=True,
        note="Relays, NewAPI/OneAPI, vLLM and compatible endpoints",
    ),
)


def catalog_payload() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in PROVIDER_PRESETS:
        oauth_ready = (
            item.oauth is not None
            and DEFAULT_OAUTH_REGISTRY.has(item.id)
        )
        auth_methods = [
            method
            for method in item.auth_methods
            if method != "oauth" or oauth_ready
        ]
        row = asdict(item)
        row["auth_methods"] = auth_methods
        row["oauth"] = asdict(item.oauth) if oauth_ready and item.oauth else None
        row["capabilities"] = capability_descriptor(item.protocol, {})
        out.append(row)
    return out


def capability_descriptor(protocol: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    extra = extra or {}
    if protocol == "openai_chat":
        caps = CapabilitySet(
            protocol=protocol,
            tool_calling=True,
            image_input=True,
            streaming=False,
            reasoning_levels=frozenset({"low", "medium", "high"}),
        )
    elif protocol == "openai_responses":
        caps = CapabilitySet(
            protocol=protocol,
            tool_calling=True,
            image_input=True,
            streaming=False,
            reasoning_levels=frozenset({"minimal", "low", "medium", "high"}),
        )
    elif protocol == "anthropic_messages":
        caps = CapabilitySet(
            protocol=protocol,
            tool_calling=True,
            image_input=True,
            streaming=False,
            reasoning_levels=frozenset(),
        )
    elif protocol == "gemini":
        caps = CapabilitySet(
            protocol=protocol,
            tool_calling=True,
            image_input=True,
            streaming=False,
            reasoning_levels=frozenset(),
        )
    elif protocol == "openai_compatible":
        caps = CapabilitySet(
            protocol=protocol,
            tool_calling=True,
            image_input=bool(extra.get("image_input", False)),
            streaming=False,
            reasoning_levels=(
                frozenset({"low", "medium", "high"})
                if bool(extra.get("reasoning_effort", False))
                else frozenset()
            ),
        )
    else:
        raise ValueError(f"unsupported provider protocol: {protocol}")
    return caps.describe()


def _discovery_secrets(api_key: str, extra: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    if api_key:
        values.append(api_key)
    headers = extra.get("extra_headers")
    if isinstance(headers, dict):
        values.extend(
            value
            for value in headers.values()
            if isinstance(value, str) and value
        )
    # Longest first so a shorter token does not partially mask a longer one.
    return tuple(sorted(set(values), key=len, reverse=True))


def _discovery_headers(
    protocol: str,
    api_key: str,
    extra: dict[str, Any],
) -> dict[str, str]:
    if protocol in {"openai_chat", "openai_responses"}:
        return {"Authorization": f"Bearer {api_key}"} if api_key else {}
    if protocol == "anthropic_messages":
        headers = {"anthropic-version": str(extra.get("api_version") or "2023-06-01")}
        if api_key:
            headers["x-api-key"] = api_key
        return headers
    if protocol == "gemini":
        return {"x-goog-api-key": api_key} if api_key else {}
    if protocol == "openai_compatible":
        headers = dict(extra.get("extra_headers") or {})
        if not api_key:
            return headers
        auth_style = str(extra.get("auth_style") or "bearer")
        if auth_style == "bearer":
            headers["Authorization"] = f"Bearer {api_key}"
        elif auth_style == "x-api-key":
            headers["x-api-key"] = api_key
        elif auth_style != "none":
            raise ValueError(f"unsupported auth_style: {auth_style}")
        return headers
    raise ValueError(f"unsupported provider protocol: {protocol}")


def _models_url(
    protocol: str,
    base_url: str,
    extra: dict[str, Any],
) -> str | None:
    base = base_url.rstrip("/")
    if protocol == "gemini":
        return f"{base}/v1beta/models"
    if protocol == "anthropic_messages":
        return f"{base}/v1/models"
    if protocol == "openai_compatible":
        raw = extra.get("models_path", "/models")
        if raw is None or str(raw).strip() == "":
            return None
        path = str(raw).strip()
        if not path.startswith("/"):
            path = "/" + path
        return f"{base}{path}"
    return f"{base}/models"


def _parse_model_ids(protocol: str, payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []

    values: list[str] = []
    if protocol == "gemini":
        rows = payload.get("models")
        if not isinstance(rows, list):
            return []
        for row in rows:
            if not isinstance(row, dict):
                continue
            methods = row.get("supportedGenerationMethods")
            if isinstance(methods, list) and "generateContent" not in methods:
                continue
            value = row.get("name")
            if isinstance(value, str) and value:
                values.append(value.removeprefix("models/"))
    else:
        rows = payload.get("data")
        if not isinstance(rows, list):
            return []
        for row in rows:
            if isinstance(row, dict):
                value = row.get("id")
                if isinstance(value, str) and value:
                    values.append(value)

    # Stable, bounded UI payload.  Duplicate model aliases are collapsed.
    return sorted(set(values), key=str.casefold)[:500]


async def discover_models(
    *,
    protocol: str,
    base_url: str,
    api_key: str = "",
    extra: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Read a provider's model-list endpoint without persisting credentials.

    Discovery never falls back to a generation request: pressing "refresh models" must not
    unexpectedly spend tokens.  Unsupported/missing list endpoints return an honest
    failure and the UI keeps manual model entry available.
    """
    base_url = validate_provider_base_url(base_url)
    extra = validate_provider_extra(extra)
    secrets = _discovery_secrets(api_key, extra)
    headers = _discovery_headers(protocol, api_key, extra)
    url = _models_url(protocol, base_url, extra)
    if url is None:
        return {
            "ok": False,
            "models": [],
            "detail": "该渠道已关闭模型列表端点；请手动输入 Model ID",
            "endpoint": "",
        }

    owned = client is None
    http = client or httpx.AsyncClient(timeout=15.0)
    try:
        try:
            response = await http.get(url, headers=headers, timeout=15.0)
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "models": [],
                "detail": "模型列表网络错误: " + redacted(str(exc)[:160], secrets),
                "endpoint": url,
            }

        if response.status_code != 200:
            detail = redacted(response.text[:240], secrets)
            return {
                "ok": False,
                "models": [],
                "detail": f"模型列表端点 {response.status_code}: {detail}",
                "endpoint": url,
            }

        try:
            payload = response.json()
        except Exception as exc:
            return {
                "ok": False,
                "models": [],
                "detail": "模型列表响应不是合法 JSON: " + redacted(str(exc), secrets),
                "endpoint": url,
            }

        models = _parse_model_ids(protocol, payload)
        if not models:
            return {
                "ok": False,
                "models": [],
                "detail": "模型列表端点可达，但没有识别到可用模型；请手动输入 Model ID",
                "endpoint": url,
            }
        return {
            "ok": True,
            "models": models,
            "detail": f"发现 {len(models)} 个模型",
            "endpoint": url,
        }
    finally:
        if owned:
            await http.aclose()
