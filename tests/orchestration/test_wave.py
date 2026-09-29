from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mmagent.agent.errors import RateLimitError
from mmagent.api.projects import create_project
from mmagent.orchestration.role_leg import run_role_leg
from mmagent.orchestration.wave import WaveJob, current_wave_concurrency, run_status_wave
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.state import events, repositories
from mmagent.tools.filesystem import FsReadTool, FsWriteTool
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy


def _run_ctx(tmp_path: Path):
    handle = create_project(tmp_path / "proj", name="wave", profile="标准")
    run_id = repositories.create_run(
        handle.workspace.db, project_id=handle.project_id, profile="标准"
    )
    return handle, run_id


@pytest.mark.asyncio
async def test_wave_bounds_concurrency_to_four(tmp_path: Path) -> None:
    handle, run_id = _run_ctx(tmp_path)
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def job() -> str:
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.02)
        async with lock:
            active -= 1
        return "SUCCEEDED"

    try:
        outcome = await run_status_wave(
            handle.workspace.db,
            run_id,
            [WaveJob(f"j{i}", job) for i in range(8)],
            wave_key="test-bound",
        )
        assert set(outcome.results.values()) == {"SUCCEEDED"}
        assert peak == 4
        assert outcome.start_concurrency == 4
        assert outcome.end_concurrency == 4
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_429_reduces_next_pass_and_persists(tmp_path: Path) -> None:
    handle, run_id = _run_ctx(tmp_path)
    calls = {"limited": 0, "ok": 0}

    async def limited() -> str:
        calls["limited"] += 1
        return "QUEUED" if calls["limited"] == 1 else "SUCCEEDED"

    async def ok() -> str:
        calls["ok"] += 1
        return "SUCCEEDED"

    try:
        outcome = await run_status_wave(
            handle.workspace.db,
            run_id,
            [WaveJob("limited", limited), WaveJob("ok", ok)],
            wave_key="test-429",
        )

        assert outcome.results == {"ok": "SUCCEEDED", "limited": "SUCCEEDED"}
        assert outcome.attempts == {"limited": 2, "ok": 1}
        assert outcome.rate_limited_jobs == ("limited",)
        assert outcome.start_concurrency == 4
        assert outcome.end_concurrency == 3
        assert current_wave_concurrency(handle.workspace.db, run_id) == 3

        reductions = events.query_events(
            handle.workspace.db,
            run_id=run_id,
            type="wave.concurrency_reduced",
        )
        assert len(reductions) == 1
        assert reductions[0].payload["from"] == 4
        assert reductions[0].payload["to"] == 3
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_repeated_429_stops_at_floor_two(tmp_path: Path) -> None:
    handle, run_id = _run_ctx(tmp_path)

    async def always_limited() -> str:
        return "QUEUED"

    try:
        for idx in range(3):
            await run_status_wave(
                handle.workspace.db,
                run_id,
                [WaveJob(f"limited-{idx}", always_limited)],
                wave_key=f"floor-{idx}",
            )

        assert current_wave_concurrency(handle.workspace.db, run_id) == 2
        floor_events = events.query_events(
            handle.workspace.db,
            run_id=run_id,
            type="wave.rate_limited_at_floor",
        )
        assert floor_events
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_failed_leg_retries_once_but_cancelled_does_not(tmp_path: Path) -> None:
    handle, run_id = _run_ctx(tmp_path)
    calls = {"failed": 0, "cancelled": 0}

    async def failed_then_ok() -> str:
        calls["failed"] += 1
        return "FAILED" if calls["failed"] == 1 else "SUCCEEDED"

    async def cancelled() -> str:
        calls["cancelled"] += 1
        return "CANCELLED"

    try:
        outcome = await run_status_wave(
            handle.workspace.db,
            run_id,
            [
                WaveJob("failed", failed_then_ok),
                WaveJob("cancelled", cancelled),
            ],
            wave_key="retry",
        )

        assert outcome.results["failed"] == "SUCCEEDED"
        assert outcome.results["cancelled"] == "CANCELLED"
        assert calls == {"failed": 2, "cancelled": 1}
    finally:
        handle.workspace.db.close()



