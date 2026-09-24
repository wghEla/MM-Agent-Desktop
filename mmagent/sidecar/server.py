"""Authenticated loopback-only sidecar API for MM-Agent Desktop."""
from __future__ import annotations

import argparse
import os
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr

from mmagent.api.dashboard import dashboard
from mmagent.api.projects import ProjectHandle, create_project, open_project
from mmagent.api.providers import (
    build_provider,
    create_provider_profile,
    list_provider_profiles,
    public_profile,
)
from mmagent.api.runs import RunController
from mmagent.runtime.credentials import (
    CredentialStore,
    MemoryCredentialStore,
    WindowsCredentialStore,
)
from mmagent.tools.filesystem import FsListTool, FsReadTool, FsWriteTool
from mmagent.tools.python import PythonRunTool
from mmagent.tools.registry import ToolRegistry

_TOKEN_ENV = "MMAGENT_SIDECAR_TOKEN"


class ProjectCreateRequest(BaseModel):
    root: str
    name: str
    profile: str = "标准"


class ProjectOpenRequest(BaseModel):
    root: str


class ProviderCreateRequest(BaseModel):
    name: str
    protocol: str
    base_url: str
    model: str
    api_key: SecretStr | None = Field(default=None, repr=False)
    reasoning: str | None = None
    max_output_tokens: int | None = None
    timeout_s: int | None = 300
    extra: dict[str, Any] = Field(default_factory=dict)


class RunStartRequest(BaseModel):
    model_profile_id: str
    profile: str = "标准"


class RunResumeRequest(BaseModel):
    model_profile_id: str


class CancelRequest(BaseModel):
    reason: str = "user cancelled"


@dataclass
class SidecarState:
    token: str
    credentials: CredentialStore
    projects: dict[str, ProjectHandle] = field(default_factory=dict)
    runs: RunController = field(default_factory=RunController)

    def register(self, handle: ProjectHandle) -> ProjectHandle:
        existing = self.projects.get(handle.project_id)
        if existing is not None:
            handle.workspace.db.close()
            return existing
        self.projects[handle.project_id] = handle
        return handle

    def project(self, project_id: str) -> ProjectHandle:
        try:
            return self.projects[project_id]
        except KeyError as exc:
            raise LookupError(
                f"project 未在当前 sidecar 打开: {project_id}"
            ) from exc

    def close(self) -> None:
        for handle in self.projects.values():
            try:
                handle.workspace.db.close()
            except Exception:
                pass
        self.projects.clear()


def _default_credentials() -> CredentialStore:
    if os.name == "nt":
        return WindowsCredentialStore()
    return MemoryCredentialStore()


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(FsReadTool())
    registry.register(FsWriteTool())
    registry.register(FsListTool())
    registry.register(PythonRunTool())
    return registry


