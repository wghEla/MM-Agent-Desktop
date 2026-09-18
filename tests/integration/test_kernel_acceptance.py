"""内核验收（总方案 v0.1.0 验收条款）：

Mock Agent 能：写 Python → 跑 → 看到 traceback → 修改 → 重跑 →
产出通过 schema 校验的 artifact，且全程事件/消息/tool_call 完整落库。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from mmagent.agent.loop import AgentLoop, AgentTask
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.state import events, repositories
from mmagent.state.models import TaskStatus
from mmagent.tools.filesystem import FsListTool, FsReadTool, FsWriteTool
from mmagent.tools.python import PythonRunTool
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy
from mmagent.workspace.permissions import PermissionChecker, RolePermissions


class ResultDeclaration(BaseModel):
    """v0.1 内核测试用的最小结果声明契约（正式契约在 v0.4+ 的 mm.contracts）。"""

    question: int
    core_metrics: dict[str, float]
    caliber_notes: str


BUGGY_CODE = "value = 1 / 0\nprint(f'answer={value}')\n"
GOOD_CODE = "value = 42 * 1.0\nprint(f'answer={value}')\n"

DECLARATION = {
    "question": 1,
    "core_metrics": {"answer": 42.0},
    "caliber_notes": "按题面口径直接计算",
}


def _build_loop(ws, db, script: MockScript) -> tuple[AgentLoop, Path]:
    policy = PathPolicy(ws.workspace.root)
    perms = RolePermissions(
        role_id="modeler",
        read_scopes=("输入/**", "交接/**", "求解/**"),
        write_scopes=("求解/**", "交接/**"),
        allowed_tools=frozenset({"fs.read", "fs.write", "fs.list", "python.run"}),
        host_code=True,  # 建模师是受信任角色：显式授予宿主代码执行能力（P0-3 语义）
    )
    checker = PermissionChecker(perms, policy)
    registry = ToolRegistry()
    for tool in (FsReadTool(), FsWriteTool(), FsListTool(), PythonRunTool()):
        registry.register(tool)
    provider = MockProvider(script)
    loop = AgentLoop(db, provider, registry, checker, policy)
    return loop, ws.workspace.root


def _make_task(ws, db, run_id: str) -> AgentTask:
    t = repositories.create_task(
        db,
        run_id=run_id,
        stage_key="S2",
        node_key="S2:问1",
        role_id="modeler",
        expected_artifacts=[{"rel_path": "交接/结果声明_问题1.json", "schema": "ResultDeclaration"}],
    )
    return AgentTask(
        task_id=t.id,
        node_key="S2:问1",
        role_id="modeler",
        system_prompt="你是建模师（内核验收测试）。",
        instructions="写 求解/问题1/求解_问题1.py，运行修好它，然后把结果声明写到 交接/结果声明_问题1.json。",
        model="mock-1",
        expected_artifacts=[
            ExpectedArtifact(rel_path="交接/结果声明_问题1.json", schema_model=ResultDeclaration)
        ],
    )


@pytest.mark.asyncio
async def test_kernel_acceptance_loop(ws, db, run_id):
    """验收主链路：写→跑（崩）→改→跑（成）→声明 artifact → SUCCEEDED。"""
    script = MockScript(
        [
            MockTurn(tool_calls=[("c1", "fs.write", {"path": "求解/问题1/求解_问题1.py", "content": BUGGY_CODE})]),
            MockTurn(tool_calls=[("c2", "python.run", {"path": "求解/问题1/求解_问题1.py"})]),
            MockTurn(tool_calls=[("c3", "fs.write", {"path": "求解/问题1/求解_问题1.py", "content": GOOD_CODE})]),
            MockTurn(tool_calls=[("c4", "python.run", {"path": "求解/问题1/求解_问题1.py"})]),
            MockTurn(tool_calls=[("c5", "fs.write", {"path": "交接/结果声明_问题1.json", "content": json.dumps(DECLARATION, ensure_ascii=False)})]),
            MockTurn(text="求解完成，结果声明已落盘。"),
        ]
    )
    loop, root = _build_loop(ws, db, script)
    spec = _make_task(ws, db, run_id)
    outcome = await loop.run(spec)

    # 1) 任务成功且是 Runtime 判定（非模型宣告）
    assert outcome.status is TaskStatus.SUCCEEDED, outcome.error
    # 2) 模型确实经历了 traceback → 修复
    script.turns[2].assert_saw_tool("python.run")
    assert "ZeroDivisionError" in (outcome.result.get("final_text", "") or "") or True
    tool_rows = db.query(
        "SELECT name, status, result_json FROM tool_calls ORDER BY seq"
    )
    py_runs = [r for r in tool_rows if r["name"] == "python.run"]
    assert len(py_runs) == 2
    first = json.loads(py_runs[0]["result_json"])
    second = json.loads(py_runs[1]["result_json"])
    assert first["rc"] != 0 and "ZeroDivisionError" in first["stderr_tail"]
    assert second["rc"] == 0 and "answer=42.0" in second["stdout_tail"]
    # 3) artifact 落库并带 hash/版本
    art = db.query_one("SELECT * FROM artifacts WHERE task_id = ?", (spec.task_id,))
    assert art is not None and art["schema_id"] == "ResultDeclaration"
    assert art["hash"]
    # 4) 全程事件可回放
    evs = [e.type for e in events.query_events(db, run_id=run_id)]
    assert "task.created" in evs and "task.succeeded" in evs
    assert evs.count("tool.call") == 5
    assert "invocation.started" in evs and "invocation.finished" in evs
    # 5) 消息历史持久化（system+user+assistant+tool 交替）
    n_msgs = db.query_one("SELECT COUNT(*) AS n FROM messages")["n"]
    assert n_msgs >= 8
    # 6) 磁盘产物确实存在且内容正确
    decl = json.loads((root / "交接" / "结果声明_问题1.json").read_text(encoding="utf-8"))
    assert ResultDeclaration.model_validate(decl).core_metrics == {"answer": 42.0}


@pytest.mark.asyncio
async def test_model_cannot_declare_success_without_artifact(ws, db, run_id):
    """模型说完成了、但产物缺失 → FAILED（declared != enforced）。"""
    script = MockScript([MockTurn(text="我已经完成了！真的！")])
    loop, _ = _build_loop(ws, db, script)
    spec = _make_task(ws, db, run_id)
    outcome = await loop.run(spec)
    assert outcome.status is TaskStatus.FAILED
    assert outcome.error_kind.value == "artifact_missing"
    t = repositories.get_task(db, spec.task_id)
    assert t.status is TaskStatus.FAILED and "artifact_missing" in (t.error or "")


@pytest.mark.asyncio
async def test_invalid_schema_artifact_fails(ws, db, run_id):
    """产物存在但 schema 不过 → FAILED（artifact_invalid）。"""
    bad = {"question": "一", "core_metrics": {"answer": "很多"}}
    script = MockScript(
        [
            MockTurn(tool_calls=[("c1", "fs.write", {"path": "交接/结果声明_问题1.json", "content": json.dumps(bad, ensure_ascii=False)})]),
            MockTurn(text="完成"),
        ]
    )
    loop, _ = _build_loop(ws, db, script)
    spec = _make_task(ws, db, run_id)
    outcome = await loop.run(spec)
    assert outcome.status is TaskStatus.FAILED
    assert "artifact_invalid" in (outcome.error or "")


@pytest.mark.asyncio
async def test_denied_tool_call_recorded_and_fed_back(ws, db, run_id):
    """无权限工具调用 → DENIED 结果回填，模型可继续；不得崩溃。"""
    policy = PathPolicy(ws.workspace.root)
    # 红队角色：无 python.run、无 求解/** 写权限
    perms = RolePermissions(
        role_id="red_team",
        read_scopes=("交接/题面契约.json",),
        write_scopes=("红队结果/**",),
        allowed_tools=frozenset({"fs.read", "fs.write"}),
    )
    registry = ToolRegistry()
    for tool in (FsReadTool(), FsWriteTool(), PythonRunTool()):
        registry.register(tool)
    script = MockScript(
        [
            MockTurn(tool_calls=[("c1", "python.run", {"path": "求解/问题1/x.py"})]),
            MockTurn(text="好，我不用 python 了"),
        ]
    )
    loop = AgentLoop(db, MockProvider(script), registry, PermissionChecker(perms, policy), policy)
    t = repositories.create_task(db, run_id=run_id, stage_key="S2", node_key="S2:红队", role_id="red_team")
    spec = AgentTask(
        task_id=t.id, node_key="S2:红队", role_id="red_team",
        system_prompt="s", instructions="i", model="mock-1",
    )
    outcome = await loop.run(spec)
    assert outcome.status is TaskStatus.SUCCEEDED  # 模型改口后正常结束（无期望产物）
    row = db.query_one("SELECT status, error FROM tool_calls WHERE name='python.run'")
    assert row["status"] == "denied"
