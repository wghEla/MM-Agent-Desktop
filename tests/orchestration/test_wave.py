from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mmagent.api.projects import create_project
from mmagent.orchestration.wave import WaveJob, current_wave_concurrency, run_status_wave
from mmagent.state import events, repositories


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
