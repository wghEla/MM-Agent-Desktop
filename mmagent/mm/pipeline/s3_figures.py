"""S3 figure-evidence pipeline: plot -> execute -> review -> targeted revision -> G3."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmagent.mm.config.profiles import get_profile
from mmagent.mm.config.thresholds import DEFAULT_THRESHOLDS
from mmagent.mm.contracts.s3_contracts import FigureReview
from mmagent.mm.gates.g3 import check_g3
from mmagent.mm.pipeline.plot_runtime import run_question_plot_scripts
from mmagent.orchestration.role_leg import run_role_leg
from mmagent.orchestration.wave import WaveJob, run_status_wave
from mmagent.providers.base import BaseProvider
from mmagent.state.db import Database
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy


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
    return await run_role_leg(
        db, provider, registry, policy, run_id,
        stage_key="S3",
        role_id=role_id,
        node_key=node_key,
        instructions=instructions,
        expected_artifacts=expected,
        question_num=question_num,
        image_paths=image_paths,
        cancel=cancel,
    )

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

    plot_jobs: list[WaveJob[str]] = []
    captions = {q: f"交接/图注素材_问题{q}.json" for q in problem_numbers}
    for q in problem_numbers:
        caption = captions[q]

        async def write_plots(*, question=q, caption_rel=caption) -> str:
            return await _run_agent_leg(
                db, provider, registry, policy, run_id,
                role_id="plotter",
                node_key=f"S3:问{question}:绘图",
                instructions=(
                    f"为问题{question}生成可复现绘图脚本和图片；写 {caption_rel}。"
                    "只写脚本，由 Runtime 统一执行。"
                ),
                expected=[ExpectedArtifact(rel_path=caption_rel)],
                question_num=question,
                cancel=cancel,
            )

        plot_jobs.append(WaveJob(f"问{q}:绘图", write_plots))

    plot_wave = await run_status_wave(
        db,
        run_id,
        plot_jobs,
        cancel=cancel,
        wave_key="S3:绘图脚本",
        serial=provider.protocol == "mock",
    )

    for q in problem_numbers:
        caption = captions[q]
        if plot_wave.results.get(f"问{q}:绘图") != "SUCCEEDED":
            return {
                "g3_pass": False,
                "g3_issues": [f"问{q} 绘图腿失败"],
                "reviews": history,
            }

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
            review_jobs: list[WaveJob[str]] = []
            review_names: list[str] = []
            for batch_index, batch in enumerate(batches, 1):
                suffix = "" if len(batches) == 1 else f"_B{batch_index}"
                review_rel = f"审稿/图评R{round_num}_问题{q}{suffix}.json"
                review_rels.append(review_rel)
                rel_images = [p.relative_to(policy.root).as_posix() for p in batch]
                name = f"图评{batch_index}"
                review_names.append(name)

                async def review_batch(
                    *,
                    question=q,
                    review_round=round_num,
                    suffix_key=suffix,
                    review_path=review_rel,
                    images=tuple(rel_images),
                ) -> str:
                    return await _run_agent_leg(
                        db, provider, registry, policy, run_id,
                        role_id="figure_reviewer",
                        node_key=f"S3:问{question}:图评R{review_round}{suffix_key}",
                        instructions=(
                            f"视觉评审问题{question}这一批实际图片，写 {review_path}；"
                            f"顶层给出数值字段 总分，固定通过阈值为 {threshold:.1f}。"
                            "必须依据随任务附带的图片本身，不得只读文件名推测。"
                        ),
                        expected=[ExpectedArtifact(rel_path=review_path, schema_model=FigureReview)],
                        question_num=question,
                        image_paths=list(images),
                        cancel=cancel,
                    )

                review_jobs.append(WaveJob(name, review_batch))

            review_wave = await run_status_wave(
                db,
                run_id,
                review_jobs,
                cancel=cancel,
                wave_key=f"S3:问{q}:图评R{round_num}",
                serial=provider.protocol == "mock",
            )
            for name, review_rel in zip(review_names, review_rels, strict=True):
                status = review_wave.results.get(name, "FAILED")
                score = _review_score(policy.root / review_rel)
                batch_scores.append(score)
                batch_ok = batch_ok and status == "SUCCEEDED"
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
