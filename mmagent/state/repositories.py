"""仓储层：Project / Run / Task / Artifact / Invocation 的状态事务。

核心不变量（总方案 §19/§34；v0.1.0 外审 P0/P1 修复后强化）：
- transition_task() **永远不能**把任务置为 SUCCEEDED——成功只能经
  commit_task_success()（与 artifact 落库/事件写入同事务）；
- RUNNING 状态的任务由 owner_token（执行租约）持有：非持有者不得迁移状态，
  双执行者不可能同时持有一个任务（CAS）；
- 每个状态迁移与对应事件在**同一事务**里提交（transactional outbox）；
- run() 入口状态严格：终态/暂停态不得被隐式复活，重试必须走 retry_task()。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mmagent.agent.errors import TaskLeaseHeld, TaskNotRunnable  # noqa: F401 (re-export)
from mmagent.state import events
from mmagent.state.db import Database
from mmagent.state.models import (
    ArtifactRecord,
    InvocationStatus,
    RunStatus,
    StateTransitionError,
    TaskRecord,
    TaskStatus,
    can_transition,
    can_transition_run,
)


def now_iso() -> str:
    import datetime

    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def new_owner_token() -> str:
    return uuid.uuid4().hex


def _require_token(owner_token: str | None) -> str:
    """租约 token 必须是非空字符串（空串会伪装成无租约，round3 P1-c）。"""
    if not owner_token:
        raise TaskLeaseHeld("owner token 为空：租约 token 必须是非空字符串")
    return owner_token


# ---------------------------------------------------------------- project / run
def create_project(db: Database, *, name: str, root_path: Path, profile: str = "standard") -> str:
    pid = new_id("proj")
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO projects(id, name, root_path, profile, created_at) VALUES (?,?,?,?,?)",
            (pid, name, str(root_path), profile, now_iso()),
        )
    return pid


def create_run(db: Database, *, project_id: str, profile: str, config: dict | None = None) -> str:
    rid = new_id("run")
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO runs(id, project_id, status, profile, config_json, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (rid, project_id, RunStatus.CREATED.value, profile, json.dumps(config or {}, ensure_ascii=False), now_iso()),
        )
        events.append_event_conn(conn, "run.created", {"profile": profile}, run_id=rid)
    return rid


def set_run_status(db: Database, run_id: str, status: RunStatus) -> None:
    """Run 状态迁移（带迁移表校验 + 同事务事件，外审 P2-3）。"""
    with db.transaction() as conn:
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise LookupError(f"run 不存在: {run_id}")
        current = RunStatus(row["status"])
        if not can_transition_run(current, status):
            raise StateTransitionError(f"非法 run 状态迁移: {current.value} -> {status.value}")
        changed_at = now_iso()
        conn.execute(
            "UPDATE runs SET status = ?,"
            " started_at = CASE WHEN ? = 'RUNNING' AND started_at IS NULL THEN ? ELSE started_at END,"
            " ended_at = CASE WHEN ? IN ('SUCCEEDED','FAILED','CANCELLED') THEN ? ELSE ended_at END"
            " WHERE id = ?",
            (
                status.value,
                status.value,
                changed_at,
                status.value,
                changed_at,
                run_id,
            ),
        )
        events.append_event_conn(conn, "run.status", {"from": current.value, "to": status.value}, run_id=run_id)


# ---------------------------------------------------------------- task
def create_task(
    db: Database,
    *,
    run_id: str,
    stage_key: str,
    node_key: str,
    role_id: str | None = None,
    kind: str = "agent",
    expected_artifacts: list[dict] | None = None,
    max_attempts: int = 2,
) -> TaskRecord:
    tid = new_id("task")
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO tasks(id, run_id, stage_key, node_key, role_id, kind, status,"
            " max_attempts, expected_artifacts_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                tid,
                run_id,
                stage_key,
                node_key,
                role_id,
                kind,
                TaskStatus.PENDING.value,
                max_attempts,
                json.dumps(expected_artifacts or [], ensure_ascii=False),
                now_iso(),
                now_iso(),
            ),
        )
        events.append_event_conn(conn, "task.created", {"node": node_key, "role": role_id}, run_id=run_id, task_id=tid)
    return get_task(db, tid)


def get_task(db: Database, task_id: str) -> TaskRecord:
    r = db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if r is None:
        raise LookupError(f"task 不存在: {task_id}")
    return TaskRecord(
        id=r["id"],
        run_id=r["run_id"],
        stage_key=r["stage_key"],
        node_key=r["node_key"],
        role_id=r["role_id"],
        kind=r["kind"],
        status=TaskStatus(r["status"]),
        attempt=r["attempt"],
        max_attempts=r["max_attempts"],
        expected_artifacts=json.loads(r["expected_artifacts_json"]),
        result=json.loads(r["result_json"]) if r["result_json"] else None,
        error=r["error"],
    )


def list_tasks(db: Database, run_id: str) -> list[TaskRecord]:
    rows = db.query("SELECT id FROM tasks WHERE run_id = ? ORDER BY created_at", (run_id,))
    return [get_task(db, r["id"]) for r in rows]


def transition_task(
    db: Database,
    task_id: str,
    target: TaskStatus,
    *,
    error: str | None = None,
    owner_token: str | None = None,
) -> TaskRecord:
    """单步状态迁移（迁移表 + 租约校验 + 同事务事件）。

    - SUCCEEDED 只能经 commit_task_success() 进入（外审 P0-1）。
    - 若任务被租约持有（owner_token 非空），调用必须出示相同 token。
    """
    if target is TaskStatus.SUCCEEDED:
        raise StateTransitionError(
            "SUCCEEDED 必须经 commit_task_success() 提交（不允许 transition_task 直写）"
        )
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT status, owner_token, run_id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"task 不存在: {task_id}")
        current = TaskStatus(row["status"])
        if row["owner_token"] is not None and owner_token != row["owner_token"]:
            raise TaskLeaseHeld(f"任务由其他执行者持有: {task_id}")
        if not can_transition(current, target):
            raise StateTransitionError(f"非法状态迁移: {current.value} -> {target.value}")
        # QUEUED→RUNNING 只能经 acquire_task_lease() CAS 进入（外审 round2 gate #1）
        if target is TaskStatus.RUNNING and current is TaskStatus.QUEUED:
            raise StateTransitionError(
                "QUEUED→RUNNING 必须经 acquire_task_lease() CAS 进入"
            )
        # 活跃/半活跃态走通用 API 只允许 owner-preserving 迁移（RUNNING<->WAITING_TOOL）；
        # 一切改变租约/终态语义的收口必须走专用函数
        # （commit_task_success / mark_task_failed / mark_task_cancelled /
        #   release_after_rate_limit / release_task_lease_to_queued /
        #   request_cancel / recover_interrupted_task），
        # 防止"状态已迁移但租约未释放"的脏状态（外审 round6 P1-2）。
        if current in (TaskStatus.RUNNING, TaskStatus.WAITING_TOOL, TaskStatus.CANCEL_REQUESTED):
            # 与其他接口统一的 fail-closed：活跃态 owner 必须存在（NULL/空串=损坏租约，
            # 不得被任意非空 token 推进——round7 P1-1）
            if row["owner_token"] is None:
                raise TaskLeaseHeld(f"{current.value} 无租约持有者，状态损坏；请走崩溃恢复")
            _require_token(owner_token)
            if owner_token != row["owner_token"]:
                raise TaskLeaseHeld(task_id)
            _owner_preserving = {
                (TaskStatus.RUNNING, TaskStatus.WAITING_TOOL),
                (TaskStatus.WAITING_TOOL, TaskStatus.RUNNING),
            }
            if (current, target) not in _owner_preserving:
                raise StateTransitionError(
                    f"活跃态 {current.value} -> {target.value} 不允许经通用 API："
                    "请使用对应的专用收口函数（租约语义集中管理）"
                )
        conn.execute(
            "UPDATE tasks SET status = ?, error = COALESCE(?, error), updated_at = ? WHERE id = ?",
            (target.value, error, now_iso(), task_id),
        )
        events.append_event_conn(
            conn, "task.status",
            {"from": current.value, "to": target.value, "error": error},
            run_id=row["run_id"], task_id=task_id,
        )
    return get_task(db, task_id)


def acquire_task_lease(db: Database, task_id: str, owner_token: str) -> bool:
    """QUEUED → RUNNING 的原子 CAS：只有抢到租约的执行者可以运行任务。"""
    _require_token(owner_token)
    with db.transaction() as conn:
        cur = conn.execute(
            "UPDATE tasks SET status = ?, owner_token = ?, updated_at = ?"
            " WHERE id = ? AND status = ? AND owner_token IS NULL",
            (TaskStatus.RUNNING.value, owner_token, now_iso(), task_id, TaskStatus.QUEUED.value),
        )
        if cur.rowcount != 1:
            return False
        row = conn.execute("SELECT run_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        events.append_event_conn(
            conn, "task.lease_acquired", {"owner": owner_token[:8]},
            run_id=row["run_id"], task_id=task_id,
        )
    return True


def _release_lease(conn, task_id: str, owner_token: str | None, event_type: str) -> None:
    """在已有事务里清除租约（必须已校验 owner）。"""
    row = conn.execute("SELECT run_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.execute(
        "UPDATE tasks SET owner_token = NULL, updated_at = ? WHERE id = ? AND owner_token = ?",
        (now_iso(), task_id, owner_token),
    )
    if row is not None:
        events.append_event_conn(conn, event_type, {"owner": (owner_token or "")[:8]}, run_id=row["run_id"], task_id=task_id)


def release_task_lease_to_queued(db: Database, task_id: str, owner_token: str) -> TaskRecord:
    """限流等场景：RUNNING → QUEUED 并释放租约（同事务）。限流+取消竞态请用 release_after_rate_limit。"""
    _require_token(owner_token)
    with db.transaction() as conn:
        row = conn.execute("SELECT status, owner_token FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise LookupError(task_id)
        if row["owner_token"] is None or owner_token != row["owner_token"]:
            raise TaskLeaseHeld(task_id)
        if TaskStatus(row["status"]) is not TaskStatus.RUNNING:
            raise StateTransitionError(f"仅 RUNNING 可回队列，当前 {row['status']}")
        conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (TaskStatus.QUEUED.value, now_iso(), task_id),
        )
        _release_lease(conn, task_id, owner_token, "task.lease_released_queued")
        events.append_event_conn(
            conn, "task.status", {"from": "RUNNING", "to": "QUEUED"}, task_id=task_id,
            run_id=conn.execute("SELECT run_id FROM tasks WHERE id = ?", (task_id,)).fetchone()["run_id"],
        )
    return get_task(db, task_id)


def release_after_rate_limit(db: Database, task_id: str, owner_token: str) -> TaskStatus:
    """限流收口的原子语义（外审 round2 gate #3）：
    RUNNING → QUEUED（释放租约）；若期间已被置 CANCEL_REQUESTED → CANCELLED；其它状态拒绝。"""
    _require_token(owner_token)
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT status, owner_token, run_id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise LookupError(task_id)
        if row["owner_token"] is None or owner_token != row["owner_token"]:
            raise TaskLeaseHeld(task_id)
        current = TaskStatus(row["status"])
        if current is TaskStatus.RUNNING:
            conn.execute(
                "UPDATE tasks SET status = ?, owner_token = NULL, updated_at = ? WHERE id = ?",
                (TaskStatus.QUEUED.value, now_iso(), task_id),
            )
            events.append_event_conn(
                conn, "task.status", {"from": "RUNNING", "to": "QUEUED", "reason": "rate limit"},
                run_id=row["run_id"], task_id=task_id,
            )
            return TaskStatus.QUEUED
        if current is TaskStatus.CANCEL_REQUESTED:
            conn.execute(
                "UPDATE tasks SET status = ?, owner_token = NULL, updated_at = ? WHERE id = ?",
                (TaskStatus.CANCELLED.value, now_iso(), task_id),
            )
            events.append_event_conn(
                conn, "task.status", {"from": "CANCEL_REQUESTED", "to": "CANCELLED", "reason": "cancel wins over rate limit"},
                run_id=row["run_id"], task_id=task_id,
            )
            return TaskStatus.CANCELLED
        raise StateTransitionError(f"限流收口不允许从 {current.value}")


def begin_task_attempt(
    db: Database,
    task_id: str,
    owner_token: str,
    *,
    role_id: str,
    provider_profile: str,
    model: str,
    reasoning: str | None,
    context_manifest: dict | None = None,
) -> tuple[int, str]:
    """开始一次尝试：attempt+1（含上限检查）+ 创建 invocation + 两个事件，**同一事务**（外审 round2 gate #4）。
    仅限持有租约的执行者调用。"""
    _require_token(owner_token)
    iid = new_id("inv")
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT attempt, max_attempts, owner_token, status, run_id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise LookupError(task_id)
        # ownerless RUNNING = 状态损坏；None/错 token 不得绕过（round4 P1-2）
        if row["owner_token"] is None or owner_token != row["owner_token"]:
            raise TaskLeaseHeld(task_id)
        # 必须仍是 RUNNING：抢租约前被取消的任务不得再消耗 attempt（round3 P1-a）
        if TaskStatus(row["status"]) is not TaskStatus.RUNNING:
            raise TaskNotRunnable(f"attempt 递增要求 RUNNING，当前 {row['status']}")
        if row["attempt"] + 1 > row["max_attempts"]:
            from mmagent.agent.errors import AttemptsExhausted

            raise AttemptsExhausted(f"尝试次数到顶: {row['attempt']}/{row['max_attempts']}")
        attempt = row["attempt"] + 1
        conn.execute(
            "UPDATE tasks SET attempt = ?, updated_at = ? WHERE id = ?", (attempt, now_iso(), task_id)
        )
        conn.execute(
            "INSERT INTO agent_invocations(id, task_id, role_id, provider_profile, model, reasoning,"
            " context_manifest_json, started_at, status)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                iid, task_id, role_id, provider_profile, model, reasoning,
                json.dumps(context_manifest or {}, ensure_ascii=False),
                now_iso(), InvocationStatus.RUNNING.value,
            ),
        )
        events.append_event_conn(
            conn, "task.attempt", {"attempt": attempt},
            run_id=row["run_id"], task_id=task_id, invocation_id=iid,
        )
        events.append_event_conn(
            conn, "invocation.started",
            {"role": role_id, "model": model, "reasoning": reasoning},
            run_id=row["run_id"], task_id=task_id, invocation_id=iid,
        )
    return attempt, iid


def request_cancel(db: Database, task_id: str, *, owner_token: str | None = None) -> TaskRecord:
    """取消请求：RUNNING/WAITING_TOOL/QUEUED/READY → CANCEL_REQUESTED（DB 是取消的持久真相）。"""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT status, owner_token, run_id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise LookupError(task_id)
        current = TaskStatus(row["status"])
        if current in (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.QUEUED):
            # 无活跃执行者：直接 CANCELLED，不留悬挂状态（round2 gate #3）
            if not can_transition(current, TaskStatus.CANCELLED):
                raise StateTransitionError(f"{current.value} 不能请求取消")
            conn.execute(
                "UPDATE tasks SET status = ?, owner_token = NULL, updated_at = ? WHERE id = ?",
                (TaskStatus.CANCELLED.value, now_iso(), task_id),
            )
            events.append_event_conn(
                conn, "task.status", {"from": current.value, "to": TaskStatus.CANCELLED.value, "reason": "cancel request (no executor)"},
                run_id=row["run_id"], task_id=task_id,
            )
        elif current in (TaskStatus.RUNNING, TaskStatus.WAITING_TOOL, TaskStatus.CANCEL_REQUESTED):
            # 活跃执行者语义（round4 P1-1 收死）：必须出示租约 token；
            # CANCEL_REQUESTED 的重复取消也走这里（幂等确认），不得由非 owner 直接关闭。
            if row["owner_token"] is None:
                raise TaskLeaseHeld(f"{current.value} 无租约持有者，状态损坏；请走崩溃恢复")
            _require_token(owner_token)
            if owner_token != row["owner_token"]:
                raise TaskLeaseHeld(task_id)
            if current is not TaskStatus.CANCEL_REQUESTED:
                if not can_transition(current, TaskStatus.CANCEL_REQUESTED):
                    raise StateTransitionError(f"{current.value} 不能请求取消")
                conn.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                    (TaskStatus.CANCEL_REQUESTED.value, now_iso(), task_id),
                )
                events.append_event_conn(
                    conn, "task.cancel_requested", {}, run_id=row["run_id"], task_id=task_id,
                )
        else:
            raise StateTransitionError(f"{current.value} 不能请求取消（终态/恢复态）")
    return get_task(db, task_id)


def recover_interrupted_task(db: Database, task_id: str, reason: str) -> TaskRecord:
    """Crash-recovery privilege path for an orphaned active task.

    The task and every still-RUNNING invocation owned by that task are closed in
    the same transaction.  Recovery must never leave telemetry claiming an
    invocation is live after its task has been failed closed.
    """
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT status, run_id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise LookupError(task_id)
        current = TaskStatus(row["status"])
        if current not in (
            TaskStatus.RUNNING,
            TaskStatus.WAITING_TOOL,
            TaskStatus.CANCEL_REQUESTED,
        ):
            raise StateTransitionError(f"{current.value} 不是可恢复的中断态")

        ended_at = now_iso()
        running_invocations = conn.execute(
            "SELECT id FROM agent_invocations WHERE task_id = ? AND status = ?",
            (task_id, InvocationStatus.RUNNING.value),
        ).fetchall()
        for invocation in running_invocations:
            invocation_id = invocation["id"]
            conn.execute(
                "UPDATE agent_invocations SET status = ?, ended_at = ? WHERE id = ?",
                (InvocationStatus.FAILED.value, ended_at, invocation_id),
            )
            events.append_event_conn(
                conn,
                "invocation.finished",
                {
                    "status": InvocationStatus.FAILED.value,
                    "error": reason[:200],
                    "recovered": True,
                },
                run_id=row["run_id"],
                task_id=task_id,
                invocation_id=invocation_id,
            )

        conn.execute(
            "UPDATE tasks SET status = ?, owner_token = NULL, error = ?, updated_at = ? WHERE id = ?",
            (TaskStatus.FAILED.value, reason, ended_at, task_id),
        )
        events.append_event_conn(
            conn,
            "task.recovered",
            {
                "from": current.value,
                "to": "FAILED",
                "reason": reason[:200],
                "closed_invocations": len(running_invocations),
            },
            run_id=row["run_id"],
            task_id=task_id,
        )
    return get_task(db, task_id)


def retry_task(db: Database, task_id: str) -> TaskRecord:
    """显式重试入口：FAILED/CANCELLED/BLOCKED/DEFERRED → READY（不允许 AgentLoop 隐式复活，外审 P1-2）。"""
    return transition_task(db, task_id, TaskStatus.READY)


def commit_task_success(
    db: Database,
    task_id: str,
    *,
    artifacts: list[dict[str, Any]],
    result: dict[str, Any] | None = None,
    owner_token: str | None = None,
) -> TaskRecord:
    """提交成功：状态迁移 + artifact 落库 + 事件在**同一事务**。

    - 只有当前状态是 RUNNING 且调用者持有租约（owner_token 匹配）才能提交；
      取消请求（CANCEL_REQUESTED）到达后提交必然失败——取消是赢家（外审 P1-3/P1-7）。
    """
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT status, owner_token, run_id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"task 不存在: {task_id}")
        if TaskStatus(row["status"]) is not TaskStatus.RUNNING:
            raise StateTransitionError(
                f"SUCCEEDED 只能从 RUNNING 提交，当前 {row['status']}"
            )
        # RUNNING 必须由租约持有（round5 P1-3：不再保留 ownerless 直连例外；
        # 未来非 Agent task 应单独设计状态路径）
        _require_token(owner_token)
        if row["owner_token"] is None or owner_token != row["owner_token"]:
            raise TaskLeaseHeld(f"提交成功需要持有执行租约: {task_id}")
        # required 产物完整性：expected 里 required 的路径必须全部出现在提交行里
        # （防止"空成功提交"绕过验收语义，外审 round2 gate #2）
        expected = json.loads(
            conn.execute("SELECT expected_artifacts_json FROM tasks WHERE id = ?", (task_id,)).fetchone()[0]
            or "[]"
        )
        submitted = {a["rel_path"] for a in artifacts}
        for exp in expected:
            if exp.get("required", True) and exp.get("rel_path") not in submitted:
                raise StateTransitionError(
                    f"提交成功缺少 required 产物: {exp.get('rel_path')}（不允许空成功提交）"
                )
        for a in artifacts:
            conn.execute(
                "INSERT INTO artifacts(id, task_id, rel_path, kind, schema_id, version,"
                " hash, sealed_path, producer_task, input_versions_json, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    a["id"],
                    task_id,
                    a["rel_path"],
                    a.get("kind", "json"),
                    a.get("schema_id"),
                    a["version"],
                    a["hash"],
                    a.get("sealed_path"),
                    task_id,
                    json.dumps(a.get("input_versions", {}), ensure_ascii=False),
                    now_iso(),
                ),
            )
        conn.execute(
            "UPDATE tasks SET status = ?, owner_token = NULL, result_json = ?, updated_at = ? WHERE id = ?",
            (TaskStatus.SUCCEEDED.value, json.dumps(result or {}, ensure_ascii=False), now_iso(), task_id),
        )
        events.append_event_conn(
            conn,
            "task.succeeded",
            {"artifacts": [a["rel_path"] for a in artifacts]},
            run_id=row["run_id"],
            task_id=task_id,
        )
    return get_task(db, task_id)


def mark_task_failed(
    db: Database,
    task_id: str,
    *,
    error: str,
    owner_token: str | None = None,
) -> TaskRecord:
    """失败收口（持有租约者调用）：RUNNING/WAITING_TOOL → FAILED 并释放租约，事件同事务。"""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT status, owner_token, run_id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise LookupError(task_id)
        current = TaskStatus(row["status"])
        if current in (TaskStatus.RUNNING, TaskStatus.WAITING_TOOL):
            # 与 request_cancel 同款 fail-closed：运行态必须由租约持有者收口（round4 P2）
            if row["owner_token"] is None:
                raise TaskLeaseHeld(f"{current.value} 无租约持有者，状态损坏；请走崩溃恢复")
            _require_token(owner_token)
            if owner_token != row["owner_token"]:
                raise TaskLeaseHeld(task_id)
        if not can_transition(current, TaskStatus.FAILED):
            raise StateTransitionError(f"非法状态迁移: {current.value} -> FAILED")
        conn.execute(
            "UPDATE tasks SET status = ?, owner_token = NULL, error = ?, updated_at = ? WHERE id = ?",
            (TaskStatus.FAILED.value, error, now_iso(), task_id),
        )
        events.append_event_conn(
            conn, "task.status", {"from": current.value, "to": TaskStatus.FAILED.value, "error": error},
            run_id=row["run_id"], task_id=task_id,
        )
    return get_task(db, task_id)


def mark_task_cancelled(
    db: Database,
    task_id: str,
    *,
    owner_token: str | None = None,
    reason: str = "",
) -> TaskRecord:
    """取消收口（由持有租约的执行者调用）：活跃态 → CANCELLED，释放租约，事件同事务。
    非活跃任务（PENDING/READY/QUEUED）的取消走 request_cancel()（直接 CANCELLED）。"""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT status, owner_token, run_id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise LookupError(task_id)
        current = TaskStatus(row["status"])
        if current in (TaskStatus.RUNNING, TaskStatus.WAITING_TOOL, TaskStatus.CANCEL_REQUESTED):
            # 活跃态收口必须由租约持有者完成；ownerless 活跃态视为损坏（round5 P1-1）
            if row["owner_token"] is None:
                raise TaskLeaseHeld(f"{current.value} 无租约持有者，状态损坏；请走崩溃恢复")
            _require_token(owner_token)
            if owner_token != row["owner_token"]:
                raise TaskLeaseHeld(task_id)
        if not can_transition(current, TaskStatus.CANCELLED):
            raise StateTransitionError(f"非法状态迁移: {current.value} -> CANCELLED")
        conn.execute(
            "UPDATE tasks SET status = ?, owner_token = NULL, updated_at = ? WHERE id = ?",
            (TaskStatus.CANCELLED.value, now_iso(), task_id),
        )
        events.append_event_conn(
            conn, "task.status", {"from": current.value, "to": TaskStatus.CANCELLED.value, "reason": reason},
            run_id=row["run_id"], task_id=task_id,
        )
    return get_task(db, task_id)


def increment_attempt(db: Database, task_id: str, *, owner_token: str | None = None) -> int:
    """尝试数递增（外审 P2-1）。低层 helper：AgentLoop 应使用 begin_task_attempt()。
    必须出示有效租约 token。"""
    _require_token(owner_token)
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT attempt, max_attempts, owner_token, status FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise LookupError(task_id)
        if row["owner_token"] is None or owner_token != row["owner_token"]:
            raise TaskLeaseHeld(task_id)
        # 必须仍是 RUNNING：抢租约前被取消的任务不得再消耗 attempt（round3 P1-a）
        if TaskStatus(row["status"]) is not TaskStatus.RUNNING:
            raise TaskNotRunnable(f"attempt 递增要求 RUNNING，当前 {row['status']}")
        if row["attempt"] + 1 > row["max_attempts"]:
            from mmagent.agent.errors import AttemptsExhausted

            raise AttemptsExhausted(f"尝试次数到顶: {row['attempt']}/{row['max_attempts']}")
        attempt = row["attempt"] + 1
        conn.execute("UPDATE tasks SET attempt = ?, updated_at = ? WHERE id = ?", (attempt, now_iso(), task_id))
    return attempt


def add_dependency(db: Database, task_id: str, depends_on: str) -> None:
    db.execute(
        "INSERT OR IGNORE INTO task_dependencies(task_id, depends_on) VALUES (?,?)",
        (task_id, depends_on),
    )


# ---------------------------------------------------------------- artifact
@dataclass(frozen=True)
class RegisteredArtifact(ArtifactRecord):
    pass


def latest_artifact_version(db: Database, task_id: str, rel_path: str) -> int:
    r = db.query_one(
        "SELECT MAX(version) AS v FROM artifacts WHERE task_id = ? AND rel_path = ?",
        (task_id, rel_path),
    )
    return int(r["v"] or 0)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- invocation
def create_invocation(
    db: Database,
    *,
    task_id: str,
    role_id: str,
    provider_profile: str,
    model: str,
    reasoning: str | None,
    context_manifest: dict | None = None,
) -> str:
    """低层 helper（telemetry）：AgentLoop 应使用 begin_task_attempt()。"""
    iid = new_id("inv")
    with db.transaction() as conn:
        trow = conn.execute("SELECT run_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if trow is None:
            raise LookupError(f"task 不存在: {task_id}")
        run_id = trow["run_id"]
        conn.execute(
            "INSERT INTO agent_invocations(id, task_id, role_id, provider_profile, model, reasoning,"
            " context_manifest_json, started_at, status)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                iid,
                task_id,
                role_id,
                provider_profile,
                model,
                reasoning,
                json.dumps(context_manifest or {}, ensure_ascii=False),
                now_iso(),
                InvocationStatus.RUNNING.value,
            ),
        )
        events.append_event_conn(
            conn,
            "invocation.started",
            {"role": role_id, "model": model, "reasoning": reasoning},
            run_id=run_id,
            task_id=task_id,
            invocation_id=iid,
        )
    return iid


def finish_invocation(
    db: Database,
    invocation_id: str,
    status: InvocationStatus,
    *,
    usage: dict | None = None,
    error: str | None = None,
) -> None:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT i.task_id, i.status AS inv_status, t.run_id AS run_id FROM agent_invocations i"
            " JOIN tasks t ON t.id = i.task_id WHERE i.id = ?",
            (invocation_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"invocation 不存在: {invocation_id}")
        if status not in (InvocationStatus.SUCCEEDED, InvocationStatus.FAILED, InvocationStatus.CANCELLED):
            raise StateTransitionError(f"finish_invocation 只允许终态目标，收到 {status.value}")
        if row["inv_status"] != InvocationStatus.RUNNING.value:
            raise StateTransitionError(f"invocation 已结束（{row['inv_status']}），不允许重复 finish")
        conn.execute(
            "UPDATE agent_invocations SET status = ?, ended_at = ?, usage_json = COALESCE(?, usage_json) WHERE id = ?",
            (status.value, now_iso(), json.dumps(usage, ensure_ascii=False) if usage else None, invocation_id),
        )
        events.append_event_conn(
            conn,
            "invocation.finished",
            {"status": status.value, "error": error, "usage": usage},
            invocation_id=invocation_id,
            task_id=row["task_id"] if row else None,
            run_id=row["run_id"] if row else None,
        )
