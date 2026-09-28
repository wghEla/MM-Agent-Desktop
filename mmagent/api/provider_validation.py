"""Shared validation for provider endpoints and persisted provider extras.

The desktop has two provider entry paths:

1. persisted provider profiles;
2. transient model discovery before a profile is saved.

Both must obey the same URL/header/path secret boundary so discovery cannot become a
weaker side channel than persisted provider configuration.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

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

_ALLOWED_AUTH_STYLES = frozenset({"bearer", "x-api-key", "none"})


def validate_provider_base_url(base_url: str) -> str:
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


def validate_relative_endpoint_path(
    value: str | None,
    *,
    field: str,
    allow_empty: bool = False,
) -> str | None:
    if value is None:
        return None if allow_empty else "/"

    raw = str(value).strip()
    if not raw:
        if allow_empty:
            return None
        raise ValueError(f"{field} must be non-empty")

    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        raise ValueError(f"{field} must be a relative endpoint path, not a URL")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{field} must not contain query or fragment")
    if "\" in raw:
        raise ValueError(f"{field} must use URL forward slashes")

    path = raw if raw.startswith("/") else "/" + raw
    if path.startswith("//"):
        raise ValueError(f"{field} must not be protocol-relative")
    return path


def validate_provider_extra(extra: dict[str, Any] | None) -> dict[str, Any]:
    value = dict(extra or {})

    raw_headers = value.get("extra_headers")
    if raw_headers is not None:
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
        if not all(isinstance(name, str) and isinstance(header_value, str)
                   for name, header_value in raw_headers.items()):
            raise ValueError("extra_headers keys and values must be strings")

    auth_style = value.get("auth_style")
    if auth_style is not None:
        auth_style = str(auth_style).strip()
        if auth_style not in _ALLOWED_AUTH_STYLES:
            raise ValueError(f"unsupported auth_style: {auth_style}")
        value["auth_style"] = auth_style

    if "completions_path" in value:
        value["completions_path"] = validate_relative_endpoint_path(
            value.get("completions_path"),
            field="completions_path",
            allow_empty=False,
        )

    if "models_path" in value:
        value["models_path"] = validate_relative_endpoint_path(
            value.get("models_path"),
            field="models_path",
            allow_empty=True,
        )

    return value
