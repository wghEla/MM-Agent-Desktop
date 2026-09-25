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


@pytest.mark.asyncio
async def test_controller_can_cancel_persisted_paused_run_after_restart(tmp_path) -> None:
    handle = create_project(tmp_path / "proj", name="persisted-cancel", profile="标准")
    controller = RunController()
    run_id = repositories.create_run(
        handle.workspace.db, project_id=handle.project_id, profile="标准"
    )
    handle.workspace.acquire_run_lock(run_id)
    repositories.set_run_status(handle.workspace.db, run_id, RunStatus.RUNNING)
    repositories.set_run_status(handle.workspace.db, run_id, RunStatus.PAUSED)
    handle.workspace.release_run_lock()

    await controller.cancel(run_id, "stop after restart", handle=handle)

    status = controller.status(handle, run_id)
    assert status["status"] == RunStatus.CANCELLED.value
    assert status["active_in_sidecar"] is False
    handle.workspace.db.close()


def test_controller_lists_persisted_runs_newest_first(tmp_path) -> None:
    handle = create_project(tmp_path / "proj", name="run-history", profile="标准")
    controller = RunController()
    first = repositories.create_run(
        handle.workspace.db, project_id=handle.project_id, profile="快速"
    )
    second = repositories.create_run(
        handle.workspace.db, project_id=handle.project_id, profile="标准"
    )

    listed = controller.list_status(handle)

    assert [item["id"] for item in listed] == [second, first]
    assert all(item["active_in_sidecar"] is False for item in listed)
    handle.workspace.db.close()


@pytest.mark.asyncio
async def test_controller_reacquires_lock_when_cancelling_finished_paused_task(
    monkeypatch, tmp_path
) -> None:
    handle = create_project(tmp_path / "proj-finished", name="finished-pause", profile="标准")
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
    await controller.pause(run_id)

    # FakeEngine does not own the real engine's pause-boundary cleanup, so
    # simulate the production Engine releasing run.lock at PipelinePaused.
    active.engine.release.set()
    await controller.wait(run_id)
    handle.workspace.release_run_lock()
    assert active.task.done()

    await controller.cancel(run_id, "cancel paused run", handle=handle)

    status = controller.status(handle, run_id)
    assert status["status"] == RunStatus.CANCELLED.value
    handle.workspace.db.close()
