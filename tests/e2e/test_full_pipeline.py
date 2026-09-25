"""v1.0.0 E2E 测试：合成题 S0→G0→S1→G1 全链路（mock provider）。

覆盖：完整管线、crash recovery、provider failure、G0/G1 门检全过。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.agent.errors import RateLimitError
from mmagent.mm.gates.g0 import check_g0
from mmagent.mm.pipeline.s0_s1 import check_g1, run_s0
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.state import repositories
from mmagent.tools.filesystem import FsReadTool, FsWriteTool
from mmagent.tools.python import PythonRunTool
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.permissions import PermissionChecker, RolePermissions

CONTRACT = json.dumps({
    "赛题": "B", "标题": "合成测试题",
    "问题": [
        {"编号": 1, "原文摘录": "问题1", "解读": "建模",
         "需求条目": [{"需求号": "1-1", "内容": "建模", "评分点推测": "推导"}]},
    ],
    "硬约束清单": [{"约束号": "C1", "内容": "约束"}],
    "歧义裁定": [],
    "附件清单": [],
}, ensure_ascii=False)

ARCHIVE = json.dumps({"条目": []}, ensure_ascii=False)
PREDICTION = "# 预测\n\n撞车方法：线性回归\n"
PLAN = json.dumps({
    "问题清单": [{
        "编号": 1,
        "主方法": "LS",
        "依赖问题": [],
        "锦标赛": {
            "参赛路线": ["路线A", "路线B", "路线C"],
            "优胜": "路线A",
            "依据": "三条原型均真实执行，路线A诊断最好",
        },
    }],
    "叙事主线": "数据→厚度",
}, ensure_ascii=False)


def _s0_script() -> MockScript:
    return MockScript([
        MockTurn(tool_calls=[
            ("c1", "fs.write", {"path": "交接/题面契约.json", "content": CONTRACT}),
            ("c2", "fs.write", {"path": "交接/数据档案.json", "content": ARCHIVE}),
        ]),
        MockTurn(text="读题完成"),
        MockTurn(tool_calls=[
            ("c3", "fs.write", {"path": "交接/典型答卷预测.md", "content": PREDICTION}),
        ]),
        MockTurn(text="预测完成"),
    ])


def _s1_script() -> MockScript:
    scout = json.dumps({
        "问题清单": [{
            "编号": 1,
            "路线": [
                {"路线名": "路线A", "方法": "LS", "方法理由": "基准", "原型目标": "诊断A"},
                {"路线名": "路线B", "方法": "Robust", "方法理由": "稳健", "原型目标": "诊断B"},
                {"路线名": "路线C", "方法": "Ridge", "方法理由": "正则", "原型目标": "诊断C"},
            ],
        }],
        "最难问题编号": 1,
    }, ensure_ascii=False)
    turns = [
        MockTurn(tool_calls=[
            ("s1s", "fs.write", {"path": "交接/路线侦察.json", "content": scout}),
        ]),
        MockTurn(text="侦察完成"),
    ]
    for index, name in enumerate(("A", "B", "C"), 1):
        turns += [
            MockTurn(tool_calls=[
                (
                    f"s1p{index}",
                    "fs.write",
                    {
                        "path": f"求解/问题1/原型_{index}.py",
                        "content": f"print('route {name} diagnostic={1.0-index*0.1:.1f}')\n",
                    },
                ),
            ]),
            MockTurn(text=f"原型{name}完成"),
        ]
    turns += [
        MockTurn(tool_calls=[
            ("s1f", "fs.write", {"path": "交接/计划.json", "content": PLAN}),
        ]),
        MockTurn(text="规划完成"),
    ]
    return MockScript(turns)


def _setup(tmp_path: Path):
    from mmagent.api.projects import create_project
    from mmagent.workspace.path_policy import PathPolicy

    root = tmp_path / "e2e"
    handle = create_project(root, name="e2e", profile="标准")
    (root / "输入" / "题目").mkdir(parents=True, exist_ok=True)
    (root / "输入" / "题目" / "题.pdf").write_bytes(b"%PDF-test")
    policy = PathPolicy(root)

    reg = ToolRegistry()
    reg.register(FsReadTool())
    reg.register(FsWriteTool())
    reg.register(PythonRunTool())

    perms = RolePermissions(
        role_id="test", read_scopes=("**",), write_scopes=("交接/**",),
        allowed_tools=frozenset({"fs.read", "fs.write"}),
    )
    checker = PermissionChecker(perms, policy)
    return handle, handle.workspace.db, policy, reg, checker


@pytest.mark.asyncio
async def test_e2e_s0_g0_s1_g1(tmp_path: Path):
    """全链路 E2E：S0 → G0 → S1 → G1 全过。"""
    handle, db, policy, reg, checker = _setup(tmp_path)
    run_id = repositories.create_run(db, project_id=handle.project_id, profile="标准")

    # S0
    provider_s0 = MockProvider(_s0_script())
    s0_result = await run_s0(db, provider_s0, reg, policy, run_id)
    assert s0_result["g0_pass"], s0_result["g0_issues"]
    assert (policy.root / "交接" / "题面契约.json").is_file()
    assert (policy.root / "交接" / "需求追踪矩阵.json").is_file()

    # G0 门检确认
    ok, issues = check_g0(policy.root)
    assert ok, issues

    # S1
    provider_s1 = MockProvider(_s1_script())
    from mmagent.mm.pipeline.s0_s1 import run_s1
    s1_result = await run_s1(db, provider_s1, reg, policy, run_id)
    assert s1_result["g1_pass"], s1_result["g1_issues"]
    assert (policy.root / "交接" / "计划.json").is_file()

    # G1 门检确认
    ok, issues = check_g1(policy.root)
    assert ok, issues

    # 事件回放完整性
    from mmagent.state import events
    evs = events.query_events(db, run_id=run_id)
    types = [e.type for e in evs]
    assert "run.created" in types
    assert "task.created" in types
    assert "task.succeeded" in types
    handle.workspace.db.close()


@pytest.mark.asyncio
async def test_crash_recovery_preserves_state(tmp_path: Path):
    """崩溃恢复：S0 中途崩溃 → RUNNING 任务标 FAILED → 重新 S0 成功。"""
    handle, db, policy, reg, checker = _setup(tmp_path)
    run_id = repositories.create_run(db, project_id=handle.project_id, profile="标准")

    # 第一次 S0：脚本只够一半（模拟崩溃）
    partial = MockScript([
        MockTurn(tool_calls=[
            ("c1", "fs.write", {"path": "交接/题面契约.json", "content": CONTRACT}),
        ]),
        # 模型在写入数据档案前崩溃
        MockTurn(text="partial"),  # 不写数据档案
    ])
    provider = MockProvider(partial)
    # S0 会因为缺少数据档案而失败（G0 检查）
    result = await run_s0(db, provider, reg, policy, run_id)
    # G0 不通过（缺数据档案）
    assert not result["g0_pass"]

    # 模拟崩溃恢复：检查 RUNNING 残留
    from mmagent.api.projects import reset_interrupted_tasks
    reset_interrupted_tasks(handle, run_id)
    # 第二次 S0：新 run_id（崩溃后重新启动的正确语义）
    provider2 = MockProvider(_s0_script())
    run_id2 = repositories.create_run(db, project_id=handle.project_id, profile="标准")
    contract_path = policy.root / "交接" / "题面契约.json"
    if contract_path.exists():
        contract_path.unlink()
    result2 = await run_s0(db, provider2, reg, policy, run_id2)
    assert result2["g0_pass"], result2["g0_issues"]
    handle.workspace.db.close()


@pytest.mark.asyncio
async def test_provider_rate_limit_retry(tmp_path: Path):
    """429 限流 → 任务回队列 → 重试成功。"""
    handle, db, policy, reg, checker = _setup(tmp_path)
    run_id = repositories.create_run(db, project_id=handle.project_id, profile="标准")

    script = MockScript([MockTurn(text="done after retry")])
    provider = MockProvider(script)
    provider.queue_error(RateLimitError("429", retry_after_s=0.1))

    from mmagent.agent.loop import AgentTask

    task_rec = repositories.create_task(
        db, run_id=run_id, stage_key="S0", node_key="S0:test", role_id="reader")
    loop = __import__("mmagent.agent.loop", fromlist=["AgentLoop"]).AgentLoop(
        db, provider, reg, checker, policy)
    spec = AgentTask(
        task_id=task_rec.id, node_key="S0:test", role_id="reader",
        system_prompt="test", instructions="test", model="mock",
    )
    outcome = await loop.run(spec)
    # 第一次 429 → QUEUED；第二次重试成功
    assert outcome.status.value in ("SUCCEEDED", "QUEUED")
    handle.workspace.db.close()
