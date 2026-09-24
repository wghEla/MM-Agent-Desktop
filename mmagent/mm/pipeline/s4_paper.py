"""S4 paper swarm: narrative -> draft -> dual review -> integration -> abstract swarm -> G4."""
from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mmagent.agent.loop import AgentLoop, AgentTask
from mmagent.mm.audit import audit_paper
from mmagent.mm.config.profiles import get_profile
from mmagent.mm.config.thresholds import DEFAULT_THRESHOLDS
from mmagent.mm.gates.g4 import check_g4, check_narrative
from mmagent.mm.roles.prompts import get_system_prompt
from mmagent.mm.roles.registry import get_role
from mmagent.providers.base import BaseProvider
from mmagent.state import repositories
from mmagent.state.db import Database
from mmagent.tools.latex import LatexTool
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy
from mmagent.workspace.permissions import PermissionChecker

CompileFn = Callable[[Path], dict[str, Any]]


def _score(path: Path) -> float:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0
    if isinstance(data, dict):
        for key in ("总分", "章评分", "读者分", "分数", "score"):
            value = data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return 0.0


def _abstract_verdict(path: Path) -> tuple[bool, float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, 0.0
    if not isinstance(data, dict):
        return False, 0.0
    passed = bool(data.get("通过", data.get("pass", False)))
    score = 0.0
    for key in ("分数", "总分", "score"):
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            score = float(value)
            break
    return passed, score


async def _leg(
    db: Database, provider: BaseProvider, registry: ToolRegistry, policy: PathPolicy,
    run_id: str, *, role_id: str, node_key: str, instructions: str,
    expected: list[ExpectedArtifact], cancel=None
) -> str:
    role = get_role(role_id)
    loop = AgentLoop(
        db, provider, registry, PermissionChecker(role.permissions(), policy), policy, cancel=cancel
    )
    task = repositories.create_task(
        db, run_id=run_id, stage_key="S4", node_key=node_key, role_id=role_id
    )
    outcome = await loop.run(AgentTask(
        task_id=task.id, node_key=node_key, role_id=role_id,
        system_prompt=get_system_prompt(role_id), instructions=instructions,
        model="mock", reasoning=role.reasoning, expected_artifacts=expected,
    ))
    return outcome.status.value


def _default_compile(root: Path) -> dict[str, Any]:
    try:
        return LatexTool(root).compile("论文/论文.tex")
    except RuntimeError as exc:
        return {"rc": -1, "errors": [str(exc)], "pages": 0}


async def run_s4(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    *,
    problem_numbers: list[int],
    profile: str = "标准",
    compile_paper: CompileFn | None = None,
    cancel=None,
) -> dict[str, Any]:
    cfg = get_profile(profile)
    chapter_threshold = DEFAULT_THRESHOLDS.chapter_review_threshold
    review_history: list[dict[str, Any]] = []

    narrative_status = await _leg(
        db, provider, registry, policy, run_id,
        role_id="writer", node_key="S4:叙事底稿",
        instructions=(
            "写 交接/叙事底稿.md 与 交接/论点脊柱.json。"
            "叙事底稿按每问 ## 问题N 分节，每问至少150字白话，不写公式或工程文件名。"
        ),
        expected=[
            ExpectedArtifact(rel_path="交接/叙事底稿.md", kind="text"),
            ExpectedArtifact(rel_path="交接/论点脊柱.json"),
        ], cancel=cancel,
    )
    if narrative_status != "SUCCEEDED":
        return {"g4_pass": False, "g4_issues": ["叙事底稿腿失败"], "reviews": review_history}
    narrative_ok, narrative_issues = check_narrative(policy.root, problem_numbers)
    if not narrative_ok:
        return {"g4_pass": False, "g4_issues": narrative_issues, "reviews": review_history}

    draft_status = await _leg(
        db, provider, registry, policy, run_id,
        role_id="writer", node_key="S4:正文初稿",
        instructions="依据论点脊柱、结果声明、图证与实验记录写 论文/论文.tex；不得自行改变冻结事实。",
        expected=[ExpectedArtifact(rel_path="论文/论文.tex", kind="text")], cancel=cancel,
    )
    if draft_status != "SUCCEEDED":
        return {"g4_pass": False, "g4_issues": ["正文初稿腿失败"], "reviews": review_history}

    for round_num in range(1, cfg.章评轮数 + 1):
        chapter_rel = f"审稿/章评R{round_num}.json"
        reader_rel = f"审稿/读者R{round_num}.json"
        chapter_status = await _leg(
            db, provider, registry, policy, run_id,
            role_id="chapter_reviewer", node_key=f"S4:章评R{round_num}",
            instructions=f"评审论文各章并写 {chapter_rel}，顶层给出数值字段 总分。",
            expected=[ExpectedArtifact(rel_path=chapter_rel)], cancel=cancel,
        )
        reader_status = await _leg(
            db, provider, registry, policy, run_id,
            role_id="blind_reader", node_key=f"S4:闭卷R{round_num}",
            instructions=f"只读论文内容做闭卷理解测试并写 {reader_rel}，顶层给出数值字段 读者分。",
            expected=[ExpectedArtifact(rel_path=reader_rel)], cancel=cancel,
        )
        chapter_score = _score(policy.root / chapter_rel)
        reader_score = _score(policy.root / reader_rel)
        review_history.append({
            "round": round_num, "chapter_score": chapter_score, "reader_score": reader_score
        })
        if (
            chapter_status == "SUCCEEDED" and reader_status == "SUCCEEDED"
            and chapter_score >= chapter_threshold and reader_score >= chapter_threshold
        ):
            break
        if round_num >= cfg.章评轮数:
            break
        revision = await _leg(
            db, provider, registry, policy, run_id,
            role_id="writer", node_key=f"S4:定向修订R{round_num}",
            instructions=(
                f"只根据 {chapter_rel} 与 {reader_rel} 做定向修订；保持数字/公式事实不变，"
                "修改 论文/论文.tex。"
            ),
            expected=[ExpectedArtifact(rel_path="论文/论文.tex", kind="text")], cancel=cancel,
        )
        if revision != "SUCCEEDED":
            return {"g4_pass": False, "g4_issues": ["S4 定向修订失败"], "reviews": review_history}

    if review_history:
        last = review_history[-1]
        if last["chapter_score"] < chapter_threshold or last["reader_score"] < chapter_threshold:
            return {
                "g4_pass": False,
                "g4_issues": [
                    f"章评/闭卷末轮未达 {chapter_threshold:.1f}: "
                    f"{last['chapter_score']:.2f}/{last['reader_score']:.2f}"
                ],
                "reviews": review_history,
            }

    integrate = await _leg(
        db, provider, registry, policy, run_id,
        role_id="integrator", node_key="S4:统稿",
        instructions="统一全文语言与跨章衔接，只动语言层；写 审稿/统稿回执.json。",
        expected=[ExpectedArtifact(rel_path="审稿/统稿回执.json")], cancel=cancel,
    )
    if integrate != "SUCCEEDED":
        return {"g4_pass": False, "g4_issues": ["统稿腿失败"], "reviews": review_history}

    candidates: list[dict[str, Any]] = []
    for index in range(1, cfg.摘要变体数 + 1):
        candidate_rel = f"论文/摘要候选_{index}.tex"
        verdict_rel = f"审稿/摘要复述_{index}.json"
        status = await _leg(
            db, provider, registry, policy, run_id,
            role_id="writer", node_key=f"S4:摘要候选{index}",
            instructions=f"独立写摘要候选 {candidate_rel}；突出题目对象、方法、各问结果与可信性。",
            expected=[ExpectedArtifact(rel_path=candidate_rel, kind="text")], cancel=cancel,
        )
        if status != "SUCCEEDED":
            continue
        verdict_status = await _leg(
            db, provider, registry, policy, run_id,
            role_id="blind_reader", node_key=f"S4:摘要复述{index}",
            instructions=(
                f"只读 {candidate_rel} 做四要素复述门，写 {verdict_rel}；"
                "顶层必须有 通过(boolean) 与 分数(number)。"
            ),
            expected=[ExpectedArtifact(rel_path=verdict_rel)], cancel=cancel,
        )
        passed, score = _abstract_verdict(policy.root / verdict_rel)
        candidates.append({
            "index": index, "path": candidate_rel, "passed": passed and verdict_status == "SUCCEEDED",
            "score": score,
        })

    passing = [x for x in candidates if x["passed"]]
    if not passing:
        return {"g4_pass": False, "g4_issues": ["摘要复述门无候选通过"], "reviews": review_history, "abstracts": candidates}
    best = max(passing, key=lambda x: (x["score"], -x["index"]))
    shutil.copyfile(policy.root / best["path"], policy.root / "论文" / "0.摘要.tex")

    audit_paper(policy.root)
    compiler = compile_paper or _default_compile
    compile_result = compiler(policy.root)
    if compile_result.get("rc") not in (0, None) or compile_result.get("errors"):
        return {
            "g4_pass": False, "g4_issues": [f"论文编译失败: {compile_result.get('errors')}"],
            "reviews": review_history, "abstracts": candidates,
        }

    ok, issues = check_g4(policy.root)
    return {
        "g4_pass": ok, "g4_issues": issues, "reviews": review_history,
        "abstracts": candidates, "selected_abstract": best["index"],
    }
