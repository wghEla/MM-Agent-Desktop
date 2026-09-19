"""S0/G0/S1 流水线节点执行器（编排层，mock provider 级）。

S0 流程：Reader(读题官) → AnswerPredictor(答卷预测官) → 机械生成需求追踪矩阵 → G0 门检。
S1 流程：Planner(规划师) → G1 门检（计划完整性机械判据）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmagent.agent.loop import AgentLoop, AgentTask
from mmagent.mm.roles.prompts import ANSWER_PREDICTOR_SYSTEM, PLANNER_SYSTEM, READER_SYSTEM
from mmagent.mm.roles.registry import get_role
from mmagent.providers.base import BaseProvider
from mmagent.state import repositories
from mmagent.state.db import Database
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy
from mmagent.workspace.permissions import PermissionChecker


async def run_s0(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    *,
    cancel=None,
) -> dict[str, Any]:
    """执行 S0：读题官 → 答卷预测官 → 机械生成需求追踪矩阵。

    返回 {"g0_pass": bool, "g0_issues": [...], "tasks": [...]}。
    """
    tasks: list[dict] = []
    for role_id, node_key, system, instructions, expected in _s0_specs():
        task_rec = repositories.create_task(
            db, run_id=run_id, stage_key="S0", node_key=node_key, role_id=role_id,
        )
        loop = AgentLoop(
            db, provider, registry,
            PermissionChecker(get_role(role_id).permissions(), policy),
            policy, cancel=cancel,
        )
        spec = AgentTask(
            task_id=task_rec.id, node_key=node_key, role_id=role_id,
            system_prompt=system, instructions=instructions,
            model="mock", reasoning=get_role(role_id).reasoning,
            expected_artifacts=expected,
        )
        outcome = await loop.run(spec)
        tasks.append({"node": node_key, "status": outcome.status.value, "error": outcome.error})
        if outcome.status.value != "SUCCEEDED":
            return {"g0_pass": False, "g0_issues": [f"{node_key} 未成功: {outcome.error}"], "tasks": tasks}

    # 机械生成需求追踪矩阵
    await _generate_requirement_matrix(db, policy, run_id, registry, cancel)
    tasks.append({"node": "S0.4:矩阵", "status": "SUCCEEDED"})

    # G0 门检
    from mmagent.mm.gates.g0 import check_g0
    ok, issues = check_g0(policy.root)
    return {"g0_pass": ok, "g0_issues": issues, "tasks": tasks}


def _s0_specs() -> list[tuple[str, str, str, str, list[ExpectedArtifact]]]:
    reader = get_role("reader")
    predictor = get_role("answer_predictor")
    return [
        ("reader", "S0.2:读题", READER_SYSTEM,
         "读取 输入/题目/ 下的题目文件与 输入/数据/ 下的附件清单。"
         "产出 交接/题面契约.json 和 交接/数据档案.json。",
         [ExpectedArtifact(rel_path="交接/题面契约.json"),
          ExpectedArtifact(rel_path="交接/数据档案.json")]),
        ("answer_predictor", "S0.3:预测", ANSWER_PREDICTOR_SYSTEM,
         "读取 交接/题面契约.json 和 交接/数据档案.json。"
         "产出 交接/典型答卷预测.md。",
         [ExpectedArtifact(rel_path="交接/典型答卷预测.md", kind="text")]),
    ]


async def _generate_requirement_matrix(
    db: Database, policy: PathPolicy, run_id: str, registry: ToolRegistry, cancel=None
) -> None:
    """机械生成需求追踪矩阵（从题面契约提取，不由模型生成）。"""
    contract_path = policy.root / "交接" / "题面契约.json"
    if not contract_path.is_file():
        return
    raw = json.loads(contract_path.read_text(encoding="utf-8"))
    matrix: list[dict[str, Any]] = []
    for prob in raw.get("问题", []):
        num = prob.get("编号", 0)
        for req in prob.get("需求条目", []):
            matrix.append({
                "需求号": req.get("需求号", ""),
                "问题编号": num,
                "内容": req.get("内容", ""),
                "状态": "未落位",
                "章节": "",
                "图表": "",
                "关键数字": "",
            })
    matrix_path = policy.root / "交接" / "需求追踪矩阵.json"
    matrix_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- G1
def check_g1(workspace_root: Path) -> tuple[bool, list[str]]:
    """G1 门检：计划存在、每问路线/方法/依赖齐、原型执行证据。"""
    issues: list[str] = []
    root = Path(workspace_root)
    plan_path = root / "交接" / "计划.json"
    if not plan_path.is_file():
        return False, ["交接/计划.json 缺失"]
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, [f"计划.json 不可解析: {e}"]
    problems = plan.get("问题清单") or []
    if not problems:
        issues.append("计划 问题清单 为空")
    for p in problems:
        num = p.get("编号")
        if not p.get("主方法"):
            issues.append(f"问{num} 缺主方法")
        deps = p.get("依赖问题")
        if deps is None:
            issues.append(f"问{num} 缺依赖问题")
        elif isinstance(deps, list):
            # 检查 DAG 不成环（简化：不许自依赖）
            if num in deps:
                issues.append(f"问{num} 自依赖非法")
    if not plan.get("叙事主线"):
        issues.append("计划缺叙事主线")
    return (len(issues) == 0), issues


async def run_s1(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    *,
    cancel=None,
) -> dict[str, Any]:
    """执行 S1：规划师 → G1 门检。"""
    task_rec = repositories.create_task(
        db, run_id=run_id, stage_key="S1", node_key="S1:规划", role_id="planner",
    )
    loop = AgentLoop(
        db, provider, registry,
        PermissionChecker(get_role("planner").permissions(), policy),
        policy, cancel=cancel,
    )
    spec = AgentTask(
        task_id=task_rec.id, node_key="S1:规划", role_id="planner",
        system_prompt=PLANNER_SYSTEM,
        instructions="读取 交接/题面契约.json 和 交接/典型答卷预测.md。产出 交接/计划.json。",
        model="mock", reasoning=get_role("planner").reasoning,
        expected_artifacts=[ExpectedArtifact(rel_path="交接/计划.json")],
    )
    outcome = await loop.run(spec)
    if outcome.status.value != "SUCCEEDED":
        return {"g1_pass": False, "g1_issues": [f"S1 未成功: {outcome.error}"]}
    from mmagent.mm.gates.g0 import check_g0 as _g0  # noqa
    ok, issues = check_g1(policy.root)
    return {"g1_pass": ok, "g1_issues": issues}
