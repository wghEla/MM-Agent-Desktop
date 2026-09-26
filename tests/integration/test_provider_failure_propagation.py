"""Run-level provider failure propagation 测试。

验证 401/403/429/网络错误 在 AgentLoop / Run 级别的一致语义。
"""
from __future__ import annotations

import httpx
import pytest

from mmagent.agent.errors import (
    ErrorKind,
    RateLimitError,
)
from mmagent.agent.loop import AgentLoop, AgentTask
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.state import repositories
from mmagent.state.models import TaskStatus
from mmagent.tools.registry import ToolRegistry


def _setup(tmp_path, provider, registry=None):
    from mmagent.api.projects import create_project
    from mmagent.workspace.path_policy import PathPolicy
    from mmagent.workspace.permissions import PermissionChecker as PC
    from mmagent.workspace.permissions import RolePermissions as RP

    root = tmp_path / "ws"
    handle = create_project(root, name="t")
    policy = PathPolicy(root)
    perms = RP(
        role_id="t", read_scopes=("**",), write_scopes=("**",),
        allowed_tools=frozenset({"fs.read", "fs.write"}),
    )
    checker = PC(perms, policy)
    loop = AgentLoop(handle.workspace.db, provider, registry or ToolRegistry(), checker, policy)
    return handle.workspace.db, loop, policy, root


def _spec(db, run_id, node="N1"):
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key=node, role_id="t")
    return AgentTask(task_id=t.id, node_key=node, role_id="t", system_prompt="s", instructions="i", model="m")


def _create_run(db):
    from mmagent.state import repositories
    pid = repositories.create_project(db, name="t", root_path=__import__("pathlib").Path("/tmp/x"))
    return repositories.create_run(db, project_id=pid, profile="std")


class TestProviderAuthFailure:
    """401/403 → FAILED (not retryable, not INTERNAL)。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403])
    async def test_auth_failure_propagates(self, tmp_path, status):
        from mmagent.api.projects import create_project
        from mmagent.workspace.path_policy import PathPolicy
        from mmagent.workspace.permissions import PermissionChecker as PC
        from mmagent.workspace.permissions import RolePermissions as RP

        root = tmp_path / f"auth{status}"
        handle = create_project(root, name="t")
        db = handle.workspace.db
        policy = PathPolicy(root)
        run_id = repositories.create_run(db, project_id=handle.project_id, profile="std")

        def handler(request):
            return httpx.Response(status, json={"error": "bad key"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        from mmagent.providers.openai_chat import OpenAIChatProvider
        provider = OpenAIChatProvider("https://api.test/v1", lambda: "k", client=client)

        perms = RP(role_id="t", read_scopes=("**",), write_scopes=("**",), allowed_tools=frozenset())
        checker = PC(perms, policy)
        from mmagent.tools.registry import ToolRegistry as TR
        loop = AgentLoop(db, provider, TR(), checker, policy)
        t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key=f"auth{status}", role_id="t")
        spec = AgentTask(task_id=t.id, node_key=f"auth{status}", role_id="t",
                         system_prompt="s", instructions="i", model="m")
        outcome = await loop.run(spec)
        assert outcome.status == TaskStatus.FAILED
        assert outcome.error_kind == ErrorKind.PROVIDER_AUTH
        assert outcome.retryable is False
        db.close()


class TestProviderNetworkFailure:
    """network error → FAILED with retryable flag。"""

    @pytest.mark.asyncio
    async def test_network_error_propagates(self, tmp_path):
        from mmagent.api.projects import create_project
        from mmagent.workspace.path_policy import PathPolicy
        from mmagent.workspace.permissions import PermissionChecker as PC
        from mmagent.workspace.permissions import RolePermissions as RP

        root = tmp_path / "net"
        handle = create_project(root, name="t")
        db = handle.workspace.db
        policy = PathPolicy(root)
        run_id = repositories.create_run(db, project_id=handle.project_id, profile="std")

        import httpx

        from mmagent.providers.openai_chat import OpenAIChatProvider

        def handler(request):
            raise httpx.ConnectError("connection refused")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAIChatProvider("https://unreachable.test/v1", lambda: "k", client=client)

        perms = RP(role_id="t", read_scopes=("**",), write_scopes=("**",), allowed_tools=frozenset())
        checker = PC(perms, policy)
        from mmagent.tools.registry import ToolRegistry as TR
        loop = AgentLoop(db, provider, TR(), checker, policy)
        t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="net_test", role_id="t")
        spec = AgentTask(task_id=t.id, node_key="net_test", role_id="t",
                         system_prompt="s", instructions="i", model="m")
        outcome = await loop.run(spec)
        assert outcome.status == TaskStatus.FAILED
        assert outcome.error_kind.value in ("provider_network", "provider_protocol")
        db.close()


class TestRateLimit429Run:
    """429 → QUEUED (not FAILED) → retryable。"""

    @pytest.mark.asyncio
    async def test_429_returns_queued(self, tmp_path):

        from mmagent.tools.registry import ToolRegistry as TR
        from mmagent.workspace.path_policy import PathPolicy
        from mmagent.workspace.permissions import PermissionChecker as PC
        from mmagent.workspace.permissions import RolePermissions as RP

        root = tmp_path / "r429"
        handle = __import__("mmagent.api.projects", fromlist=["create_project"]).create_project(root, name="t")
        db = handle.workspace.db
        policy = PathPolicy(root)
        run_id = repositories.create_run(db, project_id=handle.project_id, profile="std")

        provider = MockProvider(MockScript([MockTurn(text="done")]))
        provider.queue_error(RateLimitError("429", retry_after_s=0.1))

        perms = RP(role_id="t", read_scopes=("**",), write_scopes=("**",),
                   allowed_tools=frozenset({"fs.read", "fs.write"}))
        checker = PC(perms, policy)
        loop = AgentLoop(db, provider, TR(), checker, policy)
        spec = _spec(db, run_id, "r429")
        outcome = await loop.run(spec)
        assert outcome.status == TaskStatus.QUEUED
        assert outcome.retryable is True
        db.close()


class TestServer5xxRun:
    """5xx → FAILED (server, retryable)。"""

    @pytest.mark.asyncio
    async def test_500_propagates_as_server_error(self, tmp_path):
        import httpx

        from mmagent.providers.openai_chat import OpenAIChatProvider
        from mmagent.tools.registry import ToolRegistry as TR
        from mmagent.workspace.path_policy import PathPolicy
        from mmagent.workspace.permissions import PermissionChecker as PC
        from mmagent.workspace.permissions import RolePermissions as RP

        root = tmp_path / "s5xx"
        handle = __import__("mmagent.api.projects", fromlist=["create_project"]).create_project(root, name="t")
        db = handle.workspace.db
        policy = PathPolicy(root)
        run_id = repositories.create_run(db, project_id=handle.project_id, profile="std")

        def handler(request):
            return httpx.Response(500, json={"error": "internal"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAIChatProvider("https://api.test/v1", lambda: "k", client=client)

        perms = RP(role_id="t", read_scopes=("**",), write_scopes=("**",), allowed_tools=frozenset())
        checker = PC(perms, policy)
        loop = AgentLoop(db, provider, TR(), checker, policy)
        t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="s5xx", role_id="t")
        spec = AgentTask(task_id=t.id, node_key="s5xx", role_id="t",
                         system_prompt="s", instructions="i", model="m")
        outcome = await loop.run(spec)
        assert outcome.status == TaskStatus.FAILED
        assert outcome.error_kind.value == "provider_server"
        db.close()
