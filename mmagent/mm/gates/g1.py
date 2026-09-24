"""G1 strategic-tournament gate."""
from __future__ import annotations

import json
from pathlib import Path

from mmagent.mm.contracts.s1_contracts import PrototypeResults, RouteScout


def check_g1(workspace_root: Path) -> tuple[bool, list[str]]:
    root = Path(workspace_root)
    issues: list[str] = []

    scout_path = root / "交接" / "路线侦察.json"
    proto_path = root / "交接" / "原型结果.json"
    plan_path = root / "交接" / "计划.json"
    try:
        scout = RouteScout.model_validate_json(scout_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"路线侦察缺失或 schema 错误: {exc}"]
    try:
        prototypes = PrototypeResults.model_validate_json(proto_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"原型结果缺失或 schema 错误: {exc}"]
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"计划.json 缺失或不可解析: {exc}"]

    scout_by_q = {q.编号: q for q in scout.问题清单}
    evidence = {(x.问题编号, x.路线名): x for x in prototypes.条目}
    for qnum, q in scout_by_q.items():
        required_routes = q.路线
        if scout.最难问题编号 is not None and qnum != scout.最难问题编号:
            required_routes = q.路线[:1]
        for route in required_routes:
            ev = evidence.get((qnum, route.路线名))
            if ev is None:
                issues.append(f"问{qnum} 路线 {route.路线名} 缺原型证据")
            elif ev.rc != 0:
                issues.append(f"问{qnum} 路线 {route.路线名} 原型执行失败 rc={ev.rc}")

    problems = plan.get("问题清单") or []
    if not problems:
        issues.append("计划 问题清单 为空")
    for item in problems:
        qnum = item.get("编号")
        if qnum not in scout_by_q:
            issues.append(f"计划问{qnum} 没有路线侦察")
            continue
        if not item.get("主方法"):
            issues.append(f"问{qnum} 缺主方法")
        deps = item.get("依赖问题")
        if deps is None:
            issues.append(f"问{qnum} 缺依赖问题")
        elif isinstance(deps, list) and qnum in deps:
            issues.append(f"问{qnum} 自依赖非法")
        tournament = item.get("锦标赛") or {}
        winner = tournament.get("优胜") if isinstance(tournament, dict) else None
        basis = tournament.get("依据") if isinstance(tournament, dict) else None
        route_names = {x.路线名 for x in scout_by_q[qnum].路线}
        if not winner or winner not in route_names:
            issues.append(f"问{qnum} 锦标赛优胜路线缺失或不在候选中")
        elif (qnum, winner) not in evidence:
            issues.append(f"问{qnum} 优胜路线 {winner} 没有真实原型证据")
        if not basis:
            issues.append(f"问{qnum} 锦标赛缺裁决依据")
    if not plan.get("叙事主线"):
        issues.append("计划缺叙事主线")
    return not issues, issues
