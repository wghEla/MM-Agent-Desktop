from __future__ import annotations

import json
from pathlib import Path

import pytest

import mmagent.orchestration.engine as engine_mod
from mmagent.agent.errors import TaskCancelled
from mmagent.api.projects import create_project
from mmagent.orchestration.engine import (
    PaperFoundryEngine,
    PipelineHooks,
    PipelinePaused,
    PipelineStageError,
    request_pause,
)
from mmagent.providers.mock import MockProvider, MockScript
from mmagent.state import events, repositories
from mmagent.state.models import RunStatus
from mmagent.tools.registry import ToolRegistry


def _engine(tmp_path: Path):
    handle = create_project(tmp_path / "proj", name="engine", profile="快速")
    run_id = repositories.create_run(
        handle.workspace.db, project_id=handle.project_id, profile="快速"
    )
    handle.workspace.acquire_run_lock(run_id)
    eng = PaperFoundryEngine(
        handle.workspace, MockProvider(MockScript([])), ToolRegistry(), run_id,
        hooks=PipelineHooks(
            compile_paper=lambda root: {"rc": 0, "errors": [], "pages": 10},
            render_pages=lambda root: [root / "论文" / "页" / "1.png"],
        ),
    )
    return handle, run_id, eng


def _plan(root: Path) -> None:
    (root / "交接").mkdir(parents=True, exist_ok=True)
    (root / "交接" / "计划.json").write_text(
        json.dumps({"问题清单": [{"编号": 1}]}, ensure_ascii=False),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_engine_runs_authoritative_stage_order(monkeypatch, tmp_path: Path) -> None:
    handle, run_id, eng = _engine(tmp_path)
    calls: list[str] = []
    _plan(handle.workspace.root)

    async def s0(*args, **kwargs):
        calls.append("S0")
        return {"g0_pass": True, "g0_issues": []}
    async def s1(*args, **kwargs):
        calls.append("S1")
        return {"g1_pass": True, "g1_issues": []}
    async def s2(*args, **kwargs):
        calls.append("S2")
        return {"gates": {"问1": {"pass": True, "issues": []}}, "downgraded": []}
    async def s3(*args, **kwargs):
        calls.append("S3")
        return {"g3_pass": True, "g3_issues": []}
    async def s4(*args, **kwargs):
        calls.append("S4")
        return {"g4_pass": True, "g4_issues": []}
    async def s5(*args, **kwargs):
        calls.append("S5")
        return {"converged": True}
    async def s5a(*args, **kwargs):
        calls.append("S5a")
        return {"pass": True}
    async def s5b(*args, **kwargs):
        calls.append("S5b")
        events.append_event(
            handle.workspace.db, "checkpoint.s5b",
            {"beauty_baseline_pages": 10}, run_id=run_id,
        )
        return {"pass": True, "beauty_baseline_pages": 10}
    async def g5(*args, **kwargs):
        calls.append("G5")
        return {"pass": True, "issues": []}
    async def s6(*args, **kwargs):
        calls.append("S6")
        return {"pass": True, "issues": []}

    for name, func in {
        "run_s0": s0, "run_s1": s1, "run_s2": s2, "run_s3": s3, "run_s4": s4,
        "run_s5": s5, "run_s5a": s5a, "run_s5b": s5b, "run_g5": g5, "run_s6": s6,
    }.items():
        monkeypatch.setattr(engine_mod, name, func)

    result = await eng.run()
    assert calls == ["S0", "S1", "S2", "S3", "S4", "S5", "S5a", "S5b", "G5", "S6"]
    assert result.degraded_questions == ()
    row = handle.workspace.db.query_one("SELECT status FROM runs WHERE id = ?", (run_id,))
    assert row["status"] == RunStatus.SUCCEEDED.value

    checkpoints = [
        e.payload["key"] for e in events.query_events(
            handle.workspace.db, run_id=run_id, type="checkpoint.stage"
        )
    ]
    assert checkpoints == [
        "S0", "G0", "S1", "G1", "S2", "G2", "S3", "G3",
        "S4", "G4", "S5", "S5a", "S5b", "G5", "S6",
    ]
    handle.workspace.db.close()


@pytest.mark.asyncio
async def test_resume_skips_completed_stage_checkpoints(monkeypatch, tmp_path: Path) -> None:
    handle, run_id, eng = _engine(tmp_path)
    _plan(handle.workspace.root)
    for key in ("S0", "G0", "S1", "G1"):
        events.append_event(
            handle.workspace.db, "checkpoint.stage", {"key": key}, run_id=run_id
        )

    calls: list[str] = []

    async def should_not_run(*args, **kwargs):
        raise AssertionError("completed stage reran")

    async def s2(*args, **kwargs):
        calls.append("S2")
        return {"gates": {"问1": {"pass": True, "issues": []}}, "downgraded": [1]}
    async def pass_s3(*args, **kwargs):
        calls.append("S3")
        return {"g3_pass": True, "g3_issues": []}
    async def pass_s4(*args, **kwargs):
        calls.append("S4")
        return {"g4_pass": True, "g4_issues": []}
    async def pass_s5(*args, **kwargs):
        calls.append("S5")
        return {"converged": True}
    async def pass_s5a(*args, **kwargs):
        calls.append("S5a")
        return {"pass": True}
    async def pass_s5b(*args, **kwargs):
        calls.append("S5b")
        return {"pass": True, "beauty_baseline_pages": 10}
    async def pass_g5(*args, **kwargs):
        calls.append("G5")
        return {"pass": True, "issues": []}
    async def pass_s6(*args, **kwargs):
        calls.append("S6")
        return {"pass": True, "issues": []}

    monkeypatch.setattr(engine_mod, "run_s0", should_not_run)
    monkeypatch.setattr(engine_mod, "run_s1", should_not_run)
    monkeypatch.setattr(engine_mod, "run_s2", s2)
    monkeypatch.setattr(engine_mod, "run_s3", pass_s3)
    monkeypatch.setattr(engine_mod, "run_s4", pass_s4)
    monkeypatch.setattr(engine_mod, "run_s5", pass_s5)
    monkeypatch.setattr(engine_mod, "run_s5a", pass_s5a)
    monkeypatch.setattr(engine_mod, "run_s5b", pass_s5b)
    monkeypatch.setattr(engine_mod, "run_g5", pass_g5)
    monkeypatch.setattr(engine_mod, "run_s6", pass_s6)

    result = await eng.run(resume=True)
    assert result.skipped[:2] == ("S0", "S1")
    assert result.degraded_questions == (1,)
    assert calls[0] == "S2"
    handle.workspace.db.close()


@pytest.mark.asyncio
async def test_pause_stops_at_safe_boundary(monkeypatch, tmp_path: Path) -> None:
    handle, run_id, eng = _engine(tmp_path)
    _plan(handle.workspace.root)

    async def s0(*args, **kwargs):
        request_pause(handle.workspace.db, run_id)
        return {"g0_pass": True, "g0_issues": []}

    monkeypatch.setattr(engine_mod, "run_s0", s0)
    with pytest.raises(PipelinePaused):
        await eng.run()

    row = handle.workspace.db.query_one("SELECT status FROM runs WHERE id = ?", (run_id,))
    assert row["status"] == RunStatus.PAUSED.value
    assert not (handle.workspace.root / ".mmagent" / "run.lock").exists()
    handle.workspace.db.close()


@pytest.mark.asyncio
async def test_stage_failure_marks_run_failed(monkeypatch, tmp_path: Path) -> None:
    handle, run_id, eng = _engine(tmp_path)

    async def s0(*args, **kwargs):
        return {"g0_pass": False, "g0_issues": ["bad contract"]}

    monkeypatch.setattr(engine_mod, "run_s0", s0)
    with pytest.raises(PipelineStageError):
        await eng.run()

    row = handle.workspace.db.query_one("SELECT status FROM runs WHERE id = ?", (run_id,))
    assert row["status"] == RunStatus.FAILED.value
    assert events.query_events(handle.workspace.db, run_id=run_id, type="pipeline.failed")
    handle.workspace.db.close()


@pytest.mark.asyncio
async def test_cancel_marks_run_cancelled_not_failed(monkeypatch, tmp_path: Path) -> None:
    handle, run_id, eng = _engine(tmp_path)

    async def s0(*args, **kwargs):
        eng.cancel_run("user stop")
        eng.cancel.check()
        return {"g0_pass": True, "g0_issues": []}

    monkeypatch.setattr(engine_mod, "run_s0", s0)
    with pytest.raises(TaskCancelled):
        await eng.run()

    row = handle.workspace.db.query_one("SELECT status FROM runs WHERE id = ?", (run_id,))
    assert row["status"] == RunStatus.CANCELLED.value
    assert events.query_events(
        handle.workspace.db, run_id=run_id, type="pipeline.cancelled"
    )
    assert not events.query_events(
        handle.workspace.db, run_id=run_id, type="pipeline.failed"
    )
    handle.workspace.db.close()
