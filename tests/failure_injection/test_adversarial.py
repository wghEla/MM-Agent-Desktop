"""对抗性测试——外审 v0.1.0 报告要求的 release-gate 测试清单。

P0-1 SUCCEEDED 强制路径 / P0-2 junction 穿透 scope / P0-3 host_code 能力位 /
P1-1 双执行者租约 / P1-2 显式重试 / P1-3 取消优先 / P1-4 provider 取消不验收 /
P1-7 封存 / P1-8 变量注入 / P2-1 尝试上限 / P2-5 ADS 拒绝。
"""
from __future__ import annotations

import json
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