@pytest.mark.asyncio
async def test_real_role_leg_429_requeues_reduces_and_retries_same_node(
    tmp_path: Path,
) -> None:
    handle, run_id = _run_ctx(tmp_path)
    provider = MockProvider(MockScript([
        MockTurn(tool_calls=[(
            "write",
            "fs.write",
            {"path": "交接/读题体检.md", "content": "429 retry recovered"},
        )]),
        MockTurn(text="完成"),
    ]))
    provider.queue_error(RateLimitError("429", retry_after_s=0))

    registry = ToolRegistry()
    registry.register(FsReadTool())
    registry.register(FsWriteTool())
    policy = PathPolicy(handle.workspace.root)

    async def leg() -> str:
        return await run_role_leg(
            handle.workspace.db,
            provider,
            registry,
            policy,
            run_id,
            stage_key="S0",
            role_id="reader",
            node_key="S0:429-wave",
            instructions="写 交接/读题体检.md。",
            expected_artifacts=[
                ExpectedArtifact(rel_path="交接/读题体检.md", kind="text")
            ],
        )

    try:
        outcome = await run_status_wave(
            handle.workspace.db,
            run_id,
            [WaveJob("reader", leg)],
            wave_key="real-429",
        )

        assert outcome.results == {"reader": "SUCCEEDED"}
        assert outcome.attempts["reader"] == 2
        assert outcome.end_concurrency == 3
        assert (policy.root / "交接" / "读题体检.md").read_text(
            encoding="utf-8"
        ) == "429 retry recovered"

        tasks = repositories.list_tasks(handle.workspace.db, run_id)
        task = next(x for x in tasks if x.node_key == "S0:429-wave")
        assert task.attempt == 2
        assert task.status.value == "SUCCEEDED"

        rate_events = events.query_events(
            handle.workspace.db,
            run_id=run_id,
            type="task.rate_limited",
        )
        assert len(rate_events) == 1
    finally:
        handle.workspace.db.close()



@pytest.mark.asyncio
async def test_direct_role_leg_429_honors_retry_after_before_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle, run_id = _run_ctx(tmp_path)
    provider = MockProvider(MockScript([
        MockTurn(tool_calls=[(
            "write-backoff",
            "fs.write",
            {"path": "交接/读题体检.md", "content": "retry-after recovered"},
        )]),
        MockTurn(text="完成"),
    ]))
    provider.queue_error(RateLimitError("429", retry_after_s=5.5))

    observed: list[float] = []

    async def fake_wait(delay_s: float, cancel=None) -> None:
        observed.append(delay_s)
        if cancel is not None:
            cancel.check()

    import mmagent.orchestration.wave as wave_module

    monkeypatch.setattr(wave_module, "_wait_retry_backoff", fake_wait)

    registry = ToolRegistry()
    registry.register(FsReadTool())
    registry.register(FsWriteTool())
    policy = PathPolicy(handle.workspace.root)

    try:
        status = await run_role_leg(
            handle.workspace.db,
            provider,
            registry,
            policy,
            run_id,
            stage_key="S0",
            role_id="reader",
            node_key="S0:retry-after",
            instructions="写 交接/读题体检.md。",
            expected_artifacts=[
                ExpectedArtifact(rel_path="交接/读题体检.md", kind="text")
            ],
        )

        assert status == "SUCCEEDED"
        assert observed == [5.5]

        backoff_events = events.query_events(
            handle.workspace.db,
            run_id=run_id,
            type="wave.retry_backoff",
        )
        assert len(backoff_events) == 1
        assert backoff_events[0].payload["retry_after_s"] == 5.5
        assert backoff_events[0].payload["jobs"] == ["S0:retry-after"]
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_direct_role_leg_429_uses_single_job_adaptive_wave(
    tmp_path: Path,
) -> None:
    handle, run_id = _run_ctx(tmp_path)
    provider = MockProvider(MockScript([
        MockTurn(tool_calls=[(
            "write-direct",
            "fs.write",
            {"path": "交接/读题体检.md", "content": "direct retry recovered"},
        )]),
        MockTurn(text="完成"),
    ]))
    provider.queue_error(RateLimitError("429", retry_after_s=0))

    registry = ToolRegistry()
    registry.register(FsReadTool())
    registry.register(FsWriteTool())
    policy = PathPolicy(handle.workspace.root)

    try:
        status = await run_role_leg(
            handle.workspace.db,
            provider,
            registry,
            policy,
            run_id,
            stage_key="S0",
            role_id="reader",
            node_key="S0:direct-429",
            instructions="写 交接/读题体检.md。",
            expected_artifacts=[
                ExpectedArtifact(rel_path="交接/读题体检.md", kind="text")
            ],
        )

        assert status == "SUCCEEDED"
        assert current_wave_concurrency(handle.workspace.db, run_id) == 3
        assert (policy.root / "交接" / "读题体检.md").read_text(
            encoding="utf-8"
        ) == "direct retry recovered"

        tasks = repositories.list_tasks(handle.workspace.db, run_id)
        task = next(x for x in tasks if x.node_key == "S0:direct-429")
        assert task.attempt == 2
        assert task.status.value == "SUCCEEDED"

        reductions = events.query_events(
            handle.workspace.db,
            run_id=run_id,
            type="wave.concurrency_reduced",
        )
        assert len(reductions) == 1
        assert reductions[0].payload["from"] == 4
        assert reductions[0].payload["to"] == 3
    finally:
        handle.workspace.db.close()



