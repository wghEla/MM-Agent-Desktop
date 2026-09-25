"""S3 figure-evidence pipeline: plot -> execute -> review -> targeted revision -> G3."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmagent.agent.loop import AgentLoop, AgentTask
from mmagent.mm.config.profiles import get_profile
from mmagent.mm.config.thresholds import DEFAULT_THRESHOLDS
from mmagent.mm.gates.g3 import check_g3
from mmagent.mm.pipeline.plot_runtime import run_question_plot_scripts
from mmagent.mm.roles.prompts import get_system_prompt
from mmagent.mm.roles.registry import get_role
from mmagent.providers.base import BaseProvider
from mmagent.state import repositories
from mmagent.state.db import Database
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy
from mmagent.workspace.permissions import PermissionChecker


def _review_score(path: Path) -> float:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0
    if isinstance(data, dict):
        for key in ("总分", "图评分", "分数", "score"):
            value = data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return 0.0


async def _run_agent_leg(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    *,
    role_id: str,
    node_key: str,
    instructions: str,
    expected: list[ExpectedArtifact],
    question_num: int | None = None,
    image_paths: list[str] | None = None,
    cancel=None,
) -> str:
    role = get_role(role_id)
    permission_vars = {"question": str(question_num)} if question_num is not None else {}
    checker = PermissionChecker(role.permissions(**permission_vars), policy)
    loop = AgentLoop(db, provider, registry, checker, policy, cancel=cancel)
    task = repositories.create_task(
        db, run_id=run_id, stage_key="S3", node_key=node_key, role_id=role_id
    )
    spec = AgentTask(
        task_id=task.id,
        node_key=node_key,
        role_id=role_id,
        system_prompt=get_system_prompt(role_id),
        instructions=instructions,
        model="mock",
        reasoning=role.reasoning,
        expected_artifacts=expected,
        image_paths=list(image_paths or []),
    )
    outcome = await loop.run(spec)
    return outcome.status.value


async def run_s3(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    *,
    problem_numbers: list[int],
    profile: str = "标准",
    cancel=None,
) -> dict[str, Any]:
    """Run S3 and return review history plus G3 result.

    Plotters write scripts; the trusted runtime executes them. Figure reviewers
    then score the generated evidence. Scores below the fixed threshold trigger
    targeted plotter revision until the profile round budget is exhausted.
    """
    rounds = get_profile(profile).图评轮数
    threshold = DEFAULT_THRESHOLDS.figure_review_threshold
    history: list[dict[str, Any]] = []

    for q in problem_numbers:
        caption = f"交接/图注素材_问题{q}.json"
        status = await _run_agent_leg(
            db, provider, registry, policy, run_id,
            role_id="plotter",
            node_key=f"S3:问{q}:绘图",
            instructions=(
                f"为问题{q}生成可复现绘图脚本和图片；写 {caption}。"
                "只写脚本，由 Runtime 统一执行。"
            ),
            expected=[ExpectedArtifact(rel_path=caption)],
            question_num=q,
            cancel=cancel,
        )
        if status != "SUCCEEDED":
            return {"g3_pass": False, "g3_issues": [f"问{q} 绘图腿失败"], "reviews": history}

        exec_issues = await run_question_plot_scripts(registry, policy, q, cancel=cancel)
        if exec_issues:
            return {"g3_pass": False, "g3_issues": exec_issues, "reviews": history}

        for round_num in range(1, rounds + 1):
            images = sorted(
                p for p in (policy.root / "求解" / f"问题{q}" / "图片").glob("*.png")
                if p.is_file()
            )
            if not images:
                return {
                    "g3_pass": False,
                    "g3_issues": [f"问{q} 无实际图片可供图评"],
                    "reviews": history,
                }
            batches = [images[i:i + 8] for i in range(0, len(images), 8)]
            batch_scores: list[float] = []
            batch_ok = True
            review_rels: list[str] = []
            for batch_index, batch in enumerate(batches, 1):
                suffix = "" if len(batches) == 1 else f"_B{batch_index}"
                review_rel = f"审稿/图评R{round_num}_问题{q}{suffix}.json"
                review_rels.append(review_rel)
                rel_images = [p.relative_to(policy.root).as_posix() for p in batch]
                review_status = await _run_agent_leg(
                    db, provider, registry, policy, run_id,
                    role_id="figure_reviewer",
                    node_key=f"S3:问{q}:图评R{round_num}{suffix}",
                    instructions=(
                        f"视觉评审问题{q}这一批实际图片，写 {review_rel}；"
                        f"顶层给出数值字段 总分，固定通过阈值为 {threshold:.1f}。"
                        "必须依据随任务附带的图片本身，不得只读文件名推测。"
                    ),
                    expected=[ExpectedArtifact(rel_path=review_rel)],
                    question_num=q,
                    image_paths=rel_images,
                    cancel=cancel,
                )
                score = _review_score(policy.root / review_rel)
                batch_scores.append(score)
                batch_ok = batch_ok and review_status == "SUCCEEDED"
            score = min(batch_scores) if batch_scores else 0.0
            history.append({
                "question": q,
                "round": round_num,
                "score": score,
                "batches": len(batches),
            })
            if batch_ok and score >= threshold:
                break
            if round_num >= rounds:
                break

            revision_status = await _run_agent_leg(
                db, provider, registry, policy, run_id,
                role_id="plotter",
                node_key=f"S3:问{q}:修图R{round_num}",
                instructions=(
                    f"只根据这些图评 {review_rels} 定向修改问题{q}的绘图脚本/图，保持结果事实不变；"
                    f"同步更新 {caption}。"
                ),
                expected=[ExpectedArtifact(rel_path=caption)],
                question_num=q,
                cancel=cancel,
            )
            if revision_status != "SUCCEEDED":
                return {"g3_pass": False, "g3_issues": [f"问{q} 修图腿失败"], "reviews": history}
            exec_issues = await run_question_plot_scripts(registry, policy, q, cancel=cancel)
            if exec_issues:
                return {"g3_pass": False, "g3_issues": exec_issues, "reviews": history}

    low_scores = [
        r for r in history
        if r["round"] == max(x["round"] for x in history if x["question"] == r["question"])
        and r["score"] < threshold
    ]
    ok, issues = check_g3(policy.root)
    if low_scores:
        issues = list(issues) + [
            "图评末轮未达阈值: "
            + ", ".join(f"问{x['question']}={x['score']:.2f}" for x in low_scores)
        ]
        ok = False
    return {"g3_pass": ok, "g3_issues": issues, "reviews": history}
