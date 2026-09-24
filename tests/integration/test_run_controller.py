from __future__ import annotations

import asyncio

import pytest

import mmagent.api.runs as runs_mod
from mmagent.api.projects import create_project
from mmagent.api.runs import RunController
from mmagent.providers.mock import MockProvider, MockScript
from mmagent.state import repositories
from mmagent.state.models import RunStatus
from mmagent.tools.registry import ToolRegistry


class FakeEngine:
    def __init__(self, workspace, provider, registry, run_id, *, hooks=None):
        self.workspace = workspace
        self.db = workspace.db
        self.provider = provider
        self.run_id = run_id
        self.cancelled = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, *, resume=True):
        row = self.db.query_one("SELECT status FROM runs WHERE id = ?", (self.run_id,))
        if RunStatus(row["status"]) is RunStatus.CREATED:
            repositories.set_run_status(self.db, self.run_id, RunStatus.RUNNING)
        self.started.set()
        await self.release.wait()
        row = self.db.query_one("SELECT status FROM runs WHERE id = ?", (self.run_id,))
        if RunStatus(row["status"]) is RunStatus.RUNNING:
            repositories.set_run_status(self.db, self.run_id, RunStatus.SUCCEEDED)

    def cancel_run(self, reason="user cancelled"):
        self.cancelled = True
        row = self.db.query_one("SELECT status FROM runs WHERE id = ?", (self.run_id,))
        if RunStatus(row["status"]) is RunStatus.RUNNING:
            repositories.set_run_status(self.db, self.run_id, RunStatus.CANCELLED)
        self.release.set()


@pytest.mark.asyncio
async def test_controller_start_status_and_pause(monkeypatch, tmp_path) -> None:
    handle = create_project(tmp_path / "proj", name="controller", profile="standard")
    monkeypatch.setattr(runs_mod, "PaperFoundryEngine", FakeEngine)
    controller = RunController()

    run_id = await controller.start(
        handle,
        provider=MockProvider(MockScript([])),
        registry=ToolRegistry(),
        profile="standard",
    )
    active = controller._active[run_id]
    await active.engine.started.wait()

    status = controller.status(handle, run_id)
    assert status["status"] == RunStatus.RUNNING.value
    assert status["profile"] == "标准"
    assert status["active_in_sidecar"] is True

    await controller.pause(run_id)
    status = controller.status(handle, run_id)
    assert status["status"] == RunStatus.PAUSED.value

    active.engine.release.set()
    await controller.wait(run_id)
    handle.workspace.release_run_lock()
    handle.workspace.db.close()


@pytest.mark.asyncio
async def test_controller_cancel_live_run(monkeypatch, tmp_path) -> None:
    handle = create_project(tmp_path / "proj", name="controller-cancel", profile="标准")
    monkeypatch.setattr(runs_mod, "PaperFoundryEngine", FakeEngine)
    controller = RunController()

    run_id = await controller.start(
        handle,
        provider=MockProvider(MockScript([])),
        registry=ToolRegistry(),
        profile="快速",
    )
    active = controller._active[run_id]
    await active.engine.started.wait()

    await controller.cancel(run_id, "stop button")
    await controller.wait(run_id)

    status = controller.status(handle, run_id)
    assert status["status"] == RunStatus.CANCELLED.value
    assert active.engine.cancelled is True
    handle.workspace.release_run_lock()
    handle.workspace.db.close()



@pytest.mark.asyncio
async def test_controller_shutdown_preserves_run_as_paused(monkeypatch, tmp_path) -> None:
    handle = create_project(tmp_path / "proj", name="controller-shutdown", profile="标准")
    monkeypatch.setattr(runs_mod, "PaperFoundryEngine", FakeEngine)
    controller = RunController()

    run_id = await controller.start(
        handle,
        provider=MockProvider(MockScript([])),
        registry=ToolRegistry(),
        profile="标准",
    )
    active = controller._active[run_id]
    await active.engine.started.wait()

    await controller.shutdown()

    status = controller.status(handle, run_id)
    assert status["status"] == RunStatus.PAUSED.value
    assert status["active_in_sidecar"] is False

    # The shutdown path must release the durable single-run lock so a restarted
    # sidecar can acquire it and resume from checkpoints.
    handle.workspace.acquire_run_lock(run_id)
    handle.workspace.release_run_lock()
    handle.workspace.db.close()
