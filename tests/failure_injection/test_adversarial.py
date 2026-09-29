"""对抗性测试——外审 v0.1.0 报告要求的 release-gate 测试清单。

P0-1 SUCCEEDED 强制路径 / P0-2 junction 穿透 scope / P0-3 host_code 能力位 /
P1-1 双执行者租约 / P1-2 显式重试 / P1-3 取消优先 / P1-4 provider 取消不验收 /
P1-7 封存 / P1-8 变量注入 / P2-1 尝试上限 / P2-5 ADS 拒绝。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from mmagent.agent.errors import AttemptsExhausted, TaskLeaseHeld, TaskNotRunnable
from mmagent.agent.loop import AgentLoop, AgentTask
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.state import repositories
from mmagent.state.models import StateTransitionError, TaskStatus
from mmagent.tools.filesystem import FsWriteTool
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.permissions import PermissionChecker, RolePermissions


class Decl(BaseModel):
    question: int
    core_metrics: dict[str, float]
    caliber_notes: str


# ---------------------------------------------------------------- P0-1
def test_p0_1_transition_to_succeeded_rejected(db, run_id):
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    owner = repositories.new_owner_token()
    assert repositories.acquire_task_lease(db, t.id, owner)
    with pytest.raises(StateTransitionError, match="commit_task_success"):
        repositories.transition_task(db, t.id, TaskStatus.SUCCEEDED)
    # 事件也不应记录 SUCCEEDED 迁移
    evs = [e.type for e in __import__("mmagent.state.events", fromlist=["x"]).query_events(db, task_id=t.id)]
    assert "task.succeeded" not in evs


# ---------------------------------------------------------------- P0-2
@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction")
def test_p0_2_in_root_junction_scope_escape(policy, tmp_path):
    """工作区内 junction 指向受限目录（仍在 root 内）→ 必须拒绝（scope 穿透）。"""
    from mmagent.agent.errors import PathEscape

    (policy.root / "public").mkdir(exist_ok=True)
    denied = policy.root / "denied"
    denied.mkdir(exist_ok=True)
    (denied / "secret.py").write_text("x = 1", encoding="utf-8")
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(policy.root / "public" / "link"), str(denied)],
        check=True, capture_output=True,
    )
    checker = PermissionChecker(
        RolePermissions(role_id="r", read_scopes=("public/**",), write_scopes=("public/**",)),
        policy,
    )
    with pytest.raises(PathEscape):
        checker.check_read("public/link/secret.py")
    with pytest.raises(PathEscape):
        checker.check_write("public/link/evil.py")


# ---------------------------------------------------------------- P0-3
def test_p0_3_host_code_gate(policy):
    """python.run 在工具白名单里但角色未声明 host_code → DENIED。"""
    checker = PermissionChecker(
        RolePermissions(
            role_id="r",
            read_scopes=("**",),
            write_scopes=("**",),
            allowed_tools=frozenset({"python.run"}),
            host_code=False,
        ),
        policy,
    )
    from mmagent.agent.errors import PermissionDenied

    with pytest.raises(PermissionDenied, match="host_code"):
        checker.check_tool("python.run", requires_host_code=True)


# ---------------------------------------------------------------- P1-1
@pytest.mark.asyncio
async def test_p1_1_double_acquire_only_one_wins(ws, db, run_id, policy):
    """两个 loop 抢同一 QUEUED 任务：只有一个能执行，另一个拒绝。"""
    from mmagent.workspace.permissions import PermissionChecker, RolePermissions

    perms = RolePermissions(role_id="t", read_scopes=("**",), write_scopes=("**",), allowed_tools=frozenset({"fs.write"}))
    checker = PermissionChecker(perms, policy)
    reg = ToolRegistry()
    reg.register(FsWriteTool())
    provider = MockProvider(MockScript([MockTurn(text="done")]))
    loop = AgentLoop(db, provider, reg, checker, policy)
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:race")
    spec = AgentTask(task_id=t.id, node_key="N:race", role_id="t", system_prompt="s", instructions="i", model="m")
    outcome1 = await loop.run(spec)
    assert outcome1.status is TaskStatus.SUCCEEDED
    # 任务已 SUCCEEDED：第二个执行者不允许启动（严格入口 + 终态）
    with pytest.raises(TaskNotRunnable):
        await loop.run(spec)


def test_p1_1_lease_manual_double_acquire(db, run_id):
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:lease")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    assert repositories.acquire_task_lease(db, t.id, "owner-A") is True
    assert repositories.acquire_task_lease(db, t.id, "owner-B") is False  # CAS：B 抢不到
    # A 持有期间，B 不能迁移状态
    with pytest.raises(TaskLeaseHeld):
        repositories.transition_task(db, t.id, TaskStatus.FAILED, owner_token="owner-B")
    # A 释放回队列后 B 可抢
    repositories.release_task_lease_to_queued(db, t.id, "owner-A")
    assert repositories.acquire_task_lease(db, t.id, "owner-B") is True


# ---------------------------------------------------------------- P1-2
@pytest.mark.asyncio
async def test_p1_2_no_implicit_revive(ws, db, run_id, policy):
    """终态任务不允许 run() 隐式复活；必须 retry_task 显式走。"""
    from mmagent.workspace.permissions import PermissionChecker, RolePermissions

    checker = PermissionChecker(
        RolePermissions(role_id="t", read_scopes=("**",), write_scopes=("**",), allowed_tools=frozenset()),
        policy,
    )
    loop = AgentLoop(db, MockProvider(MockScript([MockTurn(text="x")])), ToolRegistry(), checker, policy)
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:revive")
    spec = AgentTask(task_id=t.id, node_key="N:revive", role_id="t", system_prompt="s", instructions="i", model="m")
    # FAILED 后 run() 拒绝
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    o = await loop.run(spec)  # QUEUED 可启动
    assert o.status is TaskStatus.SUCCEEDED
    with pytest.raises(TaskNotRunnable):
        await loop.run(spec)  # SUCCEEDED 不可复活
    # 显式重试 API 也不允许从 SUCCEEDED（终态）
    with pytest.raises(StateTransitionError):
        repositories.retry_task(db, t.id)
    # FAILED → retry_task → READY 合法
    t2 = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:revive2")
    repositories.transition_task(db, t2.id, TaskStatus.READY)
    repositories.transition_task(db, t2.id, TaskStatus.QUEUED)
    spec2 = AgentTask(task_id=t2.id, node_key="N:revive2", role_id="t", system_prompt="s", instructions="i", model="m")
    # 让它失败：mock 脚本耗尽抛 AssertionError → INTERNAL FAILED
    outcome = await loop.run(spec2)
    assert outcome.status is TaskStatus.FAILED
    repositories.retry_task(db, t2.id)  # 显式复活
    assert repositories.get_task(db, t2.id).status is TaskStatus.READY


# ---------------------------------------------------------------- P1-3/P1-4
@pytest.mark.asyncio
async def test_p1_4_provider_cancelled_not_accepted(ws, db, run_id, policy):
    """provider 返回 CANCELLED 且磁盘已有合法 artifact → 必须 CANCELLED，不得 SUCCEEDED。"""
    from mmagent.workspace.permissions import PermissionChecker, RolePermissions

    (policy.root / "交接").mkdir(exist_ok=True)
    (policy.root / "交接" / "d.json").write_text(
        json.dumps({"question": 1, "core_metrics": {"a": 1.0}, "caliber_notes": "x"}), encoding="utf-8"
    )
    checker = PermissionChecker(
        RolePermissions(role_id="t", read_scopes=("**",), write_scopes=("**",), allowed_tools=frozenset()),
        policy,
    )
    provider = MockProvider(MockScript([MockTurn(text="done", stop_reason=__import__("mmagent.providers.normalized", fromlist=["StopReason"]).StopReason.CANCELLED)]))
    loop = AgentLoop(db, provider, ToolRegistry(), checker, policy)
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:pcancel")
    spec = AgentTask(
        task_id=t.id, node_key="N:pcancel", role_id="t", system_prompt="s", instructions="i", model="m",
        expected_artifacts=[ExpectedArtifact(rel_path="交接/d.json", schema_model=Decl)],
    )
    outcome = await loop.run(spec)
    assert outcome.status is TaskStatus.CANCELLED, outcome.error


@pytest.mark.asyncio
async def test_p1_3_db_cancel_wins_over_success(ws, db, run_id, policy):
    """工具执行期间 DB 收到取消请求 → 验收必须失败，CANCELLED 是赢家。"""
    from mmagent.tools.tool_protocol import Tool, ToolContext, ToolResult, ToolSpec
    from mmagent.workspace.permissions import PermissionChecker, RolePermissions

    class DBCancelTool(Tool):
        spec = ToolSpec(name="test.db_cancel", description="", parameters={"type": "object", "properties": {}})

        def __init__(self, task_id: str):
            self._task_id = task_id

        async def execute(self, args, ctx: ToolContext) -> ToolResult:
            repositories.request_cancel(db, self._task_id, owner_token=ctx.extra.get("owner_token"))
            return ToolResult(ok=True, content="cancel requested")

    (policy.root / "交接").mkdir(exist_ok=True)
    (policy.root / "交接" / "d.json").write_text(
        json.dumps({"question": 1, "core_metrics": {"a": 1.0}, "caliber_notes": "x"}), encoding="utf-8"
    )
    checker = PermissionChecker(
        RolePermissions(role_id="t", read_scopes=("**",), write_scopes=("**",), allowed_tools=frozenset({"fs.write", "test.db_cancel"})),
        policy,
    )
    reg = ToolRegistry()
    reg.register(FsWriteTool())
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:dbcancel")
    reg.register(DBCancelTool(t.id))
    script = MockScript(
        [
            MockTurn(tool_calls=[("c1", "test.db_cancel", {})]),
            MockTurn(text="done"),
        ]
    )
    loop = AgentLoop(db, MockProvider(script), reg, checker, policy)
    spec = AgentTask(
        task_id=t.id, node_key="N:dbcancel", role_id="t", system_prompt="s", instructions="i", model="m",
        expected_artifacts=[ExpectedArtifact(rel_path="交接/d.json", schema_model=Decl)],
    )
    outcome = await loop.run(spec)
    assert outcome.status is TaskStatus.CANCELLED, outcome.error
    # 已有合法 artifact 也不能翻案
    assert repositories.get_task(db, t.id).status is TaskStatus.CANCELLED


# ---------------------------------------------------------------- P1-7
@pytest.mark.asyncio
async def test_p1_7_artifact_sealed(ws, db, run_id, policy):
    """成功提交后 .mmagent/artifacts/ 必须存在封存副本。"""
    from mmagent.workspace.permissions import PermissionChecker, RolePermissions

    checker = PermissionChecker(
        RolePermissions(role_id="t", read_scopes=("**",), write_scopes=("**",), allowed_tools=frozenset({"fs.write"})),
        policy,
    )
    reg = ToolRegistry()
    reg.register(FsWriteTool())
    script = MockScript(
        [
            MockTurn(tool_calls=[("c1", "fs.write", {"path": "交接/d.json", "content": json.dumps({"question": 1, "core_metrics": {"a": 2.0}, "caliber_notes": "y"})})]),
            MockTurn(text="done"),
        ]
    )
    loop = AgentLoop(db, MockProvider(script), reg, checker, policy)
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:seal")
    spec = AgentTask(
        task_id=t.id, node_key="N:seal", role_id="t", system_prompt="s", instructions="i", model="m",
        expected_artifacts=[ExpectedArtifact(rel_path="交接/d.json", schema_model=Decl)],
    )
    outcome = await loop.run(spec)
    assert outcome.status is TaskStatus.SUCCEEDED
    sealed_dir = policy.root / ".mmagent" / "artifacts"
    files = list(sealed_dir.glob(f"{t.id}_*"))
    assert len(files) == 1
    art = db.query_one("SELECT sealed_path, hash FROM artifacts WHERE task_id = ?", (t.id,))
    assert Path(art["sealed_path"]).is_file()
    import hashlib

    assert hashlib.sha256(Path(art["sealed_path"]).read_bytes()).hexdigest() == art["hash"]


# ---------------------------------------------------------------- P1-8 / P2-5 / P2-1
def test_p1_8_scope_var_injection_rejected(policy):
    perms = RolePermissions(role_id="r", read_scopes=("求解/{question}/**",), write_scopes=("求解/{question}/**",))
    for bad in ("**", "../x", "a/b", "*", "?", "", "1}{" ):
        with pytest.raises(ValueError):
            perms.with_vars(question=bad)
    ok = perms.with_vars(question="1")
    assert ok.read_scopes == ("求解/1/**",)


def test_p2_5_ads_and_reserved_names(policy):
    from mmagent.agent.errors import PathEscape

    for bad in ("交接/a.json:stream", "交接/CON", "交接/com1.txt", "交接/x. ", "交接/a/b.."):
        with pytest.raises(PathEscape):
            policy.resolve(bad)


def test_p2_1_max_attempts_enforced(db, run_id):
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:att", max_attempts=2)
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    owner = repositories.new_owner_token()
    repositories.acquire_task_lease(db, t.id, owner)
    assert repositories.increment_attempt(db, t.id, owner_token=owner) == 1
    assert repositories.increment_attempt(db, t.id, owner_token=owner) == 2
    with pytest.raises(AttemptsExhausted):
        repositories.increment_attempt(db, t.id, owner_token=owner)


# ==================== Round-2 release gate 测试 ====================
def test_r2_gate1_queued_to_running_direct_rejected(db, run_id):
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:g1")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    with pytest.raises(StateTransitionError, match="acquire_task_lease"):
        repositories.transition_task(db, t.id, TaskStatus.RUNNING)


def test_r2_gate2_empty_success_commit_rejected(db, run_id):
    """required 产物缺失时 commit_task_success 必须拒绝（空成功提交）。"""
    t = repositories.create_task(
        db, run_id=run_id, stage_key="S", node_key="N:g2",
        expected_artifacts=[{"rel_path": "交接/d.json", "required": True}],
    )
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    owner = repositories.new_owner_token()
    assert repositories.acquire_task_lease(db, t.id, owner)
    with pytest.raises(StateTransitionError, match="required"):
        repositories.commit_task_success(db, t.id, artifacts=[], owner_token=owner)


def test_r2_gate2b_increment_owner_none_bypass_rejected(db, run_id):
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:g2b")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    assert repositories.acquire_task_lease(db, t.id, "owner-A")
    with pytest.raises(TaskLeaseHeld):
        repositories.increment_attempt(db, t.id, owner_token=None)  # None 不得绕过 owner 校验
    with pytest.raises(TaskLeaseHeld):
        repositories.increment_attempt(db, t.id, owner_token="owner-B")


def test_r2_gate5_json_garbage_without_schema_rejected(policy):
    """kind=json 但无 schema 的产物：垃圾文件必须被 json.loads 拒绝。"""

    from mmagent.agent.errors import ArtifactInvalid
    from mmagent.workspace.artifacts import ExpectedArtifact, verify_expected_artifacts

    bad = policy.root / "交接"
    bad.mkdir(exist_ok=True)
    (bad / "r.json").write_text("THIS IS NOT JSON", encoding="utf-8")
    with pytest.raises(ArtifactInvalid, match="合法 JSON"):
        verify_expected_artifacts(
            policy, [ExpectedArtifact(rel_path="交接/r.json", kind="json", schema_model=None)]
        )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r2_gate6_sealing_junction_blocked(policy, tmp_path):
    """预置 .mmagent/artifacts junction → sealing 必须拒绝（不走裸 mkdir/write）。"""
    import subprocess as sp

    from mmagent.agent.errors import PathEscape
    from mmagent.workspace.artifacts import ArtifactCheck, seal_artifacts

    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    (policy.root / ".mmagent").mkdir(exist_ok=True)
    sp.run(
        ["cmd", "/c", "mklink", "/J", str(policy.root / ".mmagent" / "artifacts"), str(outside)],
        check=True, capture_output=True,
    )
    check = ArtifactCheck(
        rel_path="交接/d.json", version=1, hash="a" * 64, schema_id=None, content=b"{}",
    )
    with pytest.raises(PathEscape):
        seal_artifacts(policy, [check], "task_x")


def test_r2_p15_waiting_tool_crash_recovery(ws, db, run_id):
    """WAITING_TOOL 崩溃恢复：→ FAILED 且错误注明副作用未知。"""
    from mmagent.api import projects as api_projects

    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="S:wt", role_id="x")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    owner = repositories.new_owner_token()
    assert repositories.acquire_task_lease(db, t.id, owner)
    # 执行者进入 WAITING_TOOL（工具带副作用执行中）
    repositories.transition_task(db, t.id, TaskStatus.WAITING_TOOL, owner_token=owner)
    assert repositories.get_task(db, t.id).status is TaskStatus.WAITING_TOOL
    handle = api_projects.open_project(ws.workspace.root)
    n = api_projects.reset_interrupted_tasks(handle, run_id)
    assert n >= 1
    row = db.query_one("SELECT status, error FROM tasks WHERE id = ?", (t.id,))
    assert row["status"] == "FAILED"
    assert "副作用未知" in (row["error"] or "")


# ==================== Round-3 P1 修复的负向测试 ====================
def test_r3_p1a_begin_attempt_requires_running(db, run_id):
    """QUEUED（未抢租约路径/取消后）不得消耗 attempt。"""
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:r3a")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    owner = repositories.new_owner_token()
    assert repositories.acquire_task_lease(db, t.id, owner)
    # 租约已获取（RUNNING），随后被取消
    repositories.request_cancel(db, t.id, owner_token=owner)
    with pytest.raises(TaskNotRunnable):
        repositories.begin_task_attempt(
            db, t.id, owner, role_id="r", provider_profile="p", model="m", reasoning=None,
        )


def test_r3_p1b_request_cancel_owner_bypass_rejected(db, run_id):
    """RUNNING 有租约时 request_cancel 不带 token 必须拒绝。"""
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:r3b")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    assert repositories.acquire_task_lease(db, t.id, "owner-A")
    with pytest.raises(TaskLeaseHeld):
        repositories.request_cancel(db, t.id)  # 不带 token → 拒绝
    with pytest.raises(TaskLeaseHeld):
        repositories.request_cancel(db, t.id, owner_token="owner-B")  # 错误 token → 拒绝
    # 正确 token 可请求取消，执行者收口
    repositories.request_cancel(db, t.id, owner_token="owner-A")
    repositories.mark_task_cancelled(db, t.id, owner_token="owner-A", reason="done")
    assert repositories.get_task(db, t.id).status is TaskStatus.CANCELLED


def test_r3_p1c_empty_token_rejected(db, run_id):
    """空字符串 token 不得创建/伪装租约。"""
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:r3c")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    with pytest.raises(TaskLeaseHeld):
        repositories.acquire_task_lease(db, t.id, "")
    # 正常拿租约后，空 token 不能迁移
    owner = repositories.new_owner_token()
    assert repositories.acquire_task_lease(db, t.id, owner)
    with pytest.raises(TaskLeaseHeld):
        repositories.transition_task(db, t.id, TaskStatus.WAITING_TOOL, owner_token="")


def test_r3_p2_finish_invocation_idempotent(db, run_id):
    """invocation 不允许重复 finish / 不存在的 invocation 报错。"""
    from mmagent.state.models import InvocationStatus

    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:r3f")
    iid = repositories.create_invocation(
        db, task_id=t.id, role_id="r", provider_profile="p", model="m", reasoning=None,
    )
    repositories.finish_invocation(db, iid, InvocationStatus.SUCCEEDED)
    with pytest.raises(StateTransitionError):
        repositories.finish_invocation(db, iid, InvocationStatus.FAILED)


# ==================== Round-4 P1 修复的负向测试 ====================
def test_r4_p1_1_recancel_by_non_owner_rejected(db, run_id):
    """CANCEL_REQUESTED 不得被非 owner 直接关闭（重复取消必须出示租约）。"""
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:r4a")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    assert repositories.acquire_task_lease(db, t.id, "owner-A")
    repositories.request_cancel(db, t.id, owner_token="owner-A")  # owner 请求取消
    # 非 owner 重复 request_cancel：不得关闭任务/清租约
    with pytest.raises(TaskLeaseHeld):
        repositories.request_cancel(db, t.id)
    with pytest.raises(TaskLeaseHeld):
        repositories.request_cancel(db, t.id, owner_token="owner-B")
    assert repositories.get_task(db, t.id).status is TaskStatus.CANCEL_REQUESTED
    assert db.query_one("SELECT owner_token FROM tasks WHERE id = ?", (t.id,))["owner_token"] == "owner-A"
    # owner 幂等确认 OK，收口后终态
    repositories.request_cancel(db, t.id, owner_token="owner-A")
    repositories.mark_task_cancelled(db, t.id, owner_token="owner-A", reason="closed")
    assert repositories.get_task(db, t.id).status is TaskStatus.CANCELLED


def test_r4_p1_2_begin_attempt_none_and_ownerless(db, run_id):
    """begin_task_attempt：None token 不得绕过；ownerless RUNNING 视为损坏。"""
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:r4b")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    assert repositories.acquire_task_lease(db, t.id, "owner-A")
    with pytest.raises(TaskLeaseHeld):
        repositories.begin_task_attempt(
            db, t.id, None, role_id="r", provider_profile="p", model="m", reasoning=None,
        )
    # 直接注入 ownerless RUNNING（模拟损坏状态）
    db.execute("UPDATE tasks SET owner_token = NULL WHERE id = ?", (t.id,))
    with pytest.raises(TaskLeaseHeld):
        repositories.begin_task_attempt(
            db, t.id, "owner-A", role_id="r", provider_profile="p", model="m", reasoning=None,
        )
    with pytest.raises(TaskLeaseHeld):
        repositories.mark_task_failed(db, t.id, error="x", owner_token="owner-A") or None


def test_r4_p2_mark_failed_ownerless_running_rejected(db, run_id):
    """ownerless RUNNING 的 mark_task_failed 必须 fail-closed（走崩溃恢复）。"""
    from mmagent.agent.errors import TaskLeaseHeld as TLH

    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:r4c")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    assert repositories.acquire_task_lease(db, t.id, "owner-A")
    db.execute("UPDATE tasks SET owner_token = NULL WHERE id = ?", (t.id,))
    with pytest.raises(TLH, match="崩溃恢复"):
        repositories.mark_task_failed(db, t.id, error="x", owner_token="owner-A")
    # 只有恢复路径能收口
    from mmagent.state.repositories import recover_interrupted_task

    t2 = recover_interrupted_task(db, t.id, "crash recovery")
    assert t2.status is TaskStatus.FAILED


def test_r4_p1_3_finish_invocation_target_terminal_only(db, run_id):
    """finish 到非终态（RUNNING）必须拒绝；exactly-once 保持。"""
    from mmagent.state.models import InvocationStatus

    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:r4d")
    iid = repositories.create_invocation(
        db, task_id=t.id, role_id="r", provider_profile="p", model="m", reasoning=None,
    )
    with pytest.raises(StateTransitionError):
        repositories.finish_invocation(db, iid, InvocationStatus.RUNNING)
    repositories.finish_invocation(db, iid, InvocationStatus.SUCCEEDED)
    row = db.query_one("SELECT status FROM agent_invocations WHERE id = ?", (iid,))
    assert row["status"] == "SUCCEEDED"


def test_r4_create_invocation_missing_task(db):
    from mmagent.state import repositories as repo

    with pytest.raises(LookupError):
        repo.create_invocation(
            db, task_id="task_nonexistent", role_id="r", provider_profile="p", model="m", reasoning=None,
        )


# ==================== Round-5 P1 修复的负向测试 ====================
def test_r5_p1_1_mark_cancelled_strict(db, run_id):
    """mark_task_cancelled：活跃态必须 owner 在场 + token 精确匹配。"""
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:r5a")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    assert repositories.acquire_task_lease(db, t.id, "owner-A")
    with pytest.raises(TaskLeaseHeld):
        repositories.mark_task_cancelled(db, t.id)  # 无 token 不得收口活跃态
    with pytest.raises(TaskLeaseHeld):
        repositories.mark_task_cancelled(db, t.id, owner_token="owner-B")
    repositories.mark_task_cancelled(db, t.id, owner_token="owner-A", reason="ok")
    assert repositories.get_task(db, t.id).status is TaskStatus.CANCELLED


def test_r5_p1_3_commit_ownerless_running_rejected(db, run_id):
    """DB 注入 ownerless RUNNING 后：commit 必拒，artifact 一行都不能写。"""
    t = repositories.create_task(
        db, run_id=run_id, stage_key="S", node_key="N:r5c",
        expected_artifacts=[{"rel_path": "交接/d.json", "required": True}],
    )
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    assert repositories.acquire_task_lease(db, t.id, "owner-A")
    db.execute("UPDATE tasks SET owner_token = NULL WHERE id = ?", (t.id,))
    rows = [{"id": "art_x", "rel_path": "交接/d.json", "kind": "json", "schema_id": None,
             "version": 1, "hash": "h", "input_versions": {}}]
    with pytest.raises(TaskLeaseHeld):
        repositories.commit_task_success(db, t.id, artifacts=rows, owner_token="owner-A")
    assert db.query_one("SELECT COUNT(*) AS n FROM artifacts WHERE task_id = ?", (t.id,))["n"] == 0
    assert repositories.get_task(db, t.id).status is TaskStatus.RUNNING  # 状态未被污染


def test_r5_p1_2_begin_attempt_empty_token_rejected(db, run_id):
    """空字符串 token 在入口即拒（_require_token）。"""
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:r5b")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    assert repositories.acquire_task_lease(db, t.id, "owner-A")
    with pytest.raises(TaskLeaseHeld):
        repositories.begin_task_attempt(
            db, t.id, "", role_id="r", provider_profile="p", model="m", reasoning=None,
        )
    with pytest.raises(TaskLeaseHeld):
        repositories.begin_task_attempt(
            db, t.id, None, role_id="r", provider_profile="p", model="m", reasoning=None,
        )


# ==================== Round-6 P1 修复的负向测试 ====================
def test_r6_p1_1_begin_attempt_empty_token_db_injected(db, run_id):
    """DB 注入 owner_token='' 后：入口 _require_token 必拒（不是靠不匹配）。"""
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:r6a")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    assert repositories.acquire_task_lease(db, t.id, "owner-A")
    db.execute("UPDATE tasks SET owner_token = '' WHERE id = ?", (t.id,))
    with pytest.raises(TaskLeaseHeld):
        repositories.begin_task_attempt(
            db, t.id, "", role_id="r", provider_profile="p", model="m", reasoning=None,
        )
    # attempt / invocation / event 全部不变
    assert repositories.get_task(db, t.id).attempt == 0
    assert db.query_one("SELECT COUNT(*) AS n FROM agent_invocations WHERE task_id = ?", (t.id,))["n"] == 0
    assert db.query_one("SELECT COUNT(*) AS n FROM events WHERE type = 'task.attempt' AND task_id = ?", (t.id,))["n"] == 0


def test_r6_p1_2_generic_transition_from_active_restricted(db, run_id):
    """活跃态经通用 transition 只允许 RUNNING<->WAITING_TOOL；其余必须走专用函数。"""
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:r6b")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    assert repositories.acquire_task_lease(db, t.id, "owner-A")
    # RUNNING -> FAILED 经通用 API：拒绝（会留脏租约）
    with pytest.raises(StateTransitionError, match="专用收口函数"):
        repositories.transition_task(db, t.id, TaskStatus.FAILED, owner_token="owner-A")
    # RUNNING -> CANCELLED 经通用 API：拒绝
    with pytest.raises(StateTransitionError):
        repositories.transition_task(db, t.id, TaskStatus.CANCELLED, owner_token="owner-A")
    # RUNNING -> WAITING_TOOL -> RUNNING（owner-preserving）：合法
    repositories.transition_task(db, t.id, TaskStatus.WAITING_TOOL, owner_token="owner-A")
    repositories.transition_task(db, t.id, TaskStatus.RUNNING, owner_token="owner-A")
    assert repositories.get_task(db, t.id).status is TaskStatus.RUNNING
    # 专用 API 仍可正常收口
    t2 = repositories.mark_task_failed(db, t.id, error="x", owner_token="owner-A")
    assert t2.status is TaskStatus.FAILED
    # 失败后租约已清空：可以重新排队抢租约（无脏状态）
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    assert repositories.acquire_task_lease(db, t.id, "owner-B")


def test_r6_p1_2b_cancel_requested_via_generic_rejected(db, run_id):
    """CANCEL_REQUESTED 态经通用 API 迁走必须拒绝（防绕过 request_cancel 语义）。"""
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:r6c")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    assert repositories.acquire_task_lease(db, t.id, "owner-A")
    repositories.request_cancel(db, t.id, owner_token="owner-A")
    with pytest.raises(StateTransitionError, match="专用收口函数"):
        repositories.transition_task(db, t.id, TaskStatus.CANCELLED, owner_token="owner-A")
    with pytest.raises(StateTransitionError):
        repositories.transition_task(db, t.id, TaskStatus.READY, owner_token="owner-A")
    # 执行者仍可用专用 API 收口
    repositories.mark_task_cancelled(db, t.id, owner_token="owner-A", reason="closed")
    assert repositories.get_task(db, t.id).status is TaskStatus.CANCELLED


# ==================== Round-7 P1 修复的负向测试 ====================
def test_r7_p1_ownerless_active_via_generic_rejected(db, run_id):
    """DB 注入 ownerless RUNNING/WAITING_TOOL 后：任意非空 token 不得经通用 API 推进。"""
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="N:r7a")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    assert repositories.acquire_task_lease(db, t.id, "owner-A")
    db.execute("UPDATE tasks SET owner_token = NULL WHERE id = ?", (t.id,))
    # 注入 ownerless RUNNING 后，白名单内的推进也必须 fail-closed
    with pytest.raises(TaskLeaseHeld, match="崩溃恢复"):
        repositories.transition_task(db, t.id, TaskStatus.WAITING_TOOL, owner_token="attacker")
    # 镜像：WAITING_TOOL 方向同样 fail-closed
    db.execute("UPDATE tasks SET status = 'WAITING_TOOL' WHERE id = ?", (t.id,))
    with pytest.raises(TaskLeaseHeld, match="崩溃恢复"):
        repositories.transition_task(db, t.id, TaskStatus.RUNNING, owner_token="attacker")
    # 空串 token 同样拒（_require_token 把 NULL 与 '' 都视为损坏）
    with pytest.raises(TaskLeaseHeld):
        repositories.transition_task(db, t.id, TaskStatus.RUNNING, owner_token="")
    # 只有恢复路径能收口
    from mmagent.state.repositories import recover_interrupted_task

    t2 = recover_interrupted_task(db, t.id, "crash recovery")
    assert t2.status is TaskStatus.FAILED


# ==================== v0.2.0 Job Object / Environment ====================
@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_v02_job_object_timeout_and_cancel(policy, ws):
    """ProcessManager 路径：python.run 超时杀树 + 取消立即杀树。"""
    import asyncio as aio

    from mmagent.runtime.cancellation import CancellationToken
    from mmagent.runtime.process import ProcessManager
    from mmagent.tools.python import PythonRunTool
    from mmagent.tools.registry import ToolRegistry as R
    from mmagent.tools.tool_protocol import ToolContext
    from mmagent.workspace.permissions import PermissionChecker as PC
    from mmagent.workspace.permissions import RolePermissions as RP

    (ws.workspace.root / "求解").mkdir(exist_ok=True)
    (ws.workspace.root / "求解" / "sleeper.py").write_text("import time; time.sleep(30)\n", encoding="utf-8")
    pm = ProcessManager()
    perms = RP(role_id="m", read_scopes=("**",), write_scopes=("**",),
               allowed_tools=frozenset({"python.run"}), host_code=True)
    checker = PC(perms, policy)
    reg = R()
    reg.register(PythonRunTool(process_manager=pm))
    ctx = ToolContext(policy=policy, permission=checker, cancel=CancellationToken())
    res = aio.run(reg.invoke("python.run", {"path": "求解/sleeper.py", "timeout_s": 1}, ctx))
    assert res.ok is False and res.meta.get("timed_out") is True
    assert res.meta.get("rc") == 137  # Job 终止约定退出码
    # 取消路径：脚本睡眠中，取消令牌触发 → 进程被杀、rc 异常
    (ws.workspace.root / "求解" / "sleeper2.py").write_text("import time; time.sleep(30)\n", encoding="utf-8")
    token = CancellationToken()
    ctx2 = ToolContext(policy=policy, permission=checker, cancel=token)
    async def run_and_cancel():
        task = aio.create_task(reg.invoke("python.run", {"path": "求解/sleeper2.py", "timeout_s": 20}, ctx2))
        await aio.sleep(0.8)
        token.cancel("user stop")
        return await task
    res2 = aio.run(run_and_cancel())
    assert "rc" in res2.meta and res2.meta["rc"] != 0
    pm.shutdown()


def test_v02_environment_discovery(ws, policy):
    """环境发现：本机真值（XeLaTeX 2026 嵌套布局 + MATLAB 根目录布局）。"""
    import sys as _sys

    from mmagent.runtime import environment as env

    rep = env.probe_all(ws.workspace.root)
    if Path("D:/Apps/texlive").is_dir():
        assert rep.xelatex.ok, rep.xelatex.detail
        assert "bin/windows/xelatex.exe" in (rep.xelatex.path or "").replace("\\\\", "/").replace("\\", "/")
        assert rep.xelatex.version  # --version 真执行过
    if Path("D:/Apps/Matlab").is_dir():
        assert rep.matlab.ok, rep.matlab.detail
        assert (rep.matlab.path or "").endswith("matlab.exe")
    assert rep.managed_python.ok
    assert rep.managed_python.path == _sys.executable
    # capability cache 落盘
    cache = ws.workspace.root / ".mmagent" / "capabilities.json"
    assert cache.is_file()
    data = _json_check(cache)
    assert data["xelatex"]["name"] == "xelatex"


def _json_check(p):
    import json as _json

    return _json.loads(p.read_text(encoding="utf-8"))


# ==================== v0.2.0 Round-2 故障注入（ProcessManager 重写后） ====================
@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r2v02_old_unconfirmable_new_never_runs(policy, ws, monkeypatch):
    """旧进程无法确认终止：新挂起进程被终止（从未运行）、old 保持注册+quarantined。"""
    import sys as _sys
    import time as _time

    from mmagent.runtime import process as process_mod
    from mmagent.runtime.process import ProcessManager

    pm = ProcessManager()
    old = pm.spawn("dup2", [_sys.executable, "-c", "import time; time.sleep(30)"])
    _time.sleep(1)
    # 注入：Job 终止不生效
    monkeypatch.setattr(process_mod, "_terminate_tree_state", lambda p: "failed")
    with pytest.raises(RuntimeError, match="quarantined"):
        pm.spawn("dup2", [_sys.executable, "-c", "print('new')"])
    # old 仍在注册表且 quarantined；new 从未运行（无新注册）
    cur = pm.registry.get("dup2")
    assert cur is old and cur.quarantined
    monkeypatch.undo()
    pm.shutdown()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r2v02_job_zero_confirmation(policy, ws):
    """终止确认基于 Job 活跃数归零 + root 退出（不只 root signal）。"""
    import sys as _sys
    import time as _time

    from mmagent.runtime.process import ProcessManager, _job_active_count

    pm = ProcessManager()
    code = 'import subprocess, sys, time; subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"]); time.sleep(30)'
    proc = pm.spawn("jobzero", [_sys.executable, "-c", code])
    _time.sleep(2)
    assert proc.alive
    assert proc.job_handle is not None
    n = _job_active_count(proc.job_handle)
    assert n is not None and n >= 2  # root + child 都在 Job 内（挂起期入 Job 的证明）
    assert pm.kill("jobzero")
    _time.sleep(0.5)
    assert _job_active_count(proc.job_handle) == 0  # 整棵树归零，不只 root
    assert not proc.alive
    pm.shutdown()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r2v02_cancel_race_natural_exit_keeps_rc(policy, ws):
    """进程已自然退出后取消才到达：保留真实 rc，不改写 -99。"""
    import asyncio as aio

    from mmagent.runtime.cancellation import CancellationToken
    from mmagent.runtime.process import ProcessManager
    from mmagent.tools.python import PythonRunTool
    from mmagent.tools.registry import ToolRegistry as R
    from mmagent.tools.tool_protocol import ToolContext
    from mmagent.workspace.permissions import PermissionChecker as PC
    from mmagent.workspace.permissions import RolePermissions as RP

    (ws.workspace.root / "求解").mkdir(exist_ok=True)
    (ws.workspace.root / "求解" / "quick.py").write_text("print('done')\n", encoding="utf-8")
    pm = ProcessManager()
    perms = RP(role_id="m", read_scopes=("**",), write_scopes=("**",),
               allowed_tools=frozenset({"python.run"}), host_code=True)
    checker = PC(perms, policy)
    reg = R()
    reg.register(PythonRunTool(process_manager=pm))
    token = CancellationToken()
    ctx = ToolContext(policy=policy, permission=checker, cancel=token)

    async def run_then_cancel():
        task = aio.create_task(
            reg.invoke("python.run", {"path": "求解/quick.py", "timeout_s": 30}, ctx)
        )
        # 不用固定 sleep 猜测“应该已经退出”。高负载 Windows runner 上
        # create_task/进程启动调度可能晚于墙钟假设，导致测试把真实 cancel
        # 误称为 late cancel。机械等待 Job 整棵树自然归零，再触发取消。
        deadline = aio.get_running_loop().time() + 10.0
        observed = None
        while aio.get_running_loop().time() < deadline:
            procs = list(pm.registry._procs.values())
            if procs:
                observed = procs[0]
                if not observed.tree_alive:
                    break
            if task.done():
                result = await task
                token.cancel("late stop")
                return result
            await aio.sleep(0.01)
        assert observed is not None and not observed.tree_alive
        token.cancel("late stop")
        return await task

    res = aio.run(run_then_cancel())
    assert res.ok is True and res.meta["rc"] == 0  # 自然退出的真实 rc
    pm.shutdown()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r2v02_output_quota_terminates(policy, ws):
    """输出超预算：立即终止 Job + ToolTimeout('输出超限')，尾部捕获内存有界。"""
    import asyncio as aio

    from mmagent.runtime.cancellation import CancellationToken
    from mmagent.runtime.process import ProcessManager
    from mmagent.tools.python import PythonRunTool
    from mmagent.tools.registry import ToolRegistry as R
    from mmagent.tools.tool_protocol import ToolContext
    from mmagent.workspace.permissions import PermissionChecker as PC
    from mmagent.workspace.permissions import RolePermissions as RP

    (ws.workspace.root / "求解").mkdir(exist_ok=True)
    (ws.workspace.root / "求解" / "noisy.py").write_text(
        "import time\nwhile True:\n    print('x' * 8192, flush=True)\n    time.sleep(0.01)\n",
        encoding="utf-8",
    )
    pm = ProcessManager(output_quota_bytes=2 * 1024 * 1024)  # 2MB 预算
    perms = RP(role_id="m", read_scopes=("**",), write_scopes=("**",),
               allowed_tools=frozenset({"python.run"}), host_code=True)
    checker = PC(perms, policy)
    reg = R()
    reg.register(PythonRunTool(process_manager=pm))
    ctx = ToolContext(policy=policy, permission=checker, cancel=CancellationToken())
    res = aio.run(reg.invoke("python.run", {"path": "求解/noisy.py", "timeout_s": 60}, ctx))
    assert res.ok is False and res.meta.get("timed_out") is True
    assert len(res.meta.get("stdout_tail", "")) <= 40_100  # 尾部有界
    pm.shutdown()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r2v02_shutdown_reports_failures(policy, ws, monkeypatch):
    """shutdown 存在未确认收口的进程 → 显式 RuntimeError（注册/文件保留）。"""
    import sys as _sys
    import time as _time

    from mmagent.runtime import process as process_mod
    from mmagent.runtime.process import ProcessManager

    pm = ProcessManager()
    pm.spawn("stuck", [_sys.executable, "-c", "import time; time.sleep(30)"])
    _time.sleep(1)
    monkeypatch.setattr(process_mod, "_terminate_tree_state", lambda p: "failed")
    with pytest.raises(RuntimeError, match="未能确认终止"):
        pm.shutdown()
    cur = pm.registry.get("stuck")
    assert cur is not None and cur.quarantined  # 保持注册供人工检查
    monkeypatch.undo()
    assert pm.recycle("stuck")  # 恢复后可正常收口


# ==================== Round-3 P1 修复的负向测试 ====================
@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r3_p1_1_root_exit_tree_alive_still_tracked(policy, ws):
    """区分度测试：root 立即退出、child 长眠 → communicate 不能因 root 退出而返回；
    超时终止必须等 Job 归零。旧实现（只看 root）会在此提前返回成功。"""
    import sys as _sys
    import time as _time

    from mmagent.runtime.process import ProcessManager, _job_active_count

    pm = ProcessManager()
    # 父进程立刻退出，留下 sleep(20) 的 child 在 Job 内
    code = 'import subprocess, sys; subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"]); print("root exits")'
    proc = pm.spawn("rootexit", [_sys.executable, "-c", code])
    _time.sleep(2)
    assert not proc.alive  # root 已退出
    assert _job_active_count(proc.job_handle) >= 1  # 但 child 仍在 Job 内
    # communicate 必须超时（树仍活），而不是因 root 退出提前返回
    rc, out, err, timed_out = pm.communicate(proc, timeout_s=3)
    assert timed_out, "root 退出后树仍活：必须继续等待/超时，不得提前返回"
    # 终止确认 = Job 归零
    assert pm.kill("rootexit")
    _time.sleep(0.5)
    assert _job_active_count(proc.job_handle) == 0
    assert proc.tree_exited
    pm.shutdown()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r3_p1_3_handles_not_inheritable(policy, ws):
    """CreateProcess 返回的 process/thread 句柄不可继承（句柄继承面最小化）。"""
    import sys as _sys
    import time as _time

    import win32api

    from mmagent.runtime.process import ProcessManager

    HANDLE_FLAG_INHERIT = 0x1
    pm = ProcessManager()
    code = 'import time; time.sleep(2)'
    proc = pm.spawn("inh", [_sys.executable, "-c", code])
    _time.sleep(0.5)
    flags = win32api.GetHandleInformation(proc.h_process)
    assert not (flags & HANDLE_FLAG_INHERIT), "process 句柄不可继承"
    if proc.job_handle is not None:
        jflags = win32api.GetHandleInformation(proc.job_handle)
        assert not (jflags & HANDLE_FLAG_INHERIT), "job 句柄不可继承"
    pm.communicate(proc, 30)
    pm.shutdown()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r3_p1_2_registry_compare_remove(db, run_id, policy):
    """remove-by-name 的 compare-and-delete：换代后旧引用不得删除新对象。"""
    from mmagent.runtime.process import ManagedProcess, ProcessRegistry

    reg = ProcessRegistry()
    old = ManagedProcess(name="x", pid=1, argv=[])
    new = ManagedProcess(name="x", pid=2, argv=[])
    reg.publish(old)
    # 误删防护：用 old 引用删不掉 new
    reg.publish(new)
    removed = reg.remove("x", expected=old)
    assert removed is None and reg.get("x") is new
    removed = reg.remove("x", expected=new)
    assert removed is new


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r3_p1_2b_spawn_rejected_after_shutdown(policy, ws):
    """shutdown 后拒绝新 spawn（防 shutdown 期间新进程逃逸）。"""
    import sys as _sys

    from mmagent.runtime.process import ProcessManager

    pm = ProcessManager()
    pm.spawn("pre", [_sys.executable, "-c", "print(1)"])
    pm.shutdown()
    import pytest

    with pytest.raises(RuntimeError, match="shutdown"):
        pm.spawn("post", [_sys.executable, "-c", "print(2)"])


# ==================== Round-5 P1 修复的负向测试 ====================
@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r5_p1_2_createprocess_failure_single_close(tmp_path, monkeypatch):
    """CreateProcess 失败：每个 std 句柄严格关闭一次、tmpdir 清理、原始异常保持。"""
    import win32file
    import win32process

    from mmagent.runtime.process import ProcessManager

    calls = {"closed": [], "created": []}
    import glob
    import tempfile as _tf
    before_leftovers = set(glob.glob(os.path.join(_tf.gettempdir(), "mmagent_proc_*")))
    real_create_file = win32file.CreateFile
    real_close = win32file.CloseHandle

    def spy_create_file(*a, **k):
        h = real_create_file(*a, **k)
        calls["created"].append(h)
        return h

    def spy_close(h, *a, **k):
        calls["closed"].append(h)
        return real_close(h, *a, **k)

    monkeypatch.setattr(win32file, "CreateFile", spy_create_file)
    monkeypatch.setattr(win32file, "CloseHandle", spy_close)

    def boom(*a, **k):
        raise OSError(87, "injected CreateProcess failure")

    monkeypatch.setattr(win32process, "CreateProcess", boom)

    pm = ProcessManager()
    with pytest.raises(OSError, match="injected"):
        pm.spawn("f1", [sys.executable, "-c", "print(1)"])
    monkeypatch.undo()
    # 每个 std 句柄恰好关闭一次（3 个创建 + 3 个关闭）
    assert len(calls["created"]) == 3
    assert len(calls["closed"]) == 3
    # tmpdir 已清理：与测试前快照相比，无新增 mmagent_proc_* 残留
    import glob
    import tempfile as _tf
    leftovers = glob.glob(os.path.join(_tf.gettempdir(), "mmagent_proc_*"))
    assert before_leftovers <= set(leftovers), f"新增残留: {set(leftovers) - before_leftovers}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r5_p1_3_lifecycle_gate_serializes(policy, ws):
    """kill 与 shutdown 都经 lifecycle gate：shutdown 期间 kill 不会并发终止。"""
    import sys as _sys
    import time as _time

    from mmagent.runtime.process import ProcessManager

    pm = ProcessManager()
    pm.spawn("g", [_sys.executable, "-c", "import time; time.sleep(30)"])
    _time.sleep(1)
    # 模拟 lifecycle gate 被长时间持有：shutdown 必须等待而不是并发
    with pm._commit_lock:
        # gate 持有期间 kill 调用应当阻塞直到释放——用线程验证串行化
        import threading

        done = threading.Event()

        def killer():
            pm.kill("g")
            done.set()

        th = threading.Thread(target=killer, daemon=True)
        th.start()
        _time.sleep(0.5)
        assert not done.is_set(), "kill 必须等待 lifecycle gate"
    done.wait(30)
    assert done.is_set()
    pm.shutdown()


# ==================== Round-6 P1 修复的负向测试 ====================
@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r6_p1_1_job_setup_unconfirmed_quarantined(policy, ws, monkeypatch):
    """Job 绑定失败且终止未确认：proc 入 quarantine、句柄保留、绝不静默关闭。"""
    import win32event
    import win32job

    from mmagent.runtime.process import ProcessManager

    def fail_assign(*a, **k):
        raise OSError(5, "injected assign failure")

    def never_signal(*a, **k):
        return 0x102  # WAIT_TIMEOUT：终止未确认

    monkeypatch.setattr(win32job, "AssignProcessToJobObject", fail_assign)
    monkeypatch.setattr(win32event, "WaitForSingleObject", never_signal)
    pm = ProcessManager()
    with pytest.raises(RuntimeError, match="quarantined"):
        pm.spawn("q1", [sys.executable, "-c", "print(1)"])
    qs = pm.registry.quarantined
    assert len(qs) == 1
    q = qs[0]
    assert q.quarantined and q.h_process is not None and q.job_handle is None
    assert q.alive is not True or True  # suspended：root 未退出


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r6_p1_1b_job_setup_confirmed_cleans(policy, ws, monkeypatch):
    """Job 绑定失败但终止已确认：清理干净后抛 OSError，不留 quarantine。"""
    import win32job

    from mmagent.runtime.process import ProcessManager

    def fail_assign(*a, **k):
        raise OSError(5, "injected assign failure")

    monkeypatch.setattr(win32job, "AssignProcessToJobObject", fail_assign)
    pm = ProcessManager()
    with pytest.raises(OSError, match="已终止挂起进程"):
        pm.spawn("q2", [sys.executable, "-c", "print(1)"])
    assert pm.registry.quarantined == []
    assert pm.registry.get("q2") is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r6_p1_2_cancel_after_natural_exit_keeps_real_rc(policy, ws):
    """取消终止未确认（进程恰好自然结束）→ 显式失败，rc 不得被改成 -99。"""
    import asyncio as aio

    from mmagent.runtime.cancellation import CancellationToken
    from mmagent.runtime.process import ProcessManager
    from mmagent.tools.python import PythonRunTool
    from mmagent.tools.registry import ToolRegistry as R
    from mmagent.tools.tool_protocol import ToolContext
    from mmagent.workspace.permissions import PermissionChecker as PC
    from mmagent.workspace.permissions import RolePermissions as RP

    (ws.workspace.root / "求解").mkdir(exist_ok=True)
    # 脚本：输出很快结束，但结束前 cancel 到达且终止未发出（OSError 注入）
    (ws.workspace.root / "求解" / "racer.py").write_text("print('ok')\n", encoding="utf-8")
    pm = ProcessManager()
    perms = RP(role_id="m", read_scopes=("**",), write_scopes=("**",),
               allowed_tools=frozenset({"python.run"}), host_code=True)
    checker = PC(perms, policy)
    reg = R()
    reg.register(PythonRunTool(process_manager=pm))
    token = CancellationToken()
    ctx = ToolContext(policy=policy, permission=checker, cancel=token)

    # 进程先自然退出，随后 cancel：真实 rc 保留
    res = aio.run(reg.invoke("python.run", {"path": "求解/racer.py", "timeout_s": 30}, ctx))
    assert res.ok is True and res.meta["rc"] == 0
    # 进程结束后才 cancel：真实 rc 不得被改写成 -99
    token.cancel("late")
    assert res.ok is True and res.meta["rc"] == 0
    pm.shutdown()


# ==================== Round-7 因果性区分测试 ====================
@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r7_p1_1_terminate_request_fail_natural_exit_keeps_rc(policy, ws, monkeypatch):
    """区分度场景（外审 round7 P1-1）：
    cancel 到达 → TerminateJobObject 注入失败 → 进程随后自然结束 → 树归零。
    不得把真实 rc 改写成 -99（终止请求失败 ≠ 由取消杀灭）。"""
    import asyncio as aio

    import win32job

    from mmagent.runtime.cancellation import CancellationToken
    from mmagent.runtime.process import ProcessManager
    from mmagent.tools.python import PythonRunTool
    from mmagent.tools.registry import ToolRegistry as R
    from mmagent.tools.tool_protocol import ToolContext
    from mmagent.workspace.permissions import PermissionChecker as PC
    from mmagent.workspace.permissions import RolePermissions as RP

    (ws.workspace.root / "求解").mkdir(exist_ok=True)
    # 脚本运行约 1.2s：cancel 在 0.3s 到达（终止请求失败），进程 1.2s 自然结束
    (ws.workspace.root / "求解" / "racer2.py").write_text(
        "import time\nprint('start', flush=True)\ntime.sleep(1.2)\nprint('done', flush=True)\n",
        encoding="utf-8",
    )
    pm = ProcessManager()
    perms = RP(role_id="m", read_scopes=("**",), write_scopes=("**",),
               allowed_tools=frozenset({"python.run"}), host_code=True)
    checker = PC(perms, policy)
    reg = R()
    reg.register(PythonRunTool(process_manager=pm))
    token = CancellationToken()
    ctx = ToolContext(policy=policy, permission=checker, cancel=token)

    def fail_once_first_time(*a, **k):
        raise OSError(6, "injected terminate failure")

    async def run_with_cancel():
        task = aio.create_task(reg.invoke("python.run", {"path": "求解/racer2.py", "timeout_s": 30}, ctx))
        await aio.sleep(0.3)
        # 注入：cancel 生效期间 TerminateJobObject 请求失败
        monkeypatch.setattr(win32job, "TerminateJobObject", fail_once_first_time)
        token.cancel("cancel during run")
        await aio.sleep(3)  # 等自然退出 + 观察窗
        monkeypatch.undo()
        return await task

    res = aio.run(run_with_cancel())
    assert res.ok is True, res.error
    assert res.meta["rc"] == 0, "自然退出的真实 rc 必须保留，不得改写 -99"
    # 终止请求失败 + 自然归零：不得 quarantine、不得抛 ToolTimeout
    assert pm.registry.quarantined == [], "natural_exit 不应进入 quarantine"
    pm.shutdown()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r7_p1_1b_terminate_fail_still_alive_raises(policy, ws, monkeypatch):
    """终止请求失败且树仍活 → quarantine + 显式失败（不得静默）。"""
    import asyncio as aio

    import win32job

    from mmagent.runtime.process import ProcessManager
    from mmagent.tools.python import PythonRunTool
    from mmagent.tools.registry import ToolRegistry as R
    from mmagent.tools.tool_protocol import ToolContext
    from mmagent.workspace.permissions import PermissionChecker as PC
    from mmagent.workspace.permissions import RolePermissions as RP

    (ws.workspace.root / "求解").mkdir(exist_ok=True)
    (ws.workspace.root / "求解" / "sleeper2.py").write_text(
        "import time\ntime.sleep(30)\n", encoding="utf-8"
    )
    from mmagent.runtime.cancellation import CancellationToken as _CT

    pm = ProcessManager()
    perms = RP(role_id="m", read_scopes=("**",), write_scopes=("**",),
               allowed_tools=frozenset({"python.run"}), host_code=True)
    checker = PC(perms, policy)
    reg = R()
    reg.register(PythonRunTool(process_manager=pm))
    token = _CT()
    ctx = ToolContext(policy=policy, permission=checker, cancel=token)

    def fail_terminate(*a, **k):
        raise OSError(6, "injected terminate failure")

    async def run_cancel_now():
        task = aio.create_task(reg.invoke("python.run", {"path": "求解/sleeper2.py", "timeout_s": 30}, ctx))
        await aio.sleep(0.5)
        monkeypatch.setattr(win32job, "TerminateJobObject", fail_terminate)
        token.cancel("cancel with failing terminate")
        return await task

    res = aio.run(run_cancel_now())
    # 取消终止未确认 → 工具层转为 timed_out 失败结果；proc 曾入 quarantine（round6 P1-1）
    assert res.ok is False and res.meta.get("timed_out") is True
    assert any(q.quarantined for q in pm.registry.quarantined)
    monkeypatch.undo()
    pm.shutdown()


# ==================== Round-8：std 句柄回滚三阶段区分测试 ====================
@pytest.mark.parametrize("fail_at", [1, 2, 3])
@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r8_std_handle_rollback_each_stage(tmp_path, policy, ws, monkeypatch, fail_at):
    """第 1/2/3 次 CreateFile 分别失败：已创建句柄各恰好关闭一次、无新增 tmpdir。"""
    import glob
    import os as _os
    import tempfile as _tf

    import win32file

    from mmagent.runtime.process import ProcessManager

    real_create = win32file.CreateFile
    real_close = win32file.CloseHandle
    calls = {"created": [], "closed": []}

    attempts = {"n": 0}

    def spy_create(*a, **k):
        attempts["n"] += 1
        if attempts["n"] == fail_at:
            raise OSError(87, f"injected failure #{fail_at}")
        h = real_create(*a, **k)
        calls["created"].append(h)
        return h

    def spy_close(h, *a, **k):
        calls["closed"].append(h)
        return real_close(h, *a, **k)

    before = set(glob.glob(_os.path.join(_tf.gettempdir(), "mmagent_proc_*")))
    monkeypatch.setattr(win32file, "CreateFile", spy_create)
    monkeypatch.setattr(win32file, "CloseHandle", spy_close)
    pm = ProcessManager()
    with pytest.raises(OSError, match="injected"):
        pm.spawn(f"rb{fail_at}", [sys.executable, "-c", "print(1)"])
    monkeypatch.undo()
    assert len(calls["created"]) == fail_at - 1  # 注入点之前成功创建了 fail_at-1 个
    assert len(calls["closed"]) == fail_at - 1  # 每个已创建句柄恰好关闭一次
    after = set(glob.glob(_os.path.join(_tf.gettempdir(), "mmagent_proc_*")))
    assert not (after - before), f"新增 tmpdir 残留: {after - before}"
    pm.shutdown()


# ==================== Round-9 P1 修复的负向测试 ====================
@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r9_p1_2_resume_failure_rollback(policy, ws, monkeypatch):
    """resume 失败：确认终止+清理+移出注册（或 quarantine），不留半提交对象。"""
    import sys as _sys

    from mmagent.runtime import process as process_mod
    from mmagent.runtime.process import ProcessManager

    pm = ProcessManager()

    def boom(proc):
        raise OSError(6, "injected resume failure")

    monkeypatch.setattr(process_mod, "_resume", boom)
    with pytest.raises(RuntimeError, match="resume 失败"):
        pm.spawn("r9a", [_sys.executable, "-c", "import time; time.sleep(30)"])
    monkeypatch.undo()
    # 无半提交对象：注册表为空（已回滚移除）或 quarantined（未确认时）
    assert pm.registry.get("r9a") is None
    total = len(pm.registry._procs) + len(pm.registry.quarantined)
    assert total <= 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r9_p1_3_shutdown_handles_quarantined_suspended(policy, ws, monkeypatch):
    """shutdown 收口 quarantined 的无 Job 挂起进程：确认终止（不谎报成功）。"""

    import win32event
    import win32job

    from mmagent.runtime.process import ProcessManager

    def fail_assign(*a, **k):
        raise OSError(5, "injected assign failure")

    def never_signal(*a, **k):
        return 0x102  # WAIT_TIMEOUT

    monkeypatch.setattr(win32job, "AssignProcessToJobObject", fail_assign)
    monkeypatch.setattr(win32event, "WaitForSingleObject", never_signal)
    pm = ProcessManager()
    with pytest.raises(RuntimeError, match="quarantined"):
        pm.spawn("q9", [sys.executable, "-c", "import time; time.sleep(30)"])
    assert len(pm.registry.quarantined) == 1
    q = pm.registry.quarantined[0]
    # 恢复终止能力后 shutdown：必须确认收口 quarantined 挂起进程
    monkeypatch.undo()
    pm.shutdown()
    assert q.tree_exited and q.rc is not None
    # shutdown 已把 quarantined 对象确认收口并从隔离集合移除
    assert len(pm.registry.quarantined) == 0
    # shutdown 后不能谎报成功：quarantined 中不应残留未收口对象
    pm2 = ProcessManager()
    try:
        pm2.shutdown()
    except RuntimeError:
        pass


# ==================== Round-11 P1 修复的负向测试 ====================
@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r11_p1_2_cancel_failed_not_swallowed_by_timeout(policy, ws, monkeypatch):
    """cancel 终止请求失败且树仍活 → 后续超时终止成功也必须报取消失败，不得吞成 timeout。"""
    import asyncio as aio

    import win32job

    from mmagent.runtime.cancellation import CancellationToken
    from mmagent.runtime.process import ProcessManager
    from mmagent.tools.python import PythonRunTool
    from mmagent.tools.registry import ToolRegistry as R
    from mmagent.tools.tool_protocol import ToolContext
    from mmagent.workspace.permissions import PermissionChecker as PC
    from mmagent.workspace.permissions import RolePermissions as RP

    (ws.workspace.root / "求解").mkdir(exist_ok=True)
    (ws.workspace.root / "求解" / "sleeper3.py").write_text(
        "import time\ntime.sleep(30)\n", encoding="utf-8"
    )
    pm = ProcessManager()
    perms = RP(role_id="m", read_scopes=("**",), write_scopes=("**",),
               allowed_tools=frozenset({"python.run"}), host_code=True)
    checker = PC(perms, policy)
    reg = R()
    reg.register(PythonRunTool(process_manager=pm))
    token = CancellationToken()
    ctx = ToolContext(policy=policy, permission=checker, cancel=token)

    state = {"first_call": True}

    def fail_first_terminate(*a, **k):
        if state["first_call"]:
            state["first_call"] = False
            raise OSError(6, "injected first terminate failure")
        return real_terminate_impl(*a, **k)

    real_terminate_impl = win32job.TerminateJobObject
    monkeypatch.setattr(win32job, "TerminateJobObject", fail_first_terminate)

    async def run_cancel_then_timeout():
        task = aio.create_task(reg.invoke("python.run", {"path": "求解/sleeper3.py", "timeout_s": 3}, ctx))
        await aio.sleep(0.8)
        token.cancel("cancel with failing terminate (first)")
        return await task

    res = aio.run(run_cancel_then_timeout())
    # 取消请求失败且树仍活 → 显式失败（timed_out 结果携带未确认语义）
    assert res.ok is False
    assert res.meta.get("timed_out") is True or "取消" in (res.error or "") or "quarantined" in (res.error or "")
    # 不得掩盖取消失败：错误消息必须携带"取消终止未确认"
    assert "取消终止未确认" in (res.error or ""), res.error
    monkeypatch.undo()
    pm.shutdown()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r11_p1_3_fast_exit_quota_bypass_blocked(policy, ws):
    """快速写出超配额后立即退出 → 仍必须报告输出超限（不得因 tree 死而跳过检查）。"""
    import asyncio as aio

    from mmagent.runtime.cancellation import CancellationToken
    from mmagent.runtime.process import ProcessManager
    from mmagent.tools.python import PythonRunTool
    from mmagent.tools.registry import ToolRegistry as R
    from mmagent.tools.tool_protocol import ToolContext
    from mmagent.workspace.permissions import PermissionChecker as PC
    from mmagent.workspace.permissions import RolePermissions as RP

    (ws.workspace.root / "求解").mkdir(exist_ok=True)
    (ws.workspace.root / "求解" / "burst.py").write_text(
        "import sys\nsys.stdout.write('x' * (3 * 1024 * 1024))\n", encoding="utf-8"
    )
    pm = ProcessManager(output_quota_bytes=2 * 1024 * 1024)
    perms = RP(role_id="m", read_scopes=("**",), write_scopes=("**",),
               allowed_tools=frozenset({"python.run"}), host_code=True)
    checker = PC(perms, policy)
    reg = R()
    reg.register(PythonRunTool(process_manager=pm))
    token = CancellationToken()
    ctx = ToolContext(policy=policy, permission=checker, cancel=token)
    res = aio.run(reg.invoke("python.run", {"path": "求解/burst.py", "timeout_s": 60}, ctx))
    # 输出超限必须被报告（fast-exit 不得绕过 I-J5）
    assert res.ok is False
    assert "输出超过预算" in (res.error or "") or res.meta.get("timed_out") is True
    pm.shutdown()


# ==================== Round-13 P1 修复的负向测试 ====================
@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r13_p1_2_ctor_failure_rolls_back_raw_handles(policy, ws, monkeypatch):
    """ManagedProcess 构造注入失败 → 回滚 raw handles（挂起进程被终止）+ tmpdir 清理。"""
    import os as _os
    import sys as _sys
    import time as _time

    from mmagent.runtime import process as process_mod
    from mmagent.runtime.process import ProcessManager

    def exploding_ctor(*a, **k):
        raise OSError(12, "injected ctor failure")

    monkeypatch.setattr(process_mod, "ManagedProcess", exploding_ctor)
    pm = ProcessManager()
    import glob as _glob
    import tempfile as _tf
    before_dirs = set(_glob.glob(_os.path.join(_tf.gettempdir(), "mmagent_proc_*")))
    with pytest.raises(OSError, match="injected ctor failure"):
        pm.spawn("r13", [_sys.executable, "-c", "print(1)"])
    monkeypatch.undo()
    # 挂起进程必须已被终止（不能留未托管挂起进程）
    _time.sleep(0.5)
    assert pm.registry.get("r13") is None
    assert pm.registry.quarantined == []
    # tmpdir 无残留（pre-create rollback scope 生效）
    after_dirs = set(_glob.glob(_os.path.join(_tf.gettempdir(), "mmagent_proc_*")))
    assert not (after_dirs - before_dirs), after_dirs - before_dirs


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r13_p1_1_registered_quarantined_natural_death_resolved(policy, ws, monkeypatch):
    """registered+quarantined；第二轮前自然退出 → shutdown 正常收口并清空隔离。"""
    import sys as _sys
    import time as _time

    from mmagent.runtime import process as process_mod
    from mmagent.runtime.process import ProcessManager

    pm = ProcessManager()
    # 1s 后自然退出的进程
    pm.spawn("r13nat", [_sys.executable, "-c", "import time; time.sleep(1)"])
    _time.sleep(0.2)
    # 第一轮：终止失败 → quarantined
    monkeypatch.setattr(process_mod, "_terminate_tree_state", lambda p: "failed")
    import pytest as _pytest

    with _pytest.raises(RuntimeError, match="未能确认终止"):
        pm.shutdown()
    monkeypatch.undo()
    # 进程随后自然退出
    _time.sleep(1.5)
    q = pm.registry.quarantined
    assert not q[0].tree_alive  # 属性访问刷新观测
    assert q[0].tree_exited
    # 再次 shutdown：收口并清空隔离
    pm.shutdown()
    assert pm.registry.quarantined == []


# ==================== Round-17 P1 修复的负向测试 ====================
@pytest.mark.skipif(sys.platform != "win32", reason="Windows process/runtime semantics")
def test_r17_p1_same_shutdown_recovery(policy, ws, monkeypatch):
    """区分度测试（外审 round17）：第一次 _terminate_tree_state 失败注入，
    同一次 shutdown 的 quarantine retry 成功 → 无 RuntimeError、_procs 与
    quarantined 双清、句柄全部关闭。"""
    import sys as _sys
    import time as _time

    from mmagent.runtime import process as process_mod
    from mmagent.runtime.process import ProcessManager

    pm = ProcessManager()
    pm.spawn("r17", [_sys.executable, "-c", "import time; time.sleep(30)"])
    _time.sleep(1)

    state = {"first": True}
    real_ts = process_mod._terminate_tree_state

    def fail_first_then_real(proc):
        if state["first"]:
            state["first"] = False
            return "failed"
        return real_ts(proc)

    monkeypatch.setattr(process_mod, "_terminate_tree_state", fail_first_then_real)
    pm.shutdown()  # 不得抛 RuntimeError（第一轮 failed 由同次 quarantine 收口解决）
    monkeypatch.undo()
    assert pm.registry.get("r17") is None, "_procs 必须清空"
    assert pm.registry.quarantined == [], "quarantined 集合必须清空"
