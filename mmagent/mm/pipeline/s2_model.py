"""S2 编排：建模→执行→红队→比对→仲裁→G2（含升格蜂群+降级放行+级联重算）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmagent.agent import repositories
from mmagent.agent.loop import AgentLoop, AgentTask
from mmagent.mm.gates.g2 import check_g2
from mmagent.mm.roles.registry import get_role
from mmagent.orchestration.dag import build_dependency_graph, topological_layers
from mmagent.providers.base import BaseProvider
from mmagent.state.db import Database
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.path_policy import PathPolicy
from mmagent.workspace.permissions import PermissionChecker

_MAX_REWORK = 2
_RED_TEAM_TOLERANCE = 0.01


async def run_s2(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    plan_path: Path,
    *,
    cancel=None,
) -> dict[str, Any]:
    """执行 S2：按 DAG 分层建模求解。

    返回 {"gates": {问号: {"pass": bool, "issues": [...]}}, "downgraded": [...]}。
    """
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    problem_list = plan.get("问题清单", [])
    graph = build_dependency_graph(problem_list)
    layers = topological_layers(graph)

    results: dict[str, Any] = {"gates": {}, "downgraded": []}

    for layer_num, layer in enumerate(layers, 1):
        for q_num in layer:
            gate_key = f"问{q_num}"
            # 建模师
            await _run_modeler(db, provider, registry, policy, run_id, q_num, cancel)
            # 红队（权限层硬隔离：用 red_team 的 PermissionChecker）
            await _run_red_team(db, provider, registry, policy, run_id, q_num, cancel)
            # G2 门检
            ok, issues = check_g2(policy.root, q_num)
            results["gates"][gate_key] = {"pass": ok, "issues": issues}
            if ok:
                continue
            # 返工 ≤2
            for rework in range(_MAX_REWORK):
                await _run_modeler(db, provider, registry, policy, run_id, q_num, cancel,
                                   rework=True)
                await _run_red_team(db, provider, registry, policy, run_id, q_num, cancel)
                ok, issues = check_g2(policy.root, q_num)
                if ok:
                    break
            if ok:
                results["gates"][gate_key] = {"pass": True, "issues": []}
                continue
            # 升格蜂群（3 变体）
            await _run_escalation(db, provider, registry, policy, run_id, q_num, cancel)
            ok, issues = check_g2(policy.root, q_num)
            if ok:
                results["gates"][gate_key] = {"pass": True, "issues": []}
                continue
            # 降级放行
            results["gates"][gate_key] = {"pass": False, "issues": issues, "downgraded": True}
            results["downgraded"].append(q_num)

    return results


async def _run_modeler(db: Database, provider: BaseProvider, registry: ToolRegistry,
                       policy: PathPolicy, run_id: str, q_num: int, cancel=None,
                       *, rework: bool = False) -> None:
    role = get_role("modeler")
    perms = role.permissions(question=str(q_num))
    checker = PermissionChecker(perms, policy)
    loop = AgentLoop(db, provider, registry, checker, policy, cancel=cancel)
    task_rec = repositories.create_task(
        db, run_id=run_id, stage_key="S2", node_key=f"S2:问{q_num}{'返工' if rework else ''}",
        role_id="modeler",
    )
    rework_hint = "返工：修正上次的问题。" if rework else ""
    spec = AgentTask(
        task_id=task_rec.id, node_key=f"S2:问{q_num}", role_id="modeler",
        system_prompt=f"你是建模师。负责问题{q_num}的建模与求解。{rework_hint}",
        instructions=(f"编写 求解/问题{q_num}/求解_问题{q_num}.py 并运行。"
                      f"产出 交接/结果声明_问题{q_num}.json。"),
        model="mock", reasoning=role.reasoning,
        expected_artifacts=[
            {"rel_path": f"交接/结果声明_问题{q_num}.json", "required": False},
        ],
    )
    await loop.run(spec)


async def _run_red_team(db: Database, provider: BaseProvider, registry: ToolRegistry,
                        policy: PathPolicy, run_id: str, q_num: int, cancel=None) -> None:
    """红队：使用 red_team 角色的 PermissionChecker（权限层硬隔离）。"""
    role = get_role("red_team")
    perms = role.permissions(question=str(q_num))
    checker = PermissionChecker(perms, policy)
    loop = AgentLoop(db, provider, registry, checker, policy, cancel=cancel)
    task_rec = repositories.create_task(
        db, run_id=run_id, stage_key="S2", node_key=f"S2:红队问{q_num}", role_id="red_team",
    )
    spec = AgentTask(
        task_id=task_rec.id, node_key=f"S2:红队问{q_num}", role_id="red_team",
        system_prompt=f"你是红队。独立复算问题{q_num}的头条数字。",
        instructions=(f"编写 求解/问题{q_num}/复算.py 并运行。"
                      f"产出 交接/红队_问题{q_num}.json。"),
        model="mock", reasoning=role.reasoning,
        expected_artifacts=[
            {"rel_path": f"交接/红队_问题{q_num}.json", "required": False},
        ],
    )
    await loop.run(spec)


async def _run_escalation(db: Database, provider: BaseProvider, registry: ToolRegistry,
                          policy: PathPolicy, run_id: str, q_num: int, cancel=None) -> None:
    """升格蜂群：3 变体 + 裁决。"""
    for variant in range(1, 4):
        role = get_role("modeler")
        perms = role.permissions(question=str(q_num))
        checker = PermissionChecker(perms, policy)
        loop = AgentLoop(db, provider, registry, checker, policy, cancel=cancel)
        task_rec = repositories.create_task(
            db, run_id=run_id, stage_key="S2", node_key=f"S2:升格{q_num}_变体{variant}",
            role_id="modeler",
        )
        spec = AgentTask(
            task_id=task_rec.id, node_key=f"S2:升格{q_num}_变体{variant}", role_id="modeler",
            system_prompt=f"你是建模师（升格蜂群变体{variant}）。换一种方法重做问题{q_num}。",
            instructions=f"换方法重做问题{q_num}，产出到 求解/问题{q_num}/。",
            model="mock", reasoning=role.reasoning,
        )
        await loop.run(spec)
    # 裁决腿（简化：v0.5 用裁决 Agent 选最优）
    role = get_role("interpreter")
    perms = get_role("interpreter").permissions(question=str(q_num))
    checker = PermissionChecker(perms, policy)
    loop = AgentLoop(db, provider, registry, checker, policy, cancel=cancel)
    task_rec = repositories.create_task(
        db, run_id=run_id, stage_key="S2", node_key=f"S2:裁决{q_num}", role_id="interpreter",
    )
    spec = AgentTask(
        task_id=task_rec.id, node_key=f"S2:裁决{q_num}", role_id="interpreter",
        system_prompt=f"你是解读师。裁决问题{q_num}的升格蜂群优胜方案。",
        instructions=f"裁决优胜方案并更新 交接/结果声明_问题{q_num}.json。",
        model="mock", reasoning=role.reasoning,
    )
    await loop.run(spec)
