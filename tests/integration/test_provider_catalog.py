from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

import mmagent.sidecar.server as sidecar_server
from mmagent.api.provider_catalog import (
    capability_descriptor,
    catalog_payload,
    discover_models,
)
from mmagent.runtime.credentials import MemoryCredentialStore
from mmagent.sidecar.server import create_app

TOKEN = "test-provider-catalog-token-0123456789"


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_catalog_has_no_unimplemented_oauth_login() -> None:
    catalog = catalog_payload()
    assert catalog
    assert any(item["id"] == "zcode" for item in catalog)
    assert all(item["oauth"] is None for item in catalog)
    assert all("oauth" not in item["auth_methods"] for item in catalog)


def test_compatible_capabilities_are_conservative_until_opted_in() -> None:
    default = capability_descriptor("openai_compatible", {})
    assert default["image_input"] is False
    assert default["reasoning_levels"] == []

    enabled = capability_descriptor(
        "openai_compatible",
        {"image_input": True, "reasoning_effort": True},
    )
    assert enabled["image_input"] is True
    assert enabled["reasoning_levels"] == ["high", "low", "medium"]


@pytest.mark.asyncio
async def test_discover_openai_models_is_bounded_sorted_and_deduplicated() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert request.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "z-model"},
                    {"id": "a-model"},
                    {"id": "a-model"},
                    {"missing": "ignored"},
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.invalid",
    ) as client:
        result = await discover_models(
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            api_key="test-secret",
            client=client,
        )

    assert result["ok"] is True
    assert result["models"] == ["a-model", "z-model"]
    assert "test-secret" not in repr(result)


@pytest.mark.asyncio
async def test_discover_models_redacts_secret_from_error_body() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad credential test-secret")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.invalid",
    ) as client:
        result = await discover_models(
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            api_key="test-secret",
            client=client,
        )

    assert result["ok"] is False
    assert "test-secret" not in result["detail"]
    assert "REDACTED" in result["detail"]


@pytest.mark.asyncio
async def test_discover_gemini_models_strips_prefix_and_filters_non_generate() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1beta/models"
        assert request.headers["x-goog-api-key"] == "gemini-secret"
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-a",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/embed-only",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.invalid",
    ) as client:
        result = await discover_models(
            protocol="gemini",
            base_url="https://example.invalid",
            api_key="gemini-secret",
            client=client,
        )

    assert result["models"] == ["gemini-a"]


def test_sidecar_provider_preflight_does_not_persist_profile_or_credential(
    tmp_path,
    monkeypatch,
) -> None:
    store = MemoryCredentialStore()
    app = create_app(token=TOKEN, credentials=store)
    seen: list[dict] = []

    class FakeProvider:
        async def test_connection(self):
            return {"ok": True, "detail": "preflight-ok"}

        async def aclose(self):
            return None

    def fake_build_provider_from_config(**kwargs):
        seen.append(kwargs)
        return FakeProvider()

    monkeypatch.setattr(
        sidecar_server,
        "build_provider_from_config",
        fake_build_provider_from_config,
    )

    with TestClient(app) as client:
        project = client.post(
            "/projects",
            headers=_auth(),
            json={"root": str(tmp_path / "proj-preflight"), "name": "Preflight"},
        )
        assert project.status_code == 200
        project_id = project.json()["id"]

        secret = "test-preflight-secret"
        response = client.post(
            "/providers/test-config",
            headers=_auth(),
            json={
                "protocol": "openai_compatible",
                "base_url": "https://relay.invalid/v1",
                "model": "model-a",
                "api_key": secret,
                "timeout_s": 20,
                "extra": {"auth_style": "bearer"},
            },
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True, "detail": "preflight-ok"}
        assert secret not in response.text
        assert seen[-1]["api_key"] == secret

        listed = client.get(
            f"/projects/{project_id}/providers",
            headers=_auth(),
        )
        assert listed.status_code == 200
        assert listed.json() == []
        assert store.values == {}


