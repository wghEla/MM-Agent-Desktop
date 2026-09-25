"""Authoritative run-budget guard for paper-foundry execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from mmagent.agent.errors import BudgetExhausted
from mmagent.mm.config.profiles import get_profile
from mmagent.state import events
from mmagent.state.db import Database

_RUNNING = "RUNNING"


@dataclass(frozen=True)
class BudgetSnapshot:
    profile: str
    legs: int
    max_legs: int
    active_seconds: float
    max_seconds: float


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def active_runtime_seconds(
    db: Database,
    run_id: str,
    *,
    now: datetime | None = None,
) -> float:
    """Sum durable RUNNING intervals, excluding time spent PAUSED."""
    current = now or datetime.now(UTC)
    running_since: datetime | None = None
    total = 0.0
    for event in events.query_events(db, run_id=run_id, type="run.status", limit=10000):
        source = str(event.payload.get("from", ""))
        target = str(event.payload.get("to", ""))
        ts = _parse_ts(event.ts)

        if target == _RUNNING and running_since is None:
            running_since = ts
        if source == _RUNNING and target != _RUNNING and running_since is not None:
            total += max(0.0, (ts - running_since).total_seconds())
            running_since = None

    if running_since is not None:
        total += max(0.0, (current - running_since).total_seconds())
    return total


def check_run_budget(
    db: Database,
    run_id: str,
    *,
    now: datetime | None = None,
) -> BudgetSnapshot:
    """Fail closed once either the leg or active-runtime budget is exceeded."""
    row = db.query_one("SELECT profile FROM runs WHERE id = ?", (run_id,))
    if row is None:
        raise LookupError(f"run 不存在: {run_id}")
    profile = get_profile(row["profile"])
    legs_row = db.query_one(
        "SELECT COUNT(*) AS n FROM tasks WHERE run_id = ?",
        (run_id,),
    )
    legs = int(legs_row["n"] if legs_row is not None else 0)
    active = active_runtime_seconds(db, run_id, now=now)
    maximum_seconds = profile.max_hours * 3600.0

    snapshot = BudgetSnapshot(
        profile=profile.tier,
        legs=legs,
        max_legs=profile.max_legs,
        active_seconds=active,
        max_seconds=maximum_seconds,
    )
    if legs > profile.max_legs:
        raise BudgetExhausted(
            f"run leg budget exceeded: {legs}>{profile.max_legs}",
            detail={
                "kind": "max_legs",
                "legs": legs,
                "max_legs": profile.max_legs,
                "profile": profile.tier,
            },
        )
    if active > maximum_seconds:
        raise BudgetExhausted(
            f"run active-time budget exceeded: {active:.1f}s>{maximum_seconds:.1f}s",
            detail={
                "kind": "max_hours",
                "active_seconds": active,
                "max_seconds": maximum_seconds,
                "profile": profile.tier,
            },
        )
    return snapshot
