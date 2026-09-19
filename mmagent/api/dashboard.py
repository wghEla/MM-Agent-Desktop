"""Run Dashboard API（第一版）：项目/运行/任务/事件/门检 的只读查询 + 运行控制。"""
from __future__ import annotations

from typing import Any

from mmagent.mm.config.profiles import get_profile
from mmagent.state import events, repositories
from mmagent.state.db import Database
from mmagent.workspace.root import ProjectWorkspace


def dashboard(ws: ProjectWorkspace, run_id: str) -> dict[str, Any]:
    """一屏 Dashboard：run 状态 + 阶段/任务 + 事件流 + 门检结果。"""
    db = ws.db
    run_row = db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    if run_row is None:
        raise LookupError(f"run 不存在: {run_id}")

    tasks = repositories.list_tasks(db, run_id)
    task_list = [
        {
            "id": t.id, "node": t.node_key, "role": t.role_id,
            "status": t.status.value, "attempt": t.attempt,
            "error": t.error,
        }
        for t in tasks
    ]

    # 按阶段分组
    stages: dict[str, list[dict]] = {}
    for t in task_list:
        stage = t["node"].split(":")[0] if ":" in t["node"] else t["node"]
        stages.setdefault(stage, []).append(t)

    # 最近事件
    evs = events.query_events(db, run_id=run_id, limit=50)
    event_list = [
        {"ts": e.ts, "type": e.type, "task": e.task_id,
         "payload": {k: v for k, v in e.payload.items() if k != "artifacts"}}
        for e in evs
    ]

    # 门检结果（从事件提取）
    gate_events = [
        e for e in events.query_events(db, run_id=run_id, type="gate.result", limit=20)
    ]
    gates = [{"gate": e.payload.get("gate"), "pass": e.payload.get("pass"),
              "issues": e.payload.get("issues", [])}
             for e in gate_events]

    profile = run_row["profile"]
    profile_cfg = get_profile(profile) if profile in ("深度", "标准", "快速") else None

    return {
        "run_id": run_id,
        "status": run_row["status"],
        "profile": profile,
        "profile_config": {
            "tier": profile_cfg.tier,
            "每问路线数": profile_cfg.每问路线数,
            "审稿轮数": profile_cfg.审稿轮数,
            "max_hours": profile_cfg.max_hours,
        } if profile_cfg else None,
        "stages": stages,
        "tasks": task_list,
        "events": event_list,
        "gates": gates,
    }


def record_gate_result(db: Database, run_id: str, gate_name: str,
                       passed: bool, issues: list[str]) -> None:
    """记录门检结果事件（Dashboard 可查）。"""
    events.append_event(db, "gate.result", {
        "gate": gate_name, "pass": passed, "issues": issues,
    }, run_id=run_id)


def list_projects(db: Database) -> list[dict[str, Any]]:
    rows = db.query("SELECT id, name, root_path, profile, created_at FROM projects ORDER BY created_at DESC")
    return [dict(r) for r in rows]


def list_runs(db: Database, project_id: str) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT id, status, profile, started_at, ended_at FROM runs"
        " WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    )
    return [dict(r) for r in rows]
