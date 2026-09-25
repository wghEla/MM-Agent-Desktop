"""Node-level resume primitives for deterministic pipeline legs."""
from __future__ import annotations

from dataclasses import dataclass

from mmagent.agent.errors import TaskNotRunnable
from mmagent.state import events, repositories
from mmagent.state.db import Database
from mmagent.state.models import TaskRecord, TaskStatus
from mmagent.workspace.artifacts import ExpectedArtifact, verify_expected_artifacts
from mmagent.workspace.path_policy import PathPolicy


@dataclass(frozen=True)
class PreparedNode:
    task: TaskRecord
    reused: bool


def prepare_node_task(
    db: Database,
    policy: PathPolicy,
    *,
    run_id: str,
    stage_key: str,
    node_key: str,
    role_id: str | None,
    expected_artifacts: list[ExpectedArtifact],
    kind: str = "agent",
    max_attempts: int = 2,
) -> PreparedNode:
    """Return a runnable existing task or create one; reuse valid success.

    This closes the gap between stage-level checkpoints and mid-stage crash
    recovery.  Deterministic node keys are durable identities within a run.

    - missing node -> create PENDING task;
    - SUCCEEDED -> re-verify its current carrier artifacts and reuse;
    - FAILED/CANCELLED/BLOCKED/DEFERRED -> explicit retry to READY;
    - PENDING/READY/QUEUED -> reuse as runnable;
    - active states -> reject; crash recovery must close them first.
    """
    row = db.query_one(
        "SELECT id FROM tasks WHERE run_id = ? AND node_key = ?",
        (run_id, node_key),
    )
    if row is None:
        task = repositories.create_task(
            db,
            run_id=run_id,
            stage_key=stage_key,
            node_key=node_key,
            role_id=role_id,
            kind=kind,
            expected_artifacts=[
                {
                    "rel_path": item.rel_path,
                    "kind": item.kind,
                    "required": item.required,
                    "schema_id": (
                        item.schema_model.__name__ if item.schema_model is not None else None
                    ),
                }
                for item in expected_artifacts
            ],
            max_attempts=max_attempts,
        )
        return PreparedNode(task=task, reused=False)

    task = repositories.get_task(db, row["id"])
    if task.stage_key != stage_key or task.role_id != role_id or task.kind != kind:
        raise TaskNotRunnable(
            f"节点身份冲突 {node_key}: "
            f"existing=({task.stage_key},{task.role_id},{task.kind}) "
            f"requested=({stage_key},{role_id},{kind})"
        )

    if task.status is TaskStatus.SUCCEEDED:
        verify_expected_artifacts(policy, expected_artifacts)
        events.append_event(
            db,
            "pipeline.node_reused",
            {"node": node_key, "stage": stage_key, "task_id": task.id},
            run_id=run_id,
            task_id=task.id,
        )
        return PreparedNode(task=task, reused=True)

    if task.status in (
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.BLOCKED,
        TaskStatus.DEFERRED,
    ):
        task = repositories.retry_task(db, task.id)
        events.append_event(
            db,
            "pipeline.node_retried",
            {"node": node_key, "stage": stage_key, "task_id": task.id},
            run_id=run_id,
            task_id=task.id,
        )
        return PreparedNode(task=task, reused=False)

    if task.status in (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.QUEUED):
        return PreparedNode(task=task, reused=False)

    raise TaskNotRunnable(
        f"节点 {node_key} 仍处于活动态 {task.status.value}；"
        "必须先执行 interrupted-task recovery"
    )
