"""故障注入（v0.1 内核）：限流、取消、超时、崩溃恢复、重复提交、JSON 修复回路。"""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from mmagent.agent.errors import RateLimitError
from mmagent.agent.loop import AgentLoop, AgentTask
from mmagent.api import projects as api_projects
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.state import events, repositories
from mmagent.state.models import StateTransitionError, TaskStatus
from mmagent.tools.filesystem import FsReadTool, FsWriteTool
from mmagent.tools.python import PythonRunTool
from mmagent.tools.registry import ToolRegistry
from mmagent.tools.tool_protocol import Tool, ToolContext, ToolResult, ToolSpec
from mmagent.workspace.permissions import PermissionChecker, RolePermissions


def _registry(tmp_tool: Tool | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    for t in (FsReadTool(), FsWriteTool(), PythonRunTool()):
        registry.register(t)
    if tmp_tool is not None:
        registry.register(tmp_tool)
    return registry


ROOT: list = []  # 由 fixture 注入 (policy,)


@pytest.fixture
def env(ws, db, run_id):
    from mmagent.workspace.path_policy import PathPolicy

    ROOT.clear()
    ROOT.append(ws.workspace.root)
    policy = PathPolicy(ws.workspace.root)
    perms = RolePermissions(
        role_id="tester",
        read_scopes=("**",),
        write_scopes=("**",),
        allowed_tools=frozenset({"fs.read", "fs.write", "python.run", "test.self_destruct"}),
        host_code=True,  # 故障注入测试里的受信角色
    )
    checker = PermissionChecker(perms, policy)
    return {"ws": ws, "db": db, "run_id": run_id, "policy": policy, "checker": checker}


def _spec(db, run_id: str, node: str = "N1") -> AgentTask:
    t = repositories.create_task(db, run_id=run_id, stage_key="T", node_key=node, role_id="tester")
    return AgentTask(
        task_id=t.id, node_key=node, role_id="tester",
        system_prompt="s", instructions="i", model="mock-1",
    )


class SelfDestructTool(Tool):
    """注入点：执行时触发取消（模拟用户点停止）。"""

    spec = ToolSpec(name="test.self_destruct", description="", parameters={"type": "object", "properties": {}})

    def __init__(self, cancel):
        self._cancel = cancel

    async def execute(self, args, ctx: ToolContext) -> ToolResult:
        self._cancel.cancel("user pressed stop")
        return ToolResult(ok=True, content="cancelled")


@pytest.mark.asyncio
async def test_rate_limit_is_retryable_not_failure(env):
    db, run_id = env["db"], env["run_id"]
    provider = MockProvider(MockScript([MockTurn(text="done")]))
    provider.queue_error(RateLimitError("429", retry_after_s=0.5))
    loop = AgentLoop(db, provider, _registry(), env["checker"], env["policy"])
    spec = _spec(db, run_id)
    outcome = await loop.run(spec)
    assert outcome.status is TaskStatus.QUEUED  # 回队列，不是 FAILED
    assert outcome.retryable and outcome.error_kind.value == "provider_rate_limit"
    assert any(e.type == "task.rate_limited" for e in events.query_events(db, run_id=run_id))
    # 重试后成功
    outcome2 = await loop.run(spec)  # FAILED→？不，QUEUED→RUNNING 合法
    assert outcome2.status is TaskStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_cancel_mid_run(env):
    db, run_id = env["db"], env["run_id"]
    from mmagent.runtime.cancellation import CancellationToken

    token = CancellationToken()
    script = MockScript(
        [
            MockTurn(tool_calls=[("c1", "test.self_destruct", {})]),
            MockTurn(text="should never get here"),
        ]
    )
    registry = _registry(SelfDestructTool(token))
    loop = AgentLoop(db, MockProvider(script), registry, env["checker"], env["policy"], cancel=token)
    spec = _spec(db, run_id)
    outcome = await loop.run(spec)
    assert outcome.status is TaskStatus.CANCELLED
    row = db.query_one("SELECT status FROM tasks WHERE id = ?", (spec.task_id,))
    assert row["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_tool_timeout_kills_process(env):
    db, run_id, root = db_and_root(env)
    script_path = root / "求解" / "sleeper.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    registry = _registry()
    script = MockScript(
        [
            MockTurn(tool_calls=[("c1", "python.run", {"path": "求解/sleeper.py", "timeout_s": 1})]),
            MockTurn(text="done"),
        ]
    )
    t0 = time.monotonic()
    loop = AgentLoop(db, MockProvider(script), registry, env["checker"], env["policy"])
    spec = _spec(db, run_id)
    outcome = await loop.run(spec)
    elapsed = time.monotonic() - t0
    row = db.query_one(
        "SELECT status, result_json FROM tool_calls WHERE name='python.run'"
    )
    meta = json.loads(row["result_json"])
    assert meta.get("timed_out") is True
    assert elapsed < 15  # 进程树确实被杀，不是等满 30s
    assert outcome.status is TaskStatus.SUCCEEDED  # 无期望产物，模型收尾即成功


def db_and_root(env):
    return env["db"], env["run_id"], env["ws"].workspace.root


def test_crash_recovery_marks_task_and_invocation_failed(ws, db, run_id):
    t = repositories.create_task(
        db, run_id=run_id, stage_key="S", node_key="S:crash", role_id="x"
    )
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    owner = repositories.new_owner_token()
    assert repositories.acquire_task_lease(db, t.id, owner)
    _, invocation_id = repositories.begin_task_attempt(
        db,
        t.id,
        owner,
        role_id="x",
        provider_profile="default",
        model="mock",
        reasoning=None,
    )

    # 模拟崩溃后重开：active task 和 invocation 都不得继续伪装成 RUNNING。
    handle = api_projects.open_project(ws.workspace.root)
    try:
        n = api_projects.reset_interrupted_tasks(handle, run_id)
    finally:
        handle.workspace.db.close()

    assert n == 1
    t2 = repositories.get_task(db, t.id)
    assert t2.status is TaskStatus.FAILED
    invocation = db.query_one(
        "SELECT status, ended_at FROM agent_invocations WHERE id = ?",
        (invocation_id,),
    )
    assert invocation["status"] == "FAILED"
    assert invocation["ended_at"] is not None

    recovered = events.query_events(db, run_id=run_id, type="task.recovered")
    assert recovered[-1].payload["closed_invocations"] == 1

    # FAILED 可显式重试回 READY。
    repositories.transition_task(db, t.id, TaskStatus.READY)


def test_run_lock_prevents_second_owner(ws, db, run_id):
    ws.workspace.acquire_run_lock(run_id)  # 已由 start? 直接再取应失败（同 pid 持有）
    import pytest

    from mmagent.agent.errors import RunLocked

    with pytest.raises(RunLocked):
        ws.workspace.acquire_run_lock("another-run")
    ws.workspace.release_run_lock()
    # 释放后可再取
    ws.workspace.acquire_run_lock("another-run")
    ws.workspace.release_run_lock()


def test_stale_lock_allows_takeover(ws, db, run_id):

    lock = ws.workspace.root / ".mmagent" / "run.lock"
    lock.write_text(json.dumps({"run_id": "ghost", "pid": 99999999}), encoding="utf-8")
    # pid 99999999 几乎必然不存在 → 允许接管
    ws.workspace.acquire_run_lock(run_id)
    ws.workspace.release_run_lock()


def test_duplicate_success_rejected(db, run_id):
    t = repositories.create_task(db, run_id=run_id, stage_key="S", node_key="S:dup")
    repositories.transition_task(db, t.id, TaskStatus.READY)
    repositories.transition_task(db, t.id, TaskStatus.QUEUED)
    owner = repositories.new_owner_token()
    assert repositories.acquire_task_lease(db, t.id, owner)
    repositories.commit_task_success(db, t.id, artifacts=[], owner_token=owner)
    with pytest.raises(StateTransitionError):
        repositories.commit_task_success(db, t.id, artifacts=[])  # 重复完成（retry 双写防护）


def test_bad_tool_args_json_does_not_crash(env):
    """工具参数 JSON 非法 → 结构化错误回填（模型可下一轮修复），不是崩溃。"""
    from mmagent.runtime.cancellation import CancellationToken
    from mmagent.tools.tool_protocol import ToolContext

    ctx = ToolContext(policy=env["policy"], permission=env["checker"], cancel=CancellationToken())
    result = asyncio.run(_invoke(_registry(), "fs.write", "{bad json", ctx))
    assert result.ok is False and "JSON" in (result.error or "")
    assert result.meta.get("denied") is None


async def _invoke(registry, name, args, ctx):
    return await registry.invoke(name, args, ctx)
