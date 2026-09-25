"""Bounded adaptive wave scheduling for independent paper-foundry legs.

The pinned upstream driver launches independent legs in bounded waves, retries
failed legs once, and lowers the global run concurrency after any 429 response.
This module reproduces that behavior on top of durable task/event state.

Important semantics:
- default concurrency 4, floor 2;
- adaptive limit is persisted as append-only events, so resume preserves it;
- FAILED and rate-limited QUEUED legs are retried once;
- CANCELLED legs are never retried;
- programming/runtime exceptions are not swallowed as ordinary leg failures.
"""
from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from mmagent.mm.config.thresholds import DEFAULT_THRESHOLDS
from mmagent.state import events
from mmagent.state.db import Database

T = TypeVar("T")

_WAVE_ACTIVE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "mmagent_wave_active", default=False
)


def wave_active() -> bool:
    """Whether the current async context is already executing inside a wave."""
    return _WAVE_ACTIVE.get()


@dataclass(frozen=True)
class WaveJob(Generic[T]):
    name: str
    run: Callable[[], Awaitable[T]]


@dataclass(frozen=True)
class WaveOutcome(Generic[T]):
    results: dict[str, T]
    attempts: dict[str, int]
    start_concurrency: int
    end_concurrency: int
    rate_limited_jobs: tuple[str, ...]


def current_wave_concurrency(
    db: Database,
    run_id: str,
    *,
    default: int | None = None,
    floor: int | None = None,
) -> int:
    """Return the persisted adaptive concurrency limit for this run."""
    default_value = (
        DEFAULT_THRESHOLDS.default_concurrency if default is None else int(default)
    )
    floor_value = (
        DEFAULT_THRESHOLDS.min_concurrency if floor is None else int(floor)
    )
    if floor_value < 1 or default_value < floor_value:
        raise ValueError("invalid wave concurrency bounds")

    history = events.query_events(
        db,
        run_id=run_id,
        type="wave.concurrency_reduced",
        limit=1000,
    )
    limit = default_value
    for event in history:
        value = event.payload.get("to")
        if isinstance(value, int):
            limit = max(floor_value, min(default_value, value))
    return limit


async def run_status_wave(
    db: Database,
    run_id: str,
    jobs: list[WaveJob[str]],
    *,
    retry_once: bool = True,
    default_concurrency: int | None = None,
    min_concurrency: int | None = None,
    cancel=None,
    wave_key: str = "",
    serial: bool = False,
) -> WaveOutcome[str]:
    """Run independent status-returning jobs with upstream-compatible wave rules.

    Job return values are expected to be task status strings. QUEUED means
    AgentLoop released the task after a provider 429; FAILED is an ordinary
    failed leg. Both receive at most one retry. The retry pass is a new wave,
    so an observed 429 reduces its concurrency before retrying.
    """
    if serial:
        default_concurrency = 1
        min_concurrency = 1

    if not jobs:
        limit = current_wave_concurrency(
            db,
            run_id,
            default=default_concurrency,
            floor=min_concurrency,
        )
        return WaveOutcome({}, {}, limit, limit, ())

    default_value = (
        DEFAULT_THRESHOLDS.default_concurrency
        if default_concurrency is None
        else int(default_concurrency)
    )
    floor_value = (
        DEFAULT_THRESHOLDS.min_concurrency
        if min_concurrency is None
        else int(min_concurrency)
    )
    start_limit = current_wave_concurrency(
        db, run_id, default=default_value, floor=floor_value
    )
    attempts = {job.name: 0 for job in jobs}
    results: dict[str, str] = {}
    rate_limited_seen: list[str] = []
    pending = list(jobs)
    pass_no = 0

    while pending:
        pass_no += 1
        limit = current_wave_concurrency(
            db, run_id, default=default_value, floor=floor_value
        )
        semaphore = asyncio.Semaphore(limit)

        events.append_event(
            db,
            "wave.started",
            {
                "wave": wave_key,
                "pass": pass_no,
                "jobs": [job.name for job in pending],
                "concurrency": limit,
            },
            run_id=run_id,
        )

        async def invoke(
            job: WaveJob[str], *, gate=semaphore
        ) -> tuple[str, str]:
            async with gate:
                if cancel is not None:
                    cancel.check()
                attempts[job.name] += 1
                token = _WAVE_ACTIVE.set(True)
                try:
                    status = await job.run()
                finally:
                    _WAVE_ACTIVE.reset(token)
                return job.name, str(status)

        pairs = await asyncio.gather(*(invoke(job) for job in pending))
        pass_results = dict(pairs)

        limited = [
            name for name, status in pass_results.items() if status == "QUEUED"
        ]
        if limited:
            for name in limited:
                if name not in rate_limited_seen:
                    rate_limited_seen.append(name)
            before = limit
            after = max(floor_value, before - 1)
            if after < before:
                events.append_event(
                    db,
                    "wave.concurrency_reduced",
                    {
                        "wave": wave_key,
                        "pass": pass_no,
                        "from": before,
                        "to": after,
                        "reason": "provider_429",
                        "jobs": limited,
                    },
                    run_id=run_id,
                )
            else:
                events.append_event(
                    db,
                    "wave.rate_limited_at_floor",
                    {
                        "wave": wave_key,
                        "pass": pass_no,
                        "concurrency": before,
                        "jobs": limited,
                    },
                    run_id=run_id,
                )

        retry_names: set[str] = set()
        if retry_once and pass_no == 1:
            retry_names = {
                name
                for name, status in pass_results.items()
                if status in ("FAILED", "QUEUED")
            }

        for name, status in pass_results.items():
            if name not in retry_names:
                results[name] = status

        events.append_event(
            db,
            "wave.completed",
            {
                "wave": wave_key,
                "pass": pass_no,
                "concurrency": limit,
                "results": pass_results,
                "retry": sorted(retry_names),
            },
            run_id=run_id,
        )

        if not retry_names:
            break
        pending = [job for job in jobs if job.name in retry_names]

    end_limit = current_wave_concurrency(
        db, run_id, default=default_value, floor=floor_value
    )
    return WaveOutcome(
        results=results,
        attempts=attempts,
        start_concurrency=start_limit,
        end_concurrency=end_limit,
        rate_limited_jobs=tuple(rate_limited_seen),
    )
