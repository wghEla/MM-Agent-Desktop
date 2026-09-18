"""append-only 事件存储。

不变量：
- 只允许 INSERT；UPDATE/DELETE 由触发器直接 ABORT（schema_v1）。
- 事件是回放/审计/断点判定的事实来源；状态表的每次迁移都应伴随事件。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from mmagent.state.db import Database


@dataclass(frozen=True)
class Event:
    id: int
    ts: str
    type: str
    run_id: str | None
    task_id: str | None
    invocation_id: str | None
    payload: dict[str, Any] = field(default_factory=dict)


def append_event_conn(
    conn,
    type: str,  # noqa: A002 - 事件类型是领域词
    payload: dict[str, Any] | None = None,
    *,
    run_id: str | None = None,
    task_id: str | None = None,
    invocation_id: str | None = None,
) -> int:
    """在**调用方已有事务**里追加事件（transactional outbox：状态变更与事件同提交）。"""
    cur = conn.execute(
        "INSERT INTO events(ts, run_id, task_id, invocation_id, type, payload_json)"
        " VALUES (strftime('%Y-%m-%dT%H:%M:%fZ','now'), ?, ?, ?, ?, ?)",
        (
            run_id,
            task_id,
            invocation_id,
            type,
            json.dumps(payload or {}, ensure_ascii=False),
        ),
    )
    return int(cur.lastrowid)


def append_event(
    db: Database,
    type: str,  # noqa: A002
    payload: dict[str, Any] | None = None,
    *,
    run_id: str | None = None,
    task_id: str | None = None,
    invocation_id: str | None = None,
) -> int:
    """独立事务的事件追加（只在事件本身即完整业务变更时使用）。"""
    with db.transaction() as conn:
        return append_event_conn(
            conn, type, payload, run_id=run_id, task_id=task_id, invocation_id=invocation_id
        )


def query_events(
    db: Database,
    *,
    run_id: str | None = None,
    task_id: str | None = None,
    type: str | None = None,  # noqa: A002
    after_id: int = 0,
    limit: int = 1000,
) -> list[Event]:
    sql = "SELECT id, ts, run_id, task_id, invocation_id, type, payload_json FROM events WHERE id > ?"
    params: list[Any] = [after_id]
    if run_id is not None:
        sql += " AND run_id = ?"
        params.append(run_id)
    if task_id is not None:
        sql += " AND task_id = ?"
        params.append(task_id)
    if type is not None:
        sql += " AND type = ?"
        params.append(type)
    sql += " ORDER BY id LIMIT ?"
    params.append(limit)
    return [
        Event(
            id=r["id"],
            ts=r["ts"],
            type=r["type"],
            run_id=r["run_id"],
            task_id=r["task_id"],
            invocation_id=r["invocation_id"],
            payload=json.loads(r["payload_json"]),
        )
        for r in db.query(sql, params)
    ]
