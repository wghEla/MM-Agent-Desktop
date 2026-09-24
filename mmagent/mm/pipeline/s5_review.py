"""S5 review arena with role-bounded permissions, ledger verdicts and round checkpoints."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mmagent.agent.loop import AgentLoop, AgentTask
from mmagent.mm.audit import audit_paper
from mmagent.mm.gates.g4 import check_g4
from mmagent.mm.ledger.issue_ledger import Issue, IssueLedger
from mmagent.mm.roles.prompts import get_system_prompt
from mmagent.mm.roles.registry import get_role
from mmagent.providers.base import BaseProvider
from mmagent.state import events, repositories
from mmagent.state.db import Database
from mmagent.tools.latex import LatexTool, render_pdf_pages
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy
from mmagent.workspace.permissions import PermissionChecker

CompileFn = Callable[[Path], dict[str, Any]]
RenderFn = Callable[[Path], list[Path]]


def _default_compile(root: Path) -> dict[str, Any]:
    try:
        return LatexTool(root).compile("论文/论文.tex")
    except RuntimeError as exc:
        return {"rc": -1, "errors": [str(exc)], "pages": 0}


def _default_render(root: Path) -> list[Path]:
    return render_pdf_pages(root)


def _ledger_view(ledger: IssueLedger) -> list[dict[str, Any]]:
    return [asdict(item) for item in ledger.条目]


def _write_ledger_view(policy: PathPolicy, ledger: IssueLedger) -> None:
    payload = _ledger_view(ledger)
    review_view = policy.root / "审稿" / "审稿台账_视图.json"
    carrier = policy.root / "台账" / "审稿台账.json"
    review_view.parent.mkdir(parents=True, exist_ok=True)
    carrier.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    review_view.write_text(text, encoding="utf-8")
    carrier.write_text(text, encoding="utf-8")


def _mechanical_opinions(issues: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for issue in issues:
        severity = "正确性" if any(
            key in issue for key in ("溯源", "有效数字", "需求追踪", "编译错误")
        ) else "版式"
        out.append({
            "级别": severity,
            "目标": "文",
            "定位": "机械门",
            "问题": issue,
            "指令": "按机械门明细做最小修复，并提供可复核证据。",
            "验收": "下一轮机械门不再出现该条。",
            "来源": "机械门",
        })
    return out


def _artifact_for_review(role_id: str, round_num: int, suffix: str) -> str:
    if role_id == "reviewer":
        return f"审稿/审稿意见_轮{round_num}{suffix}.json"
    if role_id == "defect_hunter":
        return f"审稿/硬伤_轮{round_num}.json"
    if role_id == "judge_simulator":
        return f"审稿/评委模拟_轮{round_num}.json"
    raise KeyError(role_id)


def _extract_review_payload(path: Path) -> tuple[list[dict], list[dict]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)], []
    if not isinstance(data, dict):
        return [], []
    opinions = data.get("意见", data.get("最高优先级修改", [])) or []
    verdicts = data.get("裁定", data.get("逐条裁定", [])) or []
    if isinstance(opinions, dict):
        opinions = [opinions]
    if isinstance(verdicts, dict):
        verdicts = [verdicts]
    return (
        [x for x in opinions if isinstance(x, dict)],
        [x for x in verdicts if isinstance(x, dict)],
    )


async def _run_review_legs(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    round_num: int,
    *,
    cancel=None,
) -> tuple[list[dict], list[dict]]:
    opinions: list[dict] = []
    verdicts: list[dict] = []
    legs = [
        ("reviewer", "A"),
        ("reviewer", "B"),
        ("defect_hunter", ""),
        ("judge_simulator", ""),
    ]
    for role_id, suffix in legs:
        role = get_role(role_id)
        artifact = _artifact_for_review(role_id, round_num, suffix)
        checker = PermissionChecker(role.permissions(), policy)
        loop = AgentLoop(db, provider, registry, checker, policy, cancel=cancel)
        node = f"S5:R{round_num}:{role_id}{suffix}"
        task = repositories.create_task(
            db, run_id=run_id, stage_key="S5", node_key=node, role_id=role_id
        )
        outcome = await loop.run(AgentTask(
            task_id=task.id,
            node_key=node,
            role_id=role_id,
            system_prompt=get_system_prompt(role_id),
            instructions=(
                f"执行第{round_num}轮独立审稿并写 {artifact}。"
                "新意见写入 意见；若审稿台账视图中存在待复核条目，逐条给出 id、generation、裁定。"
            ),
            model="mock",
            reasoning=role.reasoning,
            expected_artifacts=[ExpectedArtifact(rel_path=artifact)],
        ))
        if outcome.status.value != "SUCCEEDED":
            continue
        op, ve = _extract_review_payload(policy.root / artifact)
        for item in op:
            item.setdefault("来源", role.display_name + suffix)
        opinions.extend(op)
        verdicts.extend(ve)
    return opinions, verdicts


_CHINESE_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _related_questions(issue: Issue) -> set[int]:
    text = f"{issue.定位} {issue.问题} {issue.指令}"
    out = {int(x) for x in re.findall(r"(?:问题|问)\s*(\d+)", text)}
    for ch, value in _CHINESE_NUM.items():
        if f"问题{ch}" in text or f"问{ch}" in text:
            out.add(value)
    return out


def _items_json(items: list[Issue]) -> str:
    payload = [
        {
            "id": x.id,
            "generation": x.generation,
            "级别": x.级别,
            "目标": x.目标,
            "定位": x.定位,
            "问题": x.问题,
            "指令": x.指令,
            "验收": x.验收,
        }
        for x in items
    ]
    return json.dumps(payload, ensure_ascii=False)


async def _run_rework_leg(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    round_num: int,
    *,
    target: str,
    items: list[Issue],
    question_num: int | None = None,
    cancel=None,
) -> list[dict]:
    role_id = {"算": "modeler", "图": "plotter", "文": "writer"}[target]
    role = get_role(role_id)
    vars = {"question": str(question_num)} if question_num is not None else {}
    checker = PermissionChecker(role.permissions(**vars), policy)
    loop = AgentLoop(db, provider, registry, checker, policy, cancel=cancel)
    suffix = f"问{question_num}" if question_num is not None else ""
    receipt_rel = f"审稿/回执_R{round_num}_{target}{suffix}.json"
    node = f"S5:R{round_num}:回炉{target}{suffix}"
    task = repositories.create_task(
        db, run_id=run_id, stage_key="S5", node_key=node, role_id=role_id
    )
    outcome = await loop.run(AgentTask(
        task_id=task.id,
        node_key=node,
        role_id=role_id,
        system_prompt=get_system_prompt(role_id),
        instructions=(
            "只处理下面点名的台账条目，不扩大修改范围。"
            f"条目={_items_json(items)}。修改完成后写 {receipt_rel}，"
            "每条回执包含 id、generation、改动、证据。"
        ),
        model="mock",
        reasoning=role.reasoning,
        expected_artifacts=[ExpectedArtifact(rel_path=receipt_rel)],
    ))
    if outcome.status.value != "SUCCEEDED":
        return []
    try:
        data = json.loads((policy.root / receipt_rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        data = data.get("回执", [data])
    return [x for x in (data or []) if isinstance(x, dict)]


async def _run_rework(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    round_num: int,
    ledger: IssueLedger,
    *,
    cancel=None,
) -> dict[str, Any]:
    stats: dict[str, Any] = {"算": 0, "图": 0, "文": 0, "unrouted": []}
    for target in ("算", "图"):
        items = ledger.待改条目(目标们=[target])
        groups: dict[int, list[Issue]] = {}
        for item in items:
            questions = _related_questions(item)
            if not questions:
                stats["unrouted"].append(item.id)
                continue
            for q in questions:
                groups.setdefault(q, []).append(item)
        for q, group in sorted(groups.items()):
            receipts = await _run_rework_leg(
                db, provider, registry, policy, run_id, round_num,
                target=target, items=group, question_num=q, cancel=cancel,
            )
            result = ledger.收回执(receipts, 腿名=f"回炉{target}问{q}")
            stats[target] += result["受理"]

    text_items = ledger.待改条目(目标们=["文"])
    if text_items:
        receipts = await _run_rework_leg(
            db, provider, registry, policy, run_id, round_num,
            target="文", items=text_items, cancel=cancel,
        )
        result = ledger.收回执(receipts, 腿名="回炉文")
        stats["文"] += result["受理"]
    return stats


async def run_s5(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    *,
    max_rounds: int = 4,
    compile_paper: CompileFn | None = None,
    render_pages: RenderFn | None = None,
    cancel=None,
) -> dict[str, Any]:
    """Run review rounds. The last round is review-only when still unconverged."""
    ledger = IssueLedger(前缀="审")
    rounds: list[dict[str, Any]] = []
    converged = False
    needs_escalation: list[str] = []
    compiler = compile_paper or _default_compile
    renderer = render_pages or _default_render

    for round_num in range(1, max_rounds + 1):
        compile_result = compiler(policy.root)
        render_issue: str | None = None
        if compile_result.get("rc") in (0, None) and not compile_result.get("errors"):
            try:
                renderer(policy.root)
            except (OSError, RuntimeError, ValueError) as exc:
                render_issue = f"页图渲染失败: {exc}"
        audit_paper(policy.root)
        gate_ok, gate_issues = check_g4(policy.root)
        mechanical = _mechanical_opinions(gate_issues)
        if render_issue:
            mechanical.append({
                "级别": "硬伤", "目标": "文", "定位": "页图",
                "问题": render_issue,
                "指令": "修复 PDF/页图渲染链路后重新编译渲染。",
                "验收": "当前 PDF 对应页图可重新生成。", "来源": "机械门",
            })
        if compile_result.get("rc") not in (0, None) or compile_result.get("errors"):
            mechanical.append({
                "级别": "硬伤", "目标": "文", "定位": "编译",
                "问题": f"编译失败: {compile_result.get('errors')}",
                "指令": "修复编译错误后重新编译。", "验收": "E=0", "来源": "机械门",
            })

        _write_ledger_view(policy, ledger)
        opinions, verdicts = await _run_review_legs(
            db, provider, registry, policy, run_id, round_num, cancel=cancel
        )
        verdict_stats = ledger.收裁定(verdicts, 轮次=round_num)
        missed_verdicts = ledger.待复核未裁()
        stats = ledger.并入(mechanical + opinions, round_num)

        converged, blocking = ledger.收敛()
        round_info: dict[str, Any] = {
            "round": round_num,
            "stats": stats,
            "verdicts": verdict_stats,
            "missed_verdicts": missed_verdicts,
            "converged": converged,
            "blocking": len(blocking),
        }
        rounds.append(round_info)
        _write_ledger_view(policy, ledger)
        events.append_event(
            db, "checkpoint.s5_round",
            {"round": round_num, "converged": converged, "ledger": ledger.摘要()},
            run_id=run_id,
        )

        if converged:
            break
        if round_num >= max_rounds:
            break

        for item in ledger.熔断候选(阈值=2):
            if item.级别 in ("硬伤", "正确性"):
                if item.id not in needs_escalation:
                    needs_escalation.append(item.id)
                continue
            ledger.搁置条目(item.id, "两次定向修订仍未消解")

        round_info["rework"] = await _run_rework(
            db, provider, registry, policy, run_id, round_num, ledger, cancel=cancel
        )
        _write_ledger_view(policy, ledger)

    return {
        "rounds": rounds,
        "converged": converged,
        "ledger_summary": ledger.摘要(),
        "needs_escalation": needs_escalation,
        "ledger": _ledger_view(ledger),
    }