def create_app(
    *,
    token: str,
    credentials: CredentialStore | None = None,
) -> FastAPI:
    if len(token) < 24:
        raise ValueError("sidecar token must contain at least 24 characters")

    state = SidecarState(token=token, credentials=credentials or _default_credentials())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            await state.runs.shutdown()
            state.close()

    app = FastAPI(
        title="MM-Agent Desktop Sidecar",
        version="0.1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.mmagent = state

    @app.exception_handler(LookupError)
    async def lookup_error(_: Request, exc: LookupError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(RuntimeError)
    async def runtime_error(_: Request, exc: RuntimeError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    async def authorize(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        prefix = "Bearer "
        supplied = ""
        if authorization and authorization.startswith(prefix):
            supplied = authorization[len(prefix):]
        if not supplied or not secrets.compare_digest(supplied, state.token):
            raise HTTPException(status_code=401, detail="unauthorized")

    auth = [Depends(authorize)]

    @app.get("/health", dependencies=auth)
    async def health() -> dict[str, Any]:
        return {"ok": True, "service": "mmagent-sidecar", "pid": os.getpid()}

    @app.post("/projects", dependencies=auth)
    async def project_create(req: ProjectCreateRequest) -> dict[str, Any]:
        handle = state.register(
            create_project(Path(req.root), name=req.name, profile=req.profile)
        )
        return _project_view(handle)

    @app.post("/projects/open", dependencies=auth)
    async def project_open(req: ProjectOpenRequest) -> dict[str, Any]:
        handle = state.register(open_project(Path(req.root)))
        return _project_view(handle)

    @app.get("/projects/{project_id}/providers", dependencies=auth)
    async def providers_list(project_id: str) -> list[dict[str, Any]]:
        handle = state.project(project_id)
        return [
            public_profile(profile)
            for profile in list_provider_profiles(handle.workspace.db)
        ]

    @app.post("/projects/{project_id}/providers", dependencies=auth)
    async def provider_create(
        project_id: str, req: ProviderCreateRequest
    ) -> dict[str, Any]:
        handle = state.project(project_id)
        profile = create_provider_profile(
            handle.workspace.db,
            state.credentials,
            name=req.name,
            protocol=req.protocol,
            base_url=req.base_url,
            model=req.model,
            api_key=req.api_key.get_secret_value() if req.api_key else None,
            reasoning=req.reasoning,
            max_output_tokens=req.max_output_tokens,
            timeout_s=req.timeout_s,
            extra=req.extra,
        )
        return public_profile(profile)

    @app.post(
        "/projects/{project_id}/providers/{model_profile_id}/test",
        dependencies=auth,
    )
    async def provider_test(
        project_id: str, model_profile_id: str
    ) -> dict[str, Any]:
        handle = state.project(project_id)
        provider = build_provider(
            handle.workspace.db, state.credentials, model_profile_id
        )
        try:
            return await provider.test_connection()
        finally:
            await provider.aclose()

    @app.post("/projects/{project_id}/runs", dependencies=auth)
    async def run_start(
        project_id: str, req: RunStartRequest
    ) -> dict[str, Any]:
        handle = state.project(project_id)
        provider = build_provider(
            handle.workspace.db, state.credentials, req.model_profile_id
        )
        run_id = await state.runs.start(
            handle,
            provider=provider,
            registry=build_tool_registry(),
            profile=req.profile,
        )
        return {"run_id": run_id}

    @app.post(
        "/projects/{project_id}/runs/{run_id}/pause",
        dependencies=auth,
    )
    async def run_pause(project_id: str, run_id: str) -> dict[str, Any]:
        state.project(project_id)
        await state.runs.pause(run_id)
        return {"ok": True}

    @app.post(
        "/projects/{project_id}/runs/{run_id}/resume",
        dependencies=auth,
    )
    async def run_resume(
        project_id: str, run_id: str, req: RunResumeRequest
    ) -> dict[str, Any]:
        handle = state.project(project_id)
        provider = build_provider(
            handle.workspace.db, state.credentials, req.model_profile_id
        )
        await state.runs.resume(
            handle,
            run_id,
            provider=provider,
            registry=build_tool_registry(),
        )
        return {"ok": True}

    @app.post(
        "/projects/{project_id}/runs/{run_id}/cancel",
        dependencies=auth,
    )
    async def run_cancel(
        project_id: str, run_id: str, req: CancelRequest
    ) -> dict[str, Any]:
        state.project(project_id)
        await state.runs.cancel(run_id, req.reason)
        return {"ok": True}

    @app.get(
        "/projects/{project_id}/runs/{run_id}",
        dependencies=auth,
    )
    async def run_status(project_id: str, run_id: str) -> dict[str, Any]:
        handle = state.project(project_id)
        return state.runs.status(handle, run_id)

    @app.get(
        "/projects/{project_id}/runs/{run_id}/dashboard",
        dependencies=auth,
    )
    async def run_dashboard(project_id: str, run_id: str) -> dict[str, Any]:
        handle = state.project(project_id)
        return dashboard(handle.workspace, run_id)

    return app


def _project_view(handle: ProjectHandle) -> dict[str, Any]:
    row = handle.workspace.db.query_one(
        "SELECT id, name, root_path, profile, created_at FROM projects WHERE id = ?",
        (handle.project_id,),
    )
    if row is None:
        raise LookupError(handle.project_id)
    return dict(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="MM-Agent Desktop local sidecar")
    parser.add_argument("--port", type=int, default=28741)
    args = parser.parse_args()
    if args.port < 1024 or args.port > 65535:
        raise SystemExit("port must be between 1024 and 65535")

    token = os.environ.get(_TOKEN_ENV, "")
    if len(token) < 24:
        raise SystemExit(f"{_TOKEN_ENV} missing or too short")

    app = create_app(token=token)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
