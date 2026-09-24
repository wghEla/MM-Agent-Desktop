"""Authoritative paper-foundry pipeline orchestrator.

The stage modules contain domain logic; this engine owns run-level sequencing,
checkpoint/resume semantics, crash recovery, and run-state closure.

It intentionally treats SQLite + append-only events as the state truth.  File
artifacts are evidence/carriers, not the execution state machine.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mmagent.agent.errors import TaskCancelled
from mmagent.mm.config.profiles import get_profile
from mmagent.mm.pipeline.s0_s1 import run_s0, run_s1
from mmagent.mm.pipeline.s2_model import run_s2
from mmagent.mm.pipeline.s3_figures import run_s3
from mmagent.mm.pipeline.s4_paper import run_s4
from mmagent.mm.pipeline.s5_finalize import run_g5, run_s5a, run_s5b
from mmagent.mm.pipeline.s5_review import run_s5
from mmagent.mm.pipeline.s6_finalize import run_s6
from mmagent.providers.base import BaseProvider
from mmagent.runtime.cancellation import CancellationToken
from mmagent.state import events, repositories
from mmagent.state.models import RunStatus, TaskStatus
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.path_policy import PathPolicy
from mmagent.workspace.root import ProjectWorkspace

CompileFn = Callable[[Path], dict[str, Any]]
RenderFn = Callable[[Path], list[Path]]


class PipelineStageError(RuntimeError):
    def __init__(self, stage: str, issues: list[str] | None = None):
        self.stage = stage
        self.issues = list(issues or [])
        detail = "; ".join(self.issues) if self.issues else "stage failed"
        super().__init__(f"{stage}: {detail}")


class PipelinePaused(RuntimeError):
    """Raised only at a safe stage boundary after an external pause request."""


@dataclass(frozen=True)
class PipelineHooks:
    compile_paper: CompileFn | None = None
    render_pages: RenderFn | None = None


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    completed: tuple[str, ...]
    skipped: tuple[str, ...]
    degraded_questions: tuple[int, ...] = ()


class PaperFoundryEngine:
    """Runs the complete S0→S6 workflow for one already-created run."""

    def __init__(
        self,
        workspace: ProjectWorkspace,
        provider: BaseProvider,
        registry: ToolRegistry,
        run_id: str,
        *,
        hooks: PipelineHooks | None = None,
        cancel: CancellationToken | None = None,
    ):
        self.workspace = workspace
        self.db = workspace.db
        self.provider = provider
        self.registry = registry
        self.run_id = run_id
        self.policy = PathPolicy(workspace.root)
        self.hooks = hooks or PipelineHooks()
        self.cancel = cancel or CancellationToken()

    # ------------------------------------------------------------- state helpers
    def _run_row(self):
        row = self.db.query_one("SELECT status, profile FROM runs WHERE id = ?", (self.run_id,))
        if row is None:
            raise LookupError(f"run 不存在: {self.run_id}")
        return row

    def _completed_checkpoints(self) -> set[str]:
        return {
            str(e.payload.get("key"))
            for e in events.query_events(
                self.db, run_id=self.run_id, type="checkpoint.stage", limit=1000
            )
            if e.payload.get("key")
        }

    def _checkpoint(self, key: str, result: dict[str, Any] | None = None) -> None:
        events.append_event(
            self.db,
            "checkpoint.stage",
            {"key": key, "result": result or {}},
            run_id=self.run_id,
        )

    def _record_gate(self, gate: str, passed: bool, issues: list[str]) -> None:
        events.append_event(
            self.db,
            "gate.result",
            {"gate": gate, "pass": bool(passed), "issues": list(issues)},
            run_id=self.run_id,
        )

    def _check_boundary(self) -> None:
        self.cancel.check()
        row = self._run_row()
        if RunStatus(row["status"]) is RunStatus.PAUSED:
            events.append_event(
                self.db, "pipeline.paused_at_boundary", {}, run_id=self.run_id
            )
            raise PipelinePaused("run 已暂停；将在当前阶段边界停止")

    def cancel_run(self, reason: str = "user cancelled") -> None:
        """Request cooperative cancellation for this live engine instance."""
        self.cancel.cancel(reason)

    def recover_interrupted_tasks(self) -> int:
        """Crash recovery: active orphan tasks become FAILED, never assumed successful."""
        recovered = 0
        for task in repositories.list_tasks(self.db, self.run_id):
            if task.status in (
                TaskStatus.RUNNING,
                TaskStatus.WAITING_TOOL,
                TaskStatus.CANCEL_REQUESTED,
            ):
                repositories.recover_interrupted_task(
                    self.db,
                    task.id,
                    reason=(
                        "[pipeline_resume] 上次执行在活跃态中断；"
                        "副作用未知，按 fail-closed 标记 FAILED，后续阶段重建任务。"
                    ),
                )
                recovered += 1
        if recovered:
            events.append_event(
                self.db,
                "pipeline.recovered",
                {"interrupted_tasks": recovered},
                run_id=self.run_id,
            )
        return recovered

    def _start_or_resume_run(self) -> None:
        status = RunStatus(self._run_row()["status"])
        if status is RunStatus.CREATED:
            repositories.set_run_status(self.db, self.run_id, RunStatus.RUNNING)
        elif status is RunStatus.PAUSED:
            repositories.set_run_status(self.db, self.run_id, RunStatus.RUNNING)
        elif status is RunStatus.RUNNING:
            return
        else:
            raise RuntimeError(f"run 终态不能隐式恢复: {status.value}")

    def _problem_numbers(self) -> list[int]:
        plan_path = self.policy.root / "交接" / "计划.json"
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PipelineStageError("S1", [f"无法读取交接/计划.json: {exc}"]) from exc
        nums: list[int] = []
        for item in plan.get("问题清单", []):
            value = item.get("编号") if isinstance(item, dict) else None
            if isinstance(value, int):
                nums.append(value)
        if not nums:
            raise PipelineStageError("S1", ["计划.json 没有有效问题编号"])
        return nums

    # ------------------------------------------------------------- main driver
    async def run(self, *, resume: bool = True) -> PipelineResult:
        self._start_or_resume_run()
        if resume:
            self.recover_interrupted_tasks()

        completed = self._completed_checkpoints() if resume else set()
        done_now: list[str] = []
        skipped: list[str] = []
        degraded: list[int] = []

        async def execute_once(key: str, fn):
            self._check_boundary()
            if key in completed:
                skipped.append(key)
                return None
            events.append_event(
                self.db, "pipeline.stage_started", {"key": key}, run_id=self.run_id
            )
            try:
                result = await fn()
            except PipelinePaused:
                raise
            except BaseException as exc:
                events.append_event(
                    self.db,
                    "pipeline.stage_failed",
                    {"key": key, "error": repr(exc)},
                    run_id=self.run_id,
                )
                raise
            self._checkpoint(key, result if isinstance(result, dict) else {})
            done_now.append(key)
            completed.add(key)
            return result

        try:
            # S0 + G0
            async def s0():
                result = await run_s0(
                    self.db, self.provider, self.registry, self.policy, self.run_id,
                    cancel=self.cancel,
                )
                self._record_gate("G0", result["g0_pass"], result["g0_issues"])
                if not result["g0_pass"]:
                    raise PipelineStageError("G0", result["g0_issues"])
                return result
            await execute_once("S0", s0)
            if "S0" in completed and "G0" not in completed:
                self._checkpoint("G0")
                done_now.append("G0")
                completed.add("G0")

            # S1 + G1
            async def s1():
                result = await run_s1(
                    self.db, self.provider, self.registry, self.policy, self.run_id,
                    profile=self._run_row()["profile"],
                    cancel=self.cancel,
                )
                self._record_gate("G1", result["g1_pass"], result["g1_issues"])
                if not result["g1_pass"]:
                    raise PipelineStageError("G1", result["g1_issues"])
                return result
            await execute_once("S1", s1)
            if "S1" in completed and "G1" not in completed:
                self._checkpoint("G1")
                done_now.append("G1")
                completed.add("G1")

            problem_numbers = self._problem_numbers()
            plan_path = self.policy.root / "交接" / "计划.json"

            # S2 + per-question G2. Degraded release is an explicit continuation path.
            async def s2():
                result = await run_s2(
                    self.db, self.provider, self.registry, self.policy, self.run_id,
                    plan_path, cancel=self.cancel,
                )
                for q, gate_result in result.get("gates", {}).items():
                    self._record_gate(
                        f"G2:{q}",
                        bool(gate_result.get("pass")),
                        list(gate_result.get("issues", [])),
                    )
                return result
            s2_result = await execute_once("S2", s2)
            if isinstance(s2_result, dict):
                degraded.extend(int(x) for x in s2_result.get("downgraded", []))
            if "S2" in completed and "G2" not in completed:
                self._checkpoint("G2", {"downgraded": degraded})
                done_now.append("G2")
                completed.add("G2")

            # S3 + G3
            async def s3():
                result = await run_s3(
                    self.db, self.provider, self.registry, self.policy, self.run_id,
                    problem_numbers=problem_numbers,
                    profile=self._run_row()["profile"],
                    cancel=self.cancel,
                )
                self._record_gate("G3", result["g3_pass"], result["g3_issues"])
                if not result["g3_pass"]:
                    raise PipelineStageError("G3", result["g3_issues"])
                return result
            await execute_once("S3", s3)
            if "S3" in completed and "G3" not in completed:
                self._checkpoint("G3")
                done_now.append("G3")
                completed.add("G3")

            # S4 + G4
            async def s4():
                result = await run_s4(
                    self.db, self.provider, self.registry, self.policy, self.run_id,
                    problem_numbers=problem_numbers,
                    profile=self._run_row()["profile"],
                    compile_paper=self.hooks.compile_paper,
                    cancel=self.cancel,
                )
                self._record_gate("G4", result["g4_pass"], result["g4_issues"])
                if not result["g4_pass"]:
                    raise PipelineStageError("G4", result["g4_issues"])
                return result
            await execute_once("S4", s4)
            if "S4" in completed and "G4" not in completed:
                self._checkpoint("G4")
                done_now.append("G4")
                completed.add("G4")

            profile = get_profile(self._run_row()["profile"])

            # S5 may finish with unresolved ledger items; G5 is the publication blocker.
            async def s5():
                return await run_s5(
                    self.db, self.provider, self.registry, self.policy, self.run_id,
                    max_rounds=profile.审稿轮数,
                    compile_paper=self.hooks.compile_paper,
                    render_pages=self.hooks.render_pages,
                    cancel=self.cancel,
                )
            await execute_once("S5", s5)

            async def s5a():
                result = await run_s5a(
                    self.db, self.provider, self.registry, self.policy, self.run_id,
                    cancel=self.cancel,
                )
                if not result["pass"]:
                    raise PipelineStageError("S5a", ["摘要复述门未通过"])
                return result
            await execute_once("S5a", s5a)

            async def s5b():
                result = await run_s5b(
                    self.db, self.provider, self.registry, self.policy, self.run_id,
                    profile=profile.tier,
                    compile_paper=self.hooks.compile_paper,
                    render_pages=self.hooks.render_pages,
                    cancel=self.cancel,
                )
                if not result["pass"]:
                    raise PipelineStageError("S5b", list(result.get("issues", [])))
                return result
            s5b_result = await execute_once("S5b", s5b)

            baseline_pages = None
            if isinstance(s5b_result, dict):
                baseline_pages = s5b_result.get("beauty_baseline_pages")
            if baseline_pages is None:
                for event in events.query_events(
                    self.db, run_id=self.run_id, type="checkpoint.s5b", limit=100
                ):
                    value = event.payload.get("beauty_baseline_pages")
                    if isinstance(value, int) and value > 0:
                        baseline_pages = value
            if not isinstance(baseline_pages, int) or baseline_pages <= 0:
                raise PipelineStageError("G5", ["缺少美化后页数基线"])

            async def g5():
                result = await run_g5(
                    self.db, self.provider, self.registry, self.policy, self.run_id,
                    beauty_baseline_pages=baseline_pages,
                    compile_paper=self.hooks.compile_paper,
                    cancel=self.cancel,
                )
                if not result["pass"]:
                    raise PipelineStageError("G5", list(result.get("issues", [])))
                return result
            await execute_once("G5", g5)

            async def s6():
                result = await run_s6(
                    self.db, self.provider, self.registry, self.policy, self.run_id,
                    compile_paper=self.hooks.compile_paper,
                    render_pages=self.hooks.render_pages,
                    cancel=self.cancel,
                )
                if not result["pass"]:
                    raise PipelineStageError("S6", list(result.get("issues", [])))
                return result
            await execute_once("S6", s6)

            status = RunStatus(self._run_row()["status"])
            if status is RunStatus.RUNNING:
                repositories.set_run_status(self.db, self.run_id, RunStatus.SUCCEEDED)
            self.workspace.release_run_lock()
            return PipelineResult(
                run_id=self.run_id,
                completed=tuple(done_now),
                skipped=tuple(skipped),
                degraded_questions=tuple(sorted(set(degraded))),
            )

        except PipelinePaused:
            # PAUSED is durable state; release the process-owner lock so the
            # desktop controller can reacquire it on a later resume.
            self.workspace.release_run_lock()
            raise
        except TaskCancelled as exc:
            row = self._run_row()
            if RunStatus(row["status"]) is RunStatus.RUNNING:
                repositories.set_run_status(self.db, self.run_id, RunStatus.CANCELLED)
            self.workspace.release_run_lock()
            events.append_event(
                self.db,
                "pipeline.cancelled",
                {"reason": str(exc), "completed": sorted(completed)},
                run_id=self.run_id,
            )
            raise
        except BaseException as exc:
            row = self._run_row()
            if RunStatus(row["status"]) is RunStatus.RUNNING:
                repositories.set_run_status(self.db, self.run_id, RunStatus.FAILED)
            self.workspace.release_run_lock()
            events.append_event(
                self.db,
                "pipeline.failed",
                {"error": repr(exc), "completed": sorted(completed)},
                run_id=self.run_id,
            )
            raise


def request_pause(db, run_id: str) -> None:
    """Cooperative pause: current leg may finish; engine stops at next safe stage boundary."""
    repositories.set_run_status(db, run_id, RunStatus.PAUSED)


def request_resume(db, run_id: str) -> None:
    """Move PAUSED -> RUNNING. Call PaperFoundryEngine.run(resume=True) afterwards."""
    repositories.set_run_status(db, run_id, RunStatus.RUNNING)