def test_sidecar_provider_catalog_crud_and_credential_boundary(
    tmp_path,
    monkeypatch,
) -> None:
    store = MemoryCredentialStore()
    app = create_app(token=TOKEN, credentials=store)
    seen: list[dict] = []

    async def fake_discover_models(**kwargs):
        seen.append(kwargs)
        return {
            "ok": True,
            "models": ["model-a", "model-b"],
            "detail": "发现 2 个模型",
            "endpoint": f"{kwargs['base_url'].rstrip('/')}/models",
        }

    monkeypatch.setattr(sidecar_server, "discover_models", fake_discover_models)

    with TestClient(app) as client:
        project = client.post(
            "/projects",
            headers=_auth(),
            json={"root": str(tmp_path / "proj"), "name": "Provider UX"},
        )
        assert project.status_code == 200
        project_id = project.json()["id"]

        catalog = client.get("/providers/catalog", headers=_auth())
        assert catalog.status_code == 200
        assert any(row["id"] == "openai" for row in catalog.json())

        transient_secret = "test-transient-secret"
        discovery = client.post(
            "/providers/discover-models",
            headers=_auth(),
            json={
                "protocol": "openai_compatible",
                "base_url": "https://relay.invalid/v1",
                "api_key": transient_secret,
                "extra": {"auth_style": "bearer"},
            },
        )
        assert discovery.status_code == 200
        assert discovery.json()["models"] == ["model-a", "model-b"]
        assert transient_secret not in discovery.text
        assert seen[-1]["api_key"] == transient_secret

        created = client.post(
            f"/projects/{project_id}/providers",
            headers=_auth(),
            json={
                "name": "Relay",
                "protocol": "openai_compatible",
                "base_url": "https://relay.invalid/v1",
                "model": "model-a",
                "api_key": "test-persisted-secret",
                "timeout_s": 300,
                "extra": {"image_input": False, "reasoning_effort": False},
            },
        )
        assert created.status_code == 200
        profile = created.json()
        model_profile_id = profile["model_profile_id"]
        assert profile["auth_kind"] == "api_key"
        assert profile["capabilities"]["image_input"] is False
        assert "test-persisted-secret" not in created.text

        models = client.get(
            f"/projects/{project_id}/providers/{model_profile_id}/models",
            headers=_auth(),
        )
        assert models.status_code == 200
        assert seen[-1]["api_key"] == "test-persisted-secret"

        updated = client.post(
            f"/projects/{project_id}/providers/{model_profile_id}",
            headers=_auth(),
            json={
                "name": "Relay Updated",
                "protocol": "openai_compatible",
                "base_url": "https://relay.invalid/v1",
                "model": "model-b",
                "reasoning": "low",
                "max_output_tokens": 4096,
                "timeout_s": 90,
                "extra": {"image_input": True, "reasoning_effort": True},
            },
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["name"] == "Relay Updated"
        assert body["model"] == "model-b"
        assert body["capabilities"]["image_input"] is True
        assert body["capabilities"]["reasoning_levels"] == ["high", "low", "medium"]

        replaced_secret = "test-replaced-secret"
        replaced = client.post(
            f"/projects/{project_id}/providers/{model_profile_id}/credential",
            headers=_auth(),
            json={"api_key": replaced_secret},
        )
        assert replaced.status_code == 200
        assert replaced.json()["has_api_key"] is True
        assert replaced_secret not in replaced.text

        state = app.state.mmagent
        handle = state.project(project_id)
        ref = handle.workspace.db.query_one(
            "SELECT api_key_ref FROM providers WHERE id = ?",
            (profile["provider_id"],),
        )["api_key_ref"]
        assert store.get(ref) == replaced_secret

        cleared = client.post(
            f"/projects/{project_id}/providers/{model_profile_id}/credential/clear",
            headers=_auth(),
        )
        assert cleared.status_code == 200
        assert cleared.json()["has_api_key"] is False
        assert cleared.json()["auth_kind"] == "none"

        deleted = client.post(
            f"/projects/{project_id}/providers/{model_profile_id}/delete",
            headers=_auth(),
        )
        assert deleted.status_code == 200
        assert client.get(
            f"/projects/{project_id}/providers",
            headers=_auth(),
        ).json() == []


@pytest.mark.asyncio
async def test_discover_compatible_models_path_can_be_custom_or_disabled() -> None:
    captures: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captures.append(request)
        return httpx.Response(200, json={"data": [{"id": "custom-model"}]})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.invalid",
    ) as client:
        custom = await discover_models(
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            api_key="test-secret",
            extra={"models_path": "/catalog/models"},
            client=client,
        )
        disabled = await discover_models(
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            api_key="test-secret",
            extra={"models_path": ""},
            client=client,
        )

    assert custom["models"] == ["custom-model"]
    assert captures[0].url.path == "/v1/catalog/models"
    assert disabled["ok"] is False
    assert disabled["models"] == []
    assert disabled["endpoint"] == ""
    assert "关闭模型列表端点" in disabled["detail"]
    assert len(captures) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:password@example.invalid/v1",
        "https://example.invalid/v1?api_key=transient-secret",
        "https://example.invalid/v1#token=transient-secret",
        "file:///tmp/provider",
        "example.invalid/v1",
    ],
)
async def test_transient_model_discovery_reuses_safe_base_url_boundary(
    base_url,
) -> None:
    with pytest.raises(ValueError):
        await discover_models(
            protocol="openai_compatible",
            base_url=base_url,
            api_key="test-key",
        )


