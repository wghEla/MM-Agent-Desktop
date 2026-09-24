from __future__ import annotations

import json

import pytest

from mmagent.agent.loop import AgentLoop, AgentTask
from mmagent.api.projects import create_project
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.providers.normalized import ImagePart
from mmagent.state import repositories
from mmagent.state.models import TaskStatus
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.path_policy import PathPolicy
from mmagent.workspace.permissions import PermissionChecker, RolePermissions


class CapturingMockProvider(MockProvider):
    def __init__(self, script):
        super().__init__(script)
        self.requests = []

    async def generate(self, messages, tools, **kwargs):
        self.requests.append(messages)
        return await super().generate(messages, tools, **kwargs)


@pytest.mark.asyncio
async def test_agent_image_input_respects_scope_and_redacts_sqlite(tmp_path) -> None:
    handle = create_project(tmp_path / "proj", name="vision", profile="快速")
    try:
        root = handle.workspace.root
        image = root / "论文" / "页" / "page_001.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"fake-png-bytes")

        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        task = repositories.create_task(
            handle.workspace.db,
            run_id=run_id,
            stage_key="S6",
            node_key="S6:vision",
            role_id="beautifier",
        )
        perms = RolePermissions(
            role_id="beautifier",
            read_scopes=("论文/页/*.png",),
            write_scopes=(),
            allowed_tools=frozenset(),
        )
        provider = CapturingMockProvider(MockScript([MockTurn(text="done")]))
        loop = AgentLoop(
            handle.workspace.db,
            provider,
            ToolRegistry(),
            PermissionChecker(perms, PathPolicy(root)),
            PathPolicy(root),
        )
        outcome = await loop.run(
            AgentTask(
                task_id=task.id,
                node_key="S6:vision",
                role_id="beautifier",
                system_prompt="inspect",
                instructions="inspect the attached page",
                model="mock",
                image_paths=["论文/页/page_001.png"],
            )
        )
        assert outcome.status is TaskStatus.SUCCEEDED
        user = provider.requests[0][1]
        images = [part for part in user.content if isinstance(part, ImagePart)]
        assert len(images) == 1
        assert images[0].b64 != "<omitted>"

        rows = handle.workspace.db.query(
            "SELECT content_json FROM messages ORDER BY seq"
        )
        persisted = "
".join(row["content_json"] for row in rows)
        assert "ZmFrZS1wbmctYnl0ZXM=" not in persisted
        assert "<omitted>" in persisted
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_agent_image_input_denied_outside_role_scope(tmp_path) -> None:
    handle = create_project(tmp_path / "proj", name="vision-denied", profile="快速")
    try:
        root = handle.workspace.root
        image = root / "论文" / "页" / "page_001.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"fake-png-bytes")

        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        task = repositories.create_task(
            handle.workspace.db,
            run_id=run_id,
            stage_key="S6",
            node_key="S6:vision-denied",
            role_id="reader",
        )
        perms = RolePermissions(
            role_id="reader",
            read_scopes=("输入/**",),
            write_scopes=(),
            allowed_tools=frozenset(),
        )
        provider = MockProvider(MockScript([MockTurn(text="should not run")]))
        loop = AgentLoop(
            handle.workspace.db,
            provider,
            ToolRegistry(),
            PermissionChecker(perms, PathPolicy(root)),
            PathPolicy(root),
        )
        outcome = await loop.run(
            AgentTask(
                task_id=task.id,
                node_key="S6:vision-denied",
                role_id="reader",
                system_prompt="inspect",
                instructions="inspect",
                model="mock",
                image_paths=["论文/页/page_001.png"],
            )
        )
        assert outcome.status is TaskStatus.FAILED
        assert provider.script.cursor == 0
    finally:
        handle.workspace.db.close()
