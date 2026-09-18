"""状态机单测：迁移表白名单、终态不可变、失败重试路径。"""
from __future__ import annotations

import pytest

from mmagent.state import repositories
from mmagent.state.models import RunStatus, StateTransitionError, TaskStatus, can_transition


def test_happy_path_to_succeeded(db, run_id):
    t = repositories.create_task(db, run_id=run_id, stage_key="S0", node_key="S0.0")
    t = repositories.transition_task(db, t.id, TaskStatus.READY)
    t = repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    owner = repositories.new_owner_token()
    assert repositories.acquire_task_lease(db, t.id, owner)
    t = repositories.commit_task_success(db, t.id, artifacts=[], owner_token=owner)
    assert t.status is TaskStatus.SUCCEEDED


def test_illegal_transition_rejected(db, run_id):
    t = repositories.create_task(db, run_id=run_id, stage_key="S0", node_key="S0.1")
    t = repositories.transition_task(db, t.id, TaskStatus.READY)
    with pytest.raises(StateTransitionError):
        repositories.transition_task(db, t.id, TaskStatus.RUNNING)  # READY 不能跳到 RUNNING


def test_succeeded_is_terminal(db, run_id):
    t = repositories.create_task(db, run_id=run_id, stage_key="S0", node_key="S0.2")
    t = repositories.transition_task(db, t.id, TaskStatus.READY)
    t = repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    owner = repositories.new_owner_token()
    assert repositories.acquire_task_lease(db, t.id, owner)
    t = repositories.commit_task_success(db, t.id, artifacts=[], owner_token=owner)
    for target in TaskStatus:
        if target is not TaskStatus.SUCCEEDED:
            assert not can_transition(TaskStatus.SUCCEEDED, target), target


def test_failed_can_retry(db, run_id):
    t = repositories.create_task(db, run_id=run_id, stage_key="S0", node_key="S0.3")
    t = repositories.transition_task(db, t.id, TaskStatus.READY)
    t = repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    owner = repositories.new_owner_token()
    assert repositories.acquire_task_lease(db, t.id, owner)
    t = repositories.mark_task_failed(db, t.id, error="boom", owner_token=owner)
    t = repositories.transition_task(db, t.id, TaskStatus.READY)
    assert t.status is TaskStatus.READY
    assert t.error == "boom"  # 错误留痕


def test_running_back_to_queued_for_rate_limit(db, run_id):
    t = repositories.create_task(db, run_id=run_id, stage_key="S0", node_key="S0.4")
    t = repositories.transition_task(db, t.id, TaskStatus.READY)
    t = repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    owner = repositories.new_owner_token()
    assert repositories.acquire_task_lease(db, t.id, owner)
    t = repositories.release_task_lease_to_queued(db, t.id, owner)  # 限流回队列
    assert t.status is TaskStatus.QUEUED


def test_run_status_flow(db, run_id):
    repositories.set_run_status(db, run_id, RunStatus.RUNNING)
    repositories.set_run_status(db, run_id, RunStatus.FAILED)
    row = db.query_one("SELECT status, ended_at FROM runs WHERE id = ?", (run_id,))
    assert row["status"] == "FAILED" and row["ended_at"]


def test_cancel_request_then_cancelled(db, run_id):
    t = repositories.create_task(db, run_id=run_id, stage_key="S0", node_key="S0.5")
    t = repositories.transition_task(db, t.id, TaskStatus.READY)
    t = repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    owner = repositories.new_owner_token()
    assert repositories.acquire_task_lease(db, t.id, owner)
    t = repositories.request_cancel(db, t.id, owner_token=owner)  # 持有租约期间 → CANCEL_REQUESTED
    assert t.status is TaskStatus.CANCEL_REQUESTED
    t = repositories.mark_task_cancelled(db, t.id, owner_token=owner)  # 执行者收口
    assert t.status is TaskStatus.CANCELLED
    repositories.retry_task(db, t.id)  # 显式重跑
    assert repositories.get_task(db, t.id).status is TaskStatus.READY