@pytest.mark.asyncio
async def test_transient_model_discovery_rejects_secret_bearing_extra_headers() -> None:
    with pytest.raises(ValueError, match="Credential Manager"):
        await discover_models(
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            api_key="",
            extra={
                "extra_headers": {
                    "Authorization": "Bearer transient-header-secret",
                }
            },
        )


@pytest.mark.asyncio
async def test_model_discovery_redacts_custom_header_values_from_provider_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            text="echo custom-session-marker",
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.invalid",
    ) as client:
        result = await discover_models(
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            api_key="",
            extra={"extra_headers": {"X-Session": "custom-session-marker"}},
            client=client,
        )

    assert result["ok"] is False
    assert "custom-session-marker" not in result["detail"]
    assert "REDACTED" in result["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("models_path", "https://other.invalid/models"),
        ("models_path", "//other.invalid/models"),
        ("models_path", "/models?token=secret"),
        ("completions_path", "https://other.invalid/chat"),
        ("completions_path", "/chat/completions#secret"),
    ],
)
async def test_transient_model_discovery_rejects_absolute_or_secret_endpoint_paths(
    field,
    value,
) -> None:
    with pytest.raises(ValueError):
        await discover_models(
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            extra={field: value},
        )


def test_saved_provider_model_discovery_reports_missing_credential_as_409(
    tmp_path,
) -> None:
    store = MemoryCredentialStore()
    app = create_app(token=TOKEN, credentials=store)

    with TestClient(app) as client:
        project = client.post(
            "/projects",
            headers=_auth(),
            json={"root": str(tmp_path / "proj-missing-key"), "name": "Missing Key"},
        )
        project_id = project.json()["id"]

        created = client.post(
            f"/projects/{project_id}/providers",
            headers=_auth(),
            json={
                "name": "Relay",
                "protocol": "openai_compatible",
                "base_url": "https://relay.invalid/v1",
                "model": "model-a",
                "api_key": "test-key-to-remove",
            },
        )
        model_profile_id = created.json()["model_profile_id"]
        provider_id = created.json()["provider_id"]

        state = app.state.mmagent
        handle = state.project(project_id)
        ref = handle.workspace.db.query_one(
            "SELECT api_key_ref FROM providers WHERE id = ?",
            (provider_id,),
        )["api_key_ref"]
        store.delete(ref)

        response = client.get(
            f"/projects/{project_id}/providers/{model_profile_id}/models",
            headers=_auth(),
        )
        assert response.status_code == 409
        assert "credential missing" in response.json()["detail"]
        assert "test-key-to-remove" not in response.text
