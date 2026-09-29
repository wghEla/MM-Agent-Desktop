from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from mmagent.agent.errors import BudgetExhausted
from mmagent.api.projects import create_project
from mmagent.orchestration.budget import active_runtime_seconds, check_run_budget
from mmagent.state import repositories
from mmagent.state.models import RunStatus


def _seed_status_event(db, run_id: str, ts: datetime, source: str, target: str) -> None:
    db.execute(
        "INSERT INTO events(ts, run_id, type, payload_json) VALUES (?,?,?,?)",
        (
            ts.isoformat().replace("+00:00", "Z"),
            run_id,
            "run.status",
            json.dumps({"from": source, "to": target}),
        ),
    )


def test_run_started_at_is_set_on_first_running_transition(tmp_path) -> None:
    handle = create_project(tmp_path / "proj", name="budget-start", profile="快速")
    try:
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        repositories.set_run_status(handle.workspace.db, run_id, RunStatus.RUNNING)
        first = handle.workspace.db.query_one(
            "SELECT started_at FROM runs WHERE id = ?", (run_id,)
        )["started_at"]
        assert first

        repositories.set_run_status(handle.workspace.db, run_id, RunStatus.PAUSED)
        repositories.set_run_status(handle.workspace.db, run_id, RunStatus.RUNNING)
        second = handle.workspace.db.query_one(
            "SELECT started_at FROM runs WHERE id = ?", (run_id,)
        )["started_at"]
        assert second == first
    finally:
        handle.workspace.db.close()


def test_active_runtime_excludes_paused_intervals(tmp_path) -> None:
    handle = create_project(tmp_path / "proj", name="budget-time", profile="快速")
    try:
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        base = datetime(2026, 1, 1, tzinfo=UTC)
        _seed_status_event(
            handle.workspace.db, run_id, base, "CREATED", "RUNNING"
        )
        _seed_status_event(
            handle.workspace.db,
            run_id,
            base + timedelta(minutes=10),
            "RUNNING",
            "PAUSED",
        )
        _seed_status_event(
            handle.workspace.db,
            run_id,
            base + timedelta(hours=1),
            "PAUSED",
            "RUNNING",
        )

        elapsed = active_runtime_seconds(
            handle.workspace.db,
            run_id,
            now=base + timedelta(hours=1, minutes=10),
        )
        assert elapsed == pytest.approx(20 * 60)
    finally:
        handle.workspace.db.close()


def test_leg_budget_allows_limit_and_rejects_next_leg(tmp_path) -> None:
    handle = create_project(tmp_path / "proj", name="budget-legs", profile="快速")
    try:
        db = handle.workspace.db
        run_id = repositories.create_run(
            db, project_id=handle.project_id, profile="快速"
        )
        now = repositories.now_iso()
        with db.transaction() as conn:
            for index in range(600):
                conn.execute(
                    "INSERT INTO tasks("
                    "id, run_id, stage_key, node_key, kind, status, max_attempts,"
                    "expected_artifacts_json, created_at, updated_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        f"task_budget_{index}",
                        run_id,
                        "T",
                        f"T:{index}",
                        "agent",
                        "PENDING",
                        2,
                        "[]",
                        now,
                        now,
                    ),
                )

        snapshot = check_run_budget(db, run_id)
        assert snapshot.legs == snapshot.max_legs == 600

        repositories.create_task(
            db, run_id=run_id, stage_key="T", node_key="T:overflow"
        )
        with pytest.raises(BudgetExhausted) as exc:
            check_run_budget(db, run_id)
        assert exc.value.detail["kind"] == "max_legs"
    finally:
        handle.workspace.db.close()


def test_active_time_budget_is_enforced(tmp_path) -> None:
    handle = create_project(tmp_path / "proj", name="budget-hours", profile="快速")
    try:
        db = handle.workspace.db
        run_id = repositories.create_run(
            db, project_id=handle.project_id, profile="快速"
        )
        base = datetime(2026, 1, 1, tzinfo=UTC)
        _seed_status_event(db, run_id, base, "CREATED", "RUNNING")

        with pytest.raises(BudgetExhausted) as exc:
            check_run_budget(
                db,
                run_id,
                now=base + timedelta(hours=20, seconds=1),
            )
        assert exc.value.detail["kind"] == "max_hours"
    finally:
        handle.workspace.db.close()
