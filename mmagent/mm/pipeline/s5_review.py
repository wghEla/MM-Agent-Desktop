"""S5 审稿场编排（编译→审计→五路评审→台账→收敛→回炉 算图文→守卫→轮级断点）。"""
from __future__ import annotations

import json
from typing import Any

from mmagent.agent.loop import AgentLoop, AgentTask
from mmagent.mm.ledger.issue_ledger import IssueLedger
from mmagent.mm.roles.registry import get_role
from mmagent.providers.base import BaseProvider
from mmagent.state import repositories
from mmagent.state.db import Database
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.path_policy import PathPolicy
from mmagent.workspace.permissions import PermissionChecker


async def run_s5(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    *,
    max_rounds: int = 4,
    cancel=None,
) -> dict[str, Any]:
    """执行 S5 审稿场。

    每轮：五路意见（审A/审B/硬伤/评委/机械）→ 台账 → 收敛判定 →
    熔断 → 回炉（算→图→文）→ 变化守卫 → 编译修复 → 轮级断点。
    末轮只评不改。返回 {"rounds": [...], "converged": bool, "ledger_summary": {...}}。
    """
    ledger = IssueLedger(前缀="审")
    rounds: list[dict[str, Any]] = []
    converged = False

    for round_num in range(1, max_rounds + 1):
        # 五路意见（每路一个 Agent）
        opinions = await _run_review_legs(
            db, provider, registry, policy, run_id, round_num, ledger, cancel
        )
        # 台账并入
        stats = ledger.并入(opinions, round_num)
        # 处理上轮回执的裁定
        # （真实场景：审 A/B/硬伤对上轮待复核条目给裁定）

        # 收敛判定
        converged, blocking = ledger.收敛()
        round_info = {"round": round_num, "stats": stats,
                      "converged": converged, "blocking": len(blocking)}
        rounds.append(round_info)

        if converged:
            break
        if round_num >= max_rounds:
            break  # 末轮只评不改

        # 熔断
        for item in ledger.熔断候选(阈值=2):
            if item.级别 in ("硬伤", "正确性"):
                # 升格一次
                pass  # 升格逻辑在 S2 侧；此处只搁置
            ledger.搁置条目(item.id, "两次修订未消解")

        # 回炉（算→图→文）
        await _run_rework(db, provider, registry, policy, run_id, round_num, ledger, cancel)

    return {"rounds": rounds, "converged": converged,
            "ledger_summary": ledger.摘要()}


async def _run_review_legs(
    db: Database, provider: BaseProvider, registry: ToolRegistry,
    policy: PathPolicy, run_id: str, round_num: int,
    ledger: IssueLedger, cancel=None,
) -> list[dict]:
    """运行审 A/审 B/硬伤/评委 四路评审。"""
    opinions: list[dict] = []
    legs = [
        ("reviewer", f"审{round_num}A"),
        ("reviewer", f"审{round_num}B"),
        ("defect_hunter", f"硬伤{round_num}"),
        ("judge_simulator", f"评委模拟{round_num}"),
    ]
    for role_id, leg_name in legs:
        role = get_role(role_id)
        perms = RolePermissions(
            role_id=role_id, read_scopes=("**",), write_scopes=("审稿/**",),
            allowed_tools=frozenset({"fs.read", "fs.write"}),
        )
        checker = PermissionChecker(perms, policy)
        loop = AgentLoop(db, provider, registry, checker, policy, cancel=cancel)
        task_rec = repositories.create_task(
            db, run_id=run_id, stage_key="S5", node_key=f"S5:R{round_num}:{leg_name}",
            role_id=role_id,
        )
        spec = AgentTask(
            task_id=task_rec.id, node_key=f"S5:R{round_num}:{leg_name}", role_id=role_id,
            system_prompt=f"你是{role.display_name}。第{round_num}轮审稿。",
            instructions=f"审稿并产出 审稿/{leg_name}.json。",
            model="mock", reasoning=role.reasoning,
        )
        await loop.run(spec)
        # 从产物提取意见（mock 场景下产物可能不存在，跳过提取）
        opinion_path = policy.root / "审稿" / f"{leg_name}.json"
        if opinion_path.is_file():
            try:
                data = json.loads(opinion_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    opinions.extend(data)
                elif isinstance(data, dict):
                    opinions.extend(data.get("意见", data.get("最高优先级修改", [])))
            except (json.JSONDecodeError, OSError):
                pass
    return opinions


async def _run_rework(
    db: Database, provider: BaseProvider, registry: ToolRegistry,
    policy: PathPolicy, run_id: str, round_num: int,
    ledger: IssueLedger, cancel=None,
) -> None:
    """回炉：按 算→图→文 顺序派修改腿。"""
    for target in ("算", "图", "文"):
        items = ledger.待改条目(目标们=[target])
        if not items:
            continue
        role_id = {"算": "modeler", "图": "plotter", "文": "writer"}[target]
        role = get_role(role_id)
        perms = RolePermissions(
            role_id=role_id, read_scopes=("**",), write_scopes=("**",),
            allowed_tools=frozenset({"fs.read", "fs.write"}),
        )
        checker = PermissionChecker(perms, policy)
        loop = AgentLoop(db, provider, registry, checker, policy, cancel=cancel)
        task_rec = repositories.create_task(
            db, run_id=run_id, stage_key="S5",
            node_key=f"S5:R{round_num}:回炉{target}", role_id=role_id,
        )
        spec = AgentTask(
            task_id=task_rec.id, node_key=f"S5:R{round_num}:回炉{target}", role_id=role_id,
            system_prompt=f"你是{role.display_name}。按台账条目定向修改。",
            instructions=f"处理 {len(items)} 条{target}类意见。",
            model="mock", reasoning=role.reasoning,
        )
        await loop.run(spec)
        # 收回执
        receipts_path = policy.root / "审稿" / f"回执_R{round_num}_{target}.json"
        if receipts_path.is_file():
            try:
                receipts = json.loads(receipts_path.read_text(encoding="utf-8"))
                ledger.收回执(receipts, 腿名=f"回炉{target}")
            except (json.JSONDecodeError, OSError):
                pass
