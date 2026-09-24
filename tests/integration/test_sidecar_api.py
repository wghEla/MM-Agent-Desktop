from __future__ import annotations

from fastapi.testclient import TestClient

from mmagent.runtime.credentials import MemoryCredentialStore
from mmagent.sidecar.server import create_app


TOKEN = "test-sidecar-token-0123456789"


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_sidecar_requires_bearer_token() -> None:
    app = create_app(token=TOKEN, credentials=MemoryCredentialStore())
    with TestClient(app) as client:
        assert client.get("/health").status_code == 401
        assert client.get(
            "/health", headers={"Authorization": "Bearer wrong-token"}
        ).status_code == 401
        ok = client.get("/health", headers=_auth())
        assert ok.status_code == 200
        assert ok.json()["service"] == "mmagent-sidecar"


def test_sidecar_project_and_provider_secret_boundary(tmp_path) -> None:
    store = MemoryCredentialStore()
    app = create_app(token=TOKEN, credentials=store)
    secret = "sk-sidecar-secret-value"

    with TestClient(app) as client:
        created = client.post(
            "/projects",
            headers=_auth(),
            json={
                "root": str(tmp_path / "proj"),
                "name": "Sidecar Project",
                "profile": "standard",
            },
        )
        assert created.status_code == 200, created.text
        project_id = created.json()["id"]

        profile = client.post(
            f"/projects/{project_id}/providers",
            headers=_auth(),
            json={
                "name": "Primary",
                "protocol": "openai_chat",
                "base_url": "https://example.invalid/v1",
                "model": "model-x",
                "api_key": secret,
                "reasoning": "high",
                "timeout_s": 321,
            },
        )
        assert profile.status_code == 200, profile.text
        payload = profile.json()
        assert payload["has_api_key"] is True
        assert secret not in profile.text
        assert "api_key" not in payload

        listed = client.get(
            f"/projects/{project_id}/providers", headers=_auth()
        )
        assert listed.status_code == 200
        assert secret not in listed.text

        state = app.state.mmagent
        handle = state.project(project_id)
        row = handle.workspace.db.query_one(
            "SELECT api_key_ref, extra_json FROM providers WHERE id = ?",
            (payload["provider_id"],),
        )
        assert row is not None
        assert row["api_key_ref"]
        assert secret not in row["api_key_ref"]
        assert secret not in row["extra_json"]
        assert store.get(row["api_key_ref"]) == secret


def test_sidecar_maps_domain_errors(tmp_path) -> None:
    app = create_app(token=TOKEN, credentials=MemoryCredentialStore())
    with TestClient(app) as client:
        missing = client.get(
            "/projects/not-open/providers", headers=_auth()
        )
        assert missing.status_code == 404

        project = client.post(
            "/projects",
            headers=_auth(),
            json={"root": str(tmp_path / "proj"), "name": "P"},
        )
        project_id = project.json()["id"]
        bad = client.post(
            f"/projects/{project_id}/providers",
            headers=_auth(),
            json={
                "name": "Bad",
                "protocol": "not-a-protocol",
                "base_url": "https://example.invalid",
                "model": "m",
            },
        )
        assert bad.status_code == 400


def test_sidecar_rejects_short_token() -> None:
    try:
        create_app(token="short", credentials=MemoryCredentialStore())
    except ValueError as exc:
        assert "token" in str(exc)
    else:
        raise AssertionError("short sidecar token must be rejected")
