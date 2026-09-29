from __future__ import annotations

from pathlib import Path

import pytest

from mmagent.agent.errors import ArtifactMissing, TaskNotRunnable
from mmagent.api.projects import create_project
from mmagent.orchestration.resume import prepare_node_task
from mmagent.state import repositories
from mmagent.state.models import TaskStatus
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy


def _ctx(tmp_path: Path):
    handle = create_project(tmp_path / "proj", name="resume", profile="标准")
    run_id = repositories.create_run(
        handle.workspace.db, project_id=handle.project_id, profile="标准"
    )
    return handle, run_id, PathPolicy(handle.workspace.root)


def test_prepare_creates_then_reuses_valid_success(tmp_path: Path) -> None:
    handle, run_id, policy = _ctx(tmp_path)
    try:
        expected = [ExpectedArtifact(rel_path="交接/out.json")]
        first = prepare_node_task(
            handle.workspace.db, policy,
            run_id=run_id, stage_key="Sx", node_key="Sx:node",
            role_id="reader", expected_artifacts=expected,
        )
        assert not first.reused
        (policy.root / "交接" / "out.json").write_text("{}", encoding="utf-8")
        handle.workspace.db.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (TaskStatus.SUCCEEDED.value, first.task.id),
        )

        second = prepare_node_task(
            handle.workspace.db, policy,
            run_id=run_id, stage_key="Sx", node_key="Sx:node",
            role_id="reader", expected_artifacts=expected,
        )
        assert second.reused
        assert second.task.id == first.task.id
    finally:
        handle.workspace.db.close()


def test_prepare_retries_failed_node_in_place(tmp_path: Path) -> None:
    handle, run_id, policy = _ctx(tmp_path)
    try:
        prepared = prepare_node_task(
            handle.workspace.db, policy,
            run_id=run_id, stage_key="Sx", node_key="Sx:node",
            role_id="reader", expected_artifacts=[],
        )
        handle.workspace.db.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (TaskStatus.FAILED.value, prepared.task.id),
        )
        retried = prepare_node_task(
            handle.workspace.db, policy,
            run_id=run_id, stage_key="Sx", node_key="Sx:node",
            role_id="reader", expected_artifacts=[],
        )
        assert retried.task.id == prepared.task.id
        assert retried.task.status is TaskStatus.READY
        assert not retried.reused
    finally:
        handle.workspace.db.close()


def test_prepare_fails_closed_when_success_artifact_is_missing(tmp_path: Path) -> None:
    handle, run_id, policy = _ctx(tmp_path)
    try:
        expected = [ExpectedArtifact(rel_path="交接/missing.json")]
        prepared = prepare_node_task(
            handle.workspace.db, policy,
            run_id=run_id, stage_key="Sx", node_key="Sx:node",
            role_id="reader", expected_artifacts=expected,
        )
        handle.workspace.db.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (TaskStatus.SUCCEEDED.value, prepared.task.id),
        )
        with pytest.raises(ArtifactMissing):
            prepare_node_task(
                handle.workspace.db, policy,
                run_id=run_id, stage_key="Sx", node_key="Sx:node",
                role_id="reader", expected_artifacts=expected,
            )
    finally:
        handle.workspace.db.close()


def test_prepare_rejects_live_node_until_recovery(tmp_path: Path) -> None:
    handle, run_id, policy = _ctx(tmp_path)
    try:
        prepared = prepare_node_task(
            handle.workspace.db, policy,
            run_id=run_id, stage_key="Sx", node_key="Sx:node",
            role_id="reader", expected_artifacts=[],
        )
        repositories.transition_task(
            handle.workspace.db, prepared.task.id, TaskStatus.READY
        )
        repositories.transition_task(
            handle.workspace.db, prepared.task.id, TaskStatus.QUEUED
        )
        token = repositories.new_owner_token()
        assert repositories.acquire_task_lease(
            handle.workspace.db, prepared.task.id, token
        )
        with pytest.raises(TaskNotRunnable):
            prepare_node_task(
                handle.workspace.db, policy,
                run_id=run_id, stage_key="Sx", node_key="Sx:node",
                role_id="reader", expected_artifacts=[],
            )
    finally:
        handle.workspace.db.close()
