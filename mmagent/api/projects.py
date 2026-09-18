"""项目 API：创建/打开工作区、建 run、建 task 的稳定入口（Desktop 与测试共用）。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mmagent.state import repositories
from mmagent.state.models import TaskStatus
from mmagent.workspace.root import ProjectWorkspace


@dataclass(frozen=True)
class ProjectHandle:
    workspace: ProjectWorkspace
    project_id: str


def create_project(root: Path, *, name: str, profile: str = "standard") -> ProjectHandle:
    ws = ProjectWorkspace.create(root, name=name, profile=profile)
    row = ws.db.query_one("SELECT id FROM projects ORDER BY created_at LIMIT 1")
    return ProjectHandle(workspace=ws, project_id=row["id"])


def open_project(root: Path) -> ProjectHandle:
    ws = ProjectWorkspace.open(root)
    row = ws.db.query_one("SELECT id FROM projects ORDER BY created_at LIMIT 1")
    if row is None:
        raise LookupError(f"工作区没有 project 记录: {root}")
    return ProjectHandle(workspace=ws, project_id=row["id"])


def start_run(handle: ProjectHandle, *, profile: str = "standard", config: dict | None = None) -> str:
    """创建 run 并取单运行锁（一父目录一驱动）。"""
    run_id = repositories.create_run(handle.workspace.db, project_id=handle.project_id, profile=profile, config=config)
    handle.workspace.acquire_run_lock(run_id)
    return run_id


def finish_run(handle: ProjectHandle, run_id: str, *, status: str) -> None:
    from mmagent.state.models import RunStatus

    repositories.set_run_status(handle.workspace.db, run_id, RunStatus(status))
    handle.workspace.release_run_lock()


def create_pipeline_task(
    handle: ProjectHandle,
    run_id: str,
    *,
    stage_key: str,
    node_key: str,
    role_id: str | None = None,
    kind: str = "agent",
    expected_artifacts: list[dict] | None = None,
) -> str:
    rec = repositories.create_task(
        handle.workspace.db,
        run_id=run_id,
        stage_key=stage_key,
        node_key=node_key,
        role_id=role_id,
        kind=kind,
        expected_artifacts=expected_artifacts,
    )
    return rec.id


def reset_interrupted_tasks(handle: ProjectHandle, run_id: str) -> int:
    """崩溃恢复：RUNNING/WAITING_TOOL/CANCEL_REQUESTED 残留任务 → FAILED（绝不假定成功）。

    复现总方案 §35：resume 时 RUNNING 残留按 checkpoint 规则标 FAILED/RETRYABLE。
    返回处理数量。
    """
    n = 0
    from mmagent.state import repositories as repo

    for t in repositories.list_tasks(handle.workspace.db, run_id):
        if t.status in (TaskStatus.RUNNING, TaskStatus.WAITING_TOOL, TaskStatus.CANCEL_REQUESTED):
            repo.recover_interrupted_task(
                handle.workspace.db,
                t.id,
                reason=(
                    "[state_transition] 运行中断恢复：残留中断态任务标记 FAILED（不假定成功）；"
                    "中断时可能正处于工具执行中——副作用未知，不得假定重试幂等（外审 P1-5）"
                ),
            )
            n += 1
    return n