@pytest.mark.asyncio
async def test_wave_timeout_retries_only_after_old_job_is_cancelled(
    tmp_path: Path,
) -> None:
    handle, run_id = _run_ctx(tmp_path)
    active = 0
    peak = 0
    calls = 0
    cleanups = 0

    async def slow() -> str:
        nonlocal active, peak, calls, cleanups
        calls += 1
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.2)
            return "SUCCEEDED"
        finally:
            active -= 1
            cleanups += 1

    try:
        outcome = await run_status_wave(
            handle.workspace.db,
            run_id,
            [WaveJob("slow", slow)],
            wave_key="timeout-retry",
            timeout_s=0.03,
        )

        assert outcome.results == {"slow": "FAILED"}
        assert outcome.attempts == {"slow": 2}
        assert outcome.timed_out_jobs == ("slow",)
        assert calls == 2
        assert cleanups == 2
        assert peak == 1, "retry must not overlap the cancelled old copy"

        timeout_events = events.query_events(
            handle.workspace.db,
            run_id=run_id,
            type="wave.job_timed_out",
        )
        assert len(timeout_events) == 2
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_wave_timeout_starts_when_job_acquires_concurrency_slot(
    tmp_path: Path,
) -> None:
    handle, run_id = _run_ctx(tmp_path)

    async def short() -> str:
        await asyncio.sleep(0.035)
        return "SUCCEEDED"

    try:
        outcome = await run_status_wave(
            handle.workspace.db,
            run_id,
            [WaveJob("a", short), WaveJob("b", short)],
            wave_key="queued-deadline",
            default_concurrency=1,
            min_concurrency=1,
            timeout_s=0.06,
        )

        assert outcome.results == {"a": "SUCCEEDED", "b": "SUCCEEDED"}
        assert outcome.timed_out_jobs == ()
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_wave_programming_error_cancels_and_awaits_peers(
    tmp_path: Path,
) -> None:
    handle, run_id = _run_ctx(tmp_path)
    peer_started = asyncio.Event()
    peer_closed = asyncio.Event()

    async def boom() -> str:
        await peer_started.wait()
        raise RuntimeError("injected wave bug")

    async def peer() -> str:
        peer_started.set()
        try:
            await asyncio.sleep(30)
            return "SUCCEEDED"
        finally:
            peer_closed.set()

    try:
        with pytest.raises(RuntimeError, match="injected wave bug"):
            await run_status_wave(
                handle.workspace.db,
                run_id,
                [WaveJob("boom", boom), WaveJob("peer", peer)],
                wave_key="peer-cleanup",
                timeout_s=2,
            )

        assert peer_closed.is_set()
    finally:
        handle.workspace.db.close()
