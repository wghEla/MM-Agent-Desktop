from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

import mmagent.sidecar.server as sidecar_server
from mmagent.runtime.credentials import MemoryCredentialStore
from mmagent.runtime.environment import ToolCapability
from mmagent.sidecar.server import (
    build_pipeline_hooks,
    build_tool_registry,
    create_app,
)
from mmagent.state import repositories
from mmagent.state.models import RunStatus

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
        assert ok.json()["managed_python"]["ok"] is True


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



def test_sidecar_import_and_artifact_preview(tmp_path) -> None:
    app = create_app(token=TOKEN, credentials=MemoryCredentialStore())
    source = tmp_path / "problem.md"
    source.write_text("synthetic problem", encoding="utf-8")

    with TestClient(app) as client:
        project = client.post(
            "/projects",
            headers=_auth(),
            json={"root": str(tmp_path / "proj"), "name": "Artifacts"},
        )
        project_id = project.json()["id"]

        imported = client.post(
            f"/projects/{project_id}/imports",
            headers=_auth(),
            json={"sources": [str(source)], "kind": "problem"},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["imported"][0]["path"] == "输入/题目/problem.md"

        state = app.state.mmagent
        handle = state.project(project_id)
        note = handle.workspace.root / "审稿" / "viewer.md"
        note.write_text("artifact body", encoding="utf-8")

        listed = client.get(
            f"/projects/{project_id}/artifacts", headers=_auth()
        )
        assert listed.status_code == 200
        assert any(item["path"] == "审稿/viewer.md" for item in listed.json())

        preview = client.post(
            f"/projects/{project_id}/artifacts/read",
            headers=_auth(),
            json={"path": "审稿/viewer.md"},
        )
        assert preview.status_code == 200
        assert preview.json()["text"] == "artifact body"

        denied = client.post(
            f"/projects/{project_id}/artifacts/read",
            headers=_auth(),
            json={"path": ".mmagent/project.db"},
        )
        assert denied.status_code == 400



def test_sidecar_shutdown_endpoint_is_authenticated_and_invokes_callback() -> None:
    calls: list[str] = []
    app = create_app(
        token=TOKEN,
        credentials=MemoryCredentialStore(),
        shutdown_callback=lambda: calls.append("shutdown"),
    )
    with TestClient(app) as client:
        denied = client.post("/shutdown")
        assert denied.status_code == 401

        response = client.post("/shutdown", headers=_auth())
        assert response.status_code == 200
        assert response.json() == {"ok": True, "will_exit": True}
        assert calls == ["shutdown"]


def test_sidecar_lists_and_cancels_persisted_run(tmp_path) -> None:
    app = create_app(token=TOKEN, credentials=MemoryCredentialStore())
    with TestClient(app) as client:
        project = client.post(
            "/projects",
            headers=_auth(),
            json={"root": str(tmp_path / "proj-history"), "name": "History"},
        )
        assert project.status_code == 200
        project_id = project.json()["id"]

        state = app.state.mmagent
        handle = state.project(project_id)
        run_id = repositories.create_run(
            handle.workspace.db,
            project_id=handle.project_id,
            profile="标准",
        )
        handle.workspace.acquire_run_lock(run_id)
        repositories.set_run_status(
            handle.workspace.db, run_id, RunStatus.RUNNING
        )
        repositories.set_run_status(
            handle.workspace.db, run_id, RunStatus.PAUSED
        )
        handle.workspace.release_run_lock()

        listed = client.get(
            f"/projects/{project_id}/runs", headers=_auth()
        )
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == run_id
        assert listed.json()[0]["status"] == "PAUSED"
        assert listed.json()[0]["active_in_sidecar"] is False

        cancelled = client.post(
            f"/projects/{project_id}/runs/{run_id}/cancel",
            headers=_auth(),
            json={"reason": "desktop stop after restart"},
        )
        assert cancelled.status_code == 200

        status = client.get(
            f"/projects/{project_id}/runs/{run_id}", headers=_auth()
        )
        assert status.json()["status"] == "CANCELLED"



def test_sidecar_registry_uses_managed_python(monkeypatch) -> None:
    monkeypatch.setenv("MMAGENT_PYTHON", sys.executable)

    registry = build_tool_registry()
    python_tool = registry.get("python.run")

    assert python_tool.interpreter == sys.executable


def test_sidecar_registry_rejects_missing_managed_python(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MMAGENT_PYTHON", str(tmp_path / "missing-python.exe"))

    with pytest.raises(RuntimeError, match="受管 Python 不可用"):
        build_tool_registry()



def test_sidecar_health_fails_when_managed_python_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        sidecar_server,
        "managed_python",
        lambda: ToolCapability(
            "managed_python",
            None,
            None,
            False,
            "missing for test",
        ),
    )
    app = create_app(token=TOKEN, credentials=MemoryCredentialStore())

    with TestClient(app) as client:
        response = client.get("/health", headers=_auth())

    assert response.status_code == 503
    assert "managed Python unavailable" in response.text



def test_sidecar_registry_forwards_shared_process_manager(monkeypatch) -> None:
    monkeypatch.setenv("MMAGENT_PYTHON", sys.executable)
    marker = object()

    registry = build_tool_registry(marker)
    python_tool = registry.get("python.run")

    assert python_tool.process_manager is marker


def test_pipeline_compile_hook_uses_shared_process_manager(
    monkeypatch, tmp_path
) -> None:
    marker = object()
    seen: dict[str, object] = {}

    class FakeLatexTool:
        def __init__(self, root, process_manager=None):
            seen["root"] = root
            seen["process_manager"] = process_manager

        def compile(self, tex_file, *, cancel=None):
            seen["tex_file"] = tex_file
            seen["cancel"] = cancel
            return {"rc": 0, "errors": [], "pages": 7}

    monkeypatch.setattr(sidecar_server, "LatexTool", FakeLatexTool)
    hooks = build_pipeline_hooks(marker)

    assert hooks.compile_paper is not None
    result = hooks.compile_paper(tmp_path)

    assert result["rc"] == 0
    assert seen["root"] == tmp_path
    assert seen["process_manager"] is marker
    assert seen["tex_file"] == "论文/论文.tex"
    assert seen["cancel"] is None
