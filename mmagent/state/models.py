"""状态模型：Task/Run 状态枚举与显式迁移表。

设计约束（总方案 §4.3）：
- 状态必须显式枚举，禁止模糊布尔；
- 状态迁移必须走迁移表白名单，非法迁移抛 StateTransitionError；
- SQLite 是唯一状态真相（本模块只定义语义，落盘在 state/db.py）。
"""
from __future__ import annotations

import enum
from typing import Final

from pydantic import BaseModel, Field


class TaskStatus(enum.StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_TOOL = "WAITING_TOOL"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"
    DEFERRED = "DEFERRED"


class RunStatus(enum.StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StageStatus(enum.StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class InvocationStatus(enum.StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ToolCallStatus(enum.StrEnum):
    OK = "ok"
    ERROR = "error"
    DENIED = "denied"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------- 状态迁移表
# 终态语义说明：
# - SUCCEEDED 是终态：只能由 Runtime 事务提交（expected artifacts + schema + verifier 全过），
#   任何路径都不得从 SUCCEEDED 迁出（对应原 Skill「done 标记不由模型宣告」铁律）。
# - FAILED / CANCELLED / BLOCKED / DEFERRED 可由显式重试/重排回 READY。
_TASK_TRANSITIONS: Final[dict[TaskStatus, frozenset[TaskStatus]]] = {
    TaskStatus.PENDING: frozenset(
        {TaskStatus.READY, TaskStatus.BLOCKED, TaskStatus.DEFERRED, TaskStatus.CANCEL_REQUESTED, TaskStatus.CANCELLED}
    ),
    TaskStatus.READY: frozenset(
        {TaskStatus.QUEUED, TaskStatus.BLOCKED, TaskStatus.DEFERRED, TaskStatus.CANCEL_REQUESTED, TaskStatus.CANCELLED}
    ),
    TaskStatus.QUEUED: frozenset(
        {TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED, TaskStatus.CANCELLED}
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.WAITING_TOOL,
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.QUEUED,  # 限流等场景：任务回队列（不是失败）
            TaskStatus.CANCEL_REQUESTED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING_TOOL: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.FAILED,
            TaskStatus.CANCEL_REQUESTED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.SUCCEEDED: frozenset(),  # 终态（且只能经 commit_task_success 进入，见 repositories）
    TaskStatus.FAILED: frozenset({TaskStatus.READY, TaskStatus.DEFERRED, TaskStatus.BLOCKED}),
    # 取消请求只允许走向 CANCELLED：普通失败路径不得把取消洗成 FAILED（外审 P1-3）。
    # 清理失败的残留由崩溃恢复显式标记 FAILED。
    TaskStatus.CANCEL_REQUESTED: frozenset({TaskStatus.CANCELLED}),
    TaskStatus.CANCELLED: frozenset({TaskStatus.READY}),
    TaskStatus.BLOCKED: frozenset({TaskStatus.READY, TaskStatus.PENDING, TaskStatus.CANCELLED}),
    TaskStatus.DEFERRED: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
}


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    return target in _TASK_TRANSITIONS[current]


def require_transition(current: TaskStatus, target: TaskStatus) -> None:
    if not can_transition(current, target):
        raise StateTransitionError(f"非法状态迁移: {current.value} -> {target.value}")


class StateTransitionError(Exception):
    """非法状态迁移。"""


# Run 状态迁移表（外审 P2-3：Run 也是状态真相，不允许任意迁移）
_RUN_TRANSITIONS: Final[dict[RunStatus, frozenset[RunStatus]]] = {
    RunStatus.CREATED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED}),
    RunStatus.RUNNING: frozenset({RunStatus.PAUSED, RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}),
    RunStatus.PAUSED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def can_transition_run(current: RunStatus, target: RunStatus) -> bool:
    return target in _RUN_TRANSITIONS[current]


# ---------------------------------------------------------------- Pydantic 记录模型
class TaskRecord(BaseModel):
    id: str
    run_id: str
    stage_key: str
    node_key: str
    role_id: str | None = None
    kind: str = "agent"  # agent | script | gate
    status: TaskStatus = TaskStatus.PENDING
    attempt: int = 0
    max_attempts: int = 2
    expected_artifacts: list[dict] = Field(default_factory=list)
    result: dict | None = None
    error: str | None = None


class ArtifactRecord(BaseModel):
    id: str
    task_id: str
    rel_path: str
    kind: str = "json"
    schema_id: str | None = None
    version: int = 1
    hash: str
    producer_task: str | None = None
    input_versions: dict[str, int] = Field(default_factory=dict)


class IssueStatus(enum.StrEnum):
    """Issue Ledger 状态机（复现上游 台账 五态）。"""

    PENDING_FIX = "待改"
    PENDING_REVIEW = "待复核"
    RESOLVED = "已消解"
    UNRESOLVED = "未消解"
    SHELVED = "搁置"


ISSUE_SEVERITIES: Final[tuple[str, ...]] = ("硬伤", "正确性", "叙述", "版式")
ISSUE_TARGETS: Final[tuple[str, ...]] = ("算", "图", "文")
BLOCKING_SEVERITIES: Final[frozenset[str]] = frozenset({"硬伤", "正确性"})
