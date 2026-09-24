"""Run-control API used by the desktop sidecar.

This module deliberately owns only process-local control of active engines.
Durable state remains in each project's SQLite database, so a restarted
sidecar can reconstruct status and resume from stage checkpoints.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from mmagent.api.projects import ProjectHandle, start_run
from mmagent.mm.config.profiles import normalize_profile
from mmagent.orchestration.engine import (
    PaperFoundryEngine,
    PipelineHooks,
    PipelinePaused,
)
from mmagent.providers.base import BaseProvider
from mmagent.state import repositories
from mmagent.state.models import RunStatus
from mmagent.tools.registry import ToolRegistry


@dataclass
class ActiveRun:
    handle: ProjectHandle
    engine: PaperFoundryEngine
    task: asyncio.Task
    last_error: str | None = None


class RunController:
    """Own live pipeline tasks while delegating durable truth to SQLite."""

    def __init__(self) -> None:
        self._active: dict[str, ActiveRun] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        handle: ProjectHandle,
        *,
        provider: BaseProvider,
        registry: ToolRegistry,
        profile: str = "标准",
        hooks: PipelineHooks | None = None,
    ) -> str:
        """Create and start a new run. Returns immediately with run_id."""
        canonical = normalize_profile(profile)
        async with self._lock:
            run_id = start_run(handle, profile=canonical)
            engine = PaperFoundryEngine(
                handle.workspace, provider, registry, run_id, hooks=hooks
            )
            task = asyncio.create_task(
                self._drive(run_id, engine, resume=True),
                name=f"mmagent-run-{run_id}",
            )
            self._active[run_id] = ActiveRun(handle=handle, engine=engine, task=task)
            return run_id

    async def resume(
        self,
        handle: ProjectHandle,
        run_id: str,
        *,
        provider: BaseProvider,
        registry: ToolRegistry,
        hooks: PipelineHooks | None = None,
    ) -> None:
        """Resume a PAUSED/RUNNING crashed run from durable checkpoints."""
        async with self._lock:
            current = self._active.get(run_id)
            if current and not current.task.done():
                raise RuntimeError(f"run 已在本进程活动: {run_id}")

            row = handle.workspace.db.query_one(
                "SELECT status FROM runs WHERE id = ?", (run_id,)
            )
            if row is None:
                raise LookupError(f"run 不存在: {run_id}")
            status = RunStatus(row["status"])
            if status not in (RunStatus.PAUSED, RunStatus.RUNNING):
                raise RuntimeError(f"run 状态不可续跑: {status.value}")

            # A restarted sidecar may inherit a stale run.lock from a dead PID.
            handle.workspace.acquire_run_lock(run_id)
            engine = PaperFoundryEngine(
                handle.workspace, provider, registry, run_id, hooks=hooks
            )
            task = asyncio.create_task(
                self._drive(run_id, engine, resume=True),
                name=f"mmagent-run-{run_id}",
            )
            self._active[run_id] = ActiveRun(handle=handle, engine=engine, task=task)

    async def pause(self, run_id: str) -> None:
        """Request a cooperative pause; current stage finishes at its safe boundary."""
        active = self._require_active(run_id)
        row = active.handle.workspace.db.query_one(
            "SELECT status FROM runs WHERE id = ?", (run_id,)
        )
        if row is None:
            raise LookupError(run_id)
        status = RunStatus(row["status"])
        if status is RunStatus.PAUSED:
            return
        if status is not RunStatus.RUNNING:
            raise RuntimeError(f"只有 RUNNING 可暂停，当前 {status.value}")
        repositories.set_run_status(
            active.handle.workspace.db, run_id, RunStatus.PAUSED
        )

    async def cancel(self, run_id: str, reason: str = "user cancelled") -> None:
        """Cancel a running or paused run with correct durable run status."""
        active = self._active.get(run_id)
        if active is not None and not active.task.done():
            active.engine.cancel_run(reason)
            return

        if active is None:
            raise LookupError(f"run 不在当前 sidecar 控制中: {run_id}")
        row = active.handle.workspace.db.query_one(
            "SELECT status FROM runs WHERE id = ?", (run_id,)
        )
        if row is None:
            raise LookupError(run_id)
        status = RunStatus(row["status"])
        if status is RunStatus.PAUSED:
            repositories.set_run_status(
                active.handle.workspace.db, run_id, RunStatus.CANCELLED
            )
            active.handle.workspace.release_run_lock()
            return
        if status is RunStatus.CANCELLED:
            return
        raise RuntimeError(f"run 状态不可取消: {status.value}")

    def status(self, handle: ProjectHandle, run_id: str) -> dict[str, Any]:
        row = handle.workspace.db.query_one(
            "SELECT id, status, profile, started_at, ended_at, created_at "
            "FROM runs WHERE id = ?",
            (run_id,),
        )
        if row is None:
            raise LookupError(run_id)
        active = self._active.get(run_id)
        return {
            **dict(row),
            "active_in_sidecar": bool(active and not active.task.done()),
            "last_error": active.last_error if active else None,
        }

    async def wait(self, run_id: str) -> Any:
        active = self._require_active(run_id)
        return await active.task

    async def shutdown(self) -> None:
        """Stop process-local tasks while preserving unfinished runs as resumable."""
        tasks = [
            active.task
            for active in self._active.values()
            if not active.task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def prune_finished(self) -> int:
        finished = [rid for rid, active in self._active.items() if active.task.done()]
        for rid in finished:
            self._active.pop(rid, None)
        return len(finished)

    def _require_active(self, run_id: str) -> ActiveRun:
        active = self._active.get(run_id)
        if active is None:
            raise LookupError(f"run 不在当前 sidecar 控制中: {run_id}")
        return active

    async def _drive(
        self, run_id: str, engine: PaperFoundryEngine, *, resume: bool
    ) -> Any:
        try:
            return await engine.run(resume=resume)
        except PipelinePaused:
            # Pause is an expected control-flow boundary, not an error.
            return None
        except asyncio.CancelledError:
            # Controller/sidecar shutdown is resumable.  Explicit user Stop uses
            # engine.cancel_run() through cancel() and remains CANCELLED.
            row = engine.db.query_one(
                "SELECT status FROM runs WHERE id = ?", (run_id,)
            )
            if row is not None and RunStatus(row["status"]) is RunStatus.RUNNING:
                repositories.set_run_status(
                    engine.db, run_id, RunStatus.PAUSED
                )
            engine.workspace.release_run_lock()
            raise
        except BaseException as exc:
            active = self._active.get(run_id)
            if active is not None:
                active.last_error = repr(exc)
            raise
        finally:
            await engine.provider.aclose()
