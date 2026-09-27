"""S6 final page review, final compile, delivery harvest and retrospective."""
from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mmagent.mm.audit import audit_paper
from mmagent.mm.contracts.final_contracts import PageReviewArtifact, PublicationReviewVerdict
from mmagent.mm.gates.g5 import check_g5
from mmagent.mm.pipeline.compile_runtime import run_compile
from mmagent.mm.pipeline.plot_runtime import run_question_plot_scripts
from mmagent.orchestration.role_leg import run_role_leg
from mmagent.providers.base import BaseProvider
from mmagent.state import events, repositories
from mmagent.state.db import Database
from mmagent.tools.latex import LatexTool, render_pdf_pages
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy

CompileFn = Callable[[Path], dict[str, Any]]
RenderFn = Callable[[Path], list[Path]]


def _default_compile(root: Path) -> dict[str, Any]:
    try:
        return LatexTool(root).compile("论文/论文.tex")
    except RuntimeError as exc:
        return {"rc": -1, "errors": [str(exc)], "pages": 0}


async def _leg(
    db, provider, registry, policy, run_id, *, role_id, node, instructions,
    expected, question_num: int | None = None,
    image_paths: list[str] | None = None, cancel=None,
):
    return await run_role_leg(
        db, provider, registry, policy, run_id,
        stage_key="S6",
        role_id=role_id,
        node_key=node,
        instructions=instructions,
        expected_artifacts=expected,
        question_num=question_num,
        image_paths=image_paths,
        cancel=cancel,
    )


def _final_issues(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        raw = data.get("页问题", data.get("问题", [])) or []
        return raw if isinstance(raw, list) else [raw]
    return data if isinstance(data, list) else []


def _harvest(root: Path) -> list[str]:
    delivery = root / "交付"
    delivery.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    pdf = root / "论文" / "论文.pdf"
    if pdf.is_file():
        shutil.copy2(pdf, delivery / "论文.pdf")
        copied.append("论文.pdf")
    for name, source in (
        ("论文源码", root / "论文"),
        ("求解源码", root / "求解"),
        ("交接", root / "交接"),
        ("台账", root / "台账"),
        ("审稿", root / "审稿"),
    ):
        if source.is_dir():
            target = delivery / name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            copied.append(name)
    return copied


def _run_metrics(db: Database, run_id: str) -> dict[str, Any]:
    evs = events.query_events(db, run_id=run_id, limit=10000)
    counts: dict[str, int] = {}
    for event in evs:
        counts[event.type] = counts.get(event.type, 0) + 1
    tasks = repositories.list_tasks(db, run_id)
    stages: dict[str, int] = {}
    for task in tasks:
        stage = task.node_key.split(":", 1)[0]
        stages[stage] = stages.get(stage, 0) + 1
    return {"事件数": len(evs), "事件类型": counts, "腿数": len(tasks), "阶段腿数": stages}


async def run_s6(
    db: Database, provider: BaseProvider, registry: ToolRegistry, policy: PathPolicy,
    run_id: str, *, compile_paper: CompileFn | None = None,
    render_pages: RenderFn | None = None,
    beauty_baseline_pages: int | None = None,
    cancel=None,
) -> dict[str, Any]:
    compiler = compile_paper or _default_compile
    renderer = render_pages or render_pdf_pages
    try:
        pages = renderer(policy.root)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"pass": False, "issues": [f"S6 页图渲染失败: {exc}"]}
    if not pages:
        return {"pass": False, "issues": ["S6 无页图，不能逐页终审"]}

    batches = [pages[i:i + 8] for i in range(0, len(pages), 8)]
    issues: list[dict] = []
    for batch_index, batch in enumerate(batches, 1):
        suffix = "" if len(batches) == 1 else f"_B{batch_index}"
        review_rel = f"审稿/终审_1{suffix}.json"
        rel_images = [p.relative_to(policy.root).as_posix() for p in batch]
        review = await _leg(
            db, provider, registry, policy, run_id,
            role_id="beautifier", node=f"S6:逐页终审{suffix}",
            instructions=(
                f"逐页视觉检查本批当前 PDF 页图并写 {review_rel}；"
                "只列必须修的提交级问题，每条含页、严重度、目标、问题、修改指令；"
                "必须依据附带图片本身，不得根据文件名猜测。"
            ),
            expected=[ExpectedArtifact(rel_path=review_rel, schema_model=PageReviewArtifact)],
            image_paths=rel_images,
            cancel=cancel,
        )
        if review != "SUCCEEDED":
            return {
                "pass": False,
                "issues": [f"S6 逐页终审失败 batch={batch_index}"],
            }
        issues.extend(_final_issues(policy.root / review_rel))
    text_issues = [
        x for x in issues if isinstance(x, dict) and str(x.get("目标", "文")) == "文"
    ]
    figure_issues = [
        x for x in issues if isinstance(x, dict) and str(x.get("目标", "")) == "图"
    ]
    if text_issues:
        receipt = "审稿/回执_S6_文.json"
        fix = await _leg(
            db, provider, registry, policy, run_id,
            role_id="writer", node="S6:终审整改",
            instructions=(
                "只修下面终审点名的文字/排版问题，不改冻结事实："
                + json.dumps(text_issues, ensure_ascii=False)
                + f"。写 {receipt}。"
            ),
            expected=[ExpectedArtifact(rel_path=receipt)], cancel=cancel,
        )
        if fix != "SUCCEEDED":
            return {"pass": False, "issues": ["S6 终审整改失败"]}

    groups: dict[int, list[dict]] = {}
    for item in figure_issues:
        text = " ".join(
            str(item.get(k, "")) for k in ("页", "定位", "问题", "修改指令")
        )
        match = re.search(r"(?:问题|问)\s*(\d+)", text)
        if not match:
            return {"pass": False, "issues": ["S6 图类终审问题无法定位到问题号"]}
        groups.setdefault(int(match.group(1)), []).append(item)

    for q, group in groups.items():
        node = f"S6:终审改图问{q}"
        receipt = f"审稿/回执_S6_图问{q}.json"
        status = await _leg(
            db, provider, registry, policy, run_id,
            role_id="plotter",
            node=node,
            question_num=q,
            instructions=(
                "只修下面终审点名的图问题，不改冻结结果："
                + json.dumps(group, ensure_ascii=False)
                + f"。写 {receipt}。"
            ),
            expected=[ExpectedArtifact(rel_path=receipt)],
            cancel=cancel,
        )
        if status != "SUCCEEDED":
            return {"pass": False, "issues": [f"S6 问{q}终审改图失败"]}
        execute_issues = await run_question_plot_scripts(
            registry, policy, q, cancel=cancel
        )
        if execute_issues:
            return {"pass": False, "issues": execute_issues}

    compiled = await run_compile(compiler, policy.root, cancel=cancel)
    if compiled.get("rc") not in (0, None) or compiled.get("errors"):
        return {"pass": False, "issues": [f"S6 final compile 失败: {compiled.get('errors')}"]}
    if not (policy.root / "论文" / "论文.pdf").is_file():
        return {"pass": False, "issues": ["S6 final compile 后论文.pdf 缺失"]}

    # Terminal publication verification must certify the *post-S6-fix*
    # revision, not the older revision that passed G5 before S6 edits.
    audit_paper(policy.root)
    terminal_ok, terminal_issues = check_g5(
        policy.root,
        beauty_baseline_pages=beauty_baseline_pages,
        current_pages=int(compiled.get("pages") or 0),
    )
    if not terminal_ok:
        events.append_event(
            db, "s6.terminal_verify_failed", {"issues": terminal_issues}, run_id=run_id
        )
        return {
            "pass": False,
            "issues": [f"S6 terminal publication gate 失败: {terminal_issues}"],
        }

    # Fresh terminal current-PDF visual review on the post-S6-fix revision.
    # Re-render *after* the final compile; fs.read cannot inspect PDF/image
    # pixels, so the page images must be attached explicitly to the role leg.
    try:
        final_pages = renderer(policy.root)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"pass": False, "issues": [f"S6 终态页图渲染失败: {exc}"]}
    if not final_pages:
        return {"pass": False, "issues": ["S6 终态页图缺失，不能执行出版终审"]}

    terminal_batches = [
        final_pages[i:i + 8] for i in range(0, len(final_pages), 8)
    ]
    for batch_index, batch in enumerate(terminal_batches, 1):
        suffix = "" if len(terminal_batches) == 1 else f"_B{batch_index}"
        terminal_review_rel = f"审稿/S6终审复核{suffix}.json"
        rel_images = [p.relative_to(policy.root).as_posix() for p in batch]
        review_status = await _leg(
            db, provider, registry, policy, run_id,
            role_id="defect_hunter", node=f"S6:出版终审{suffix}",
            instructions=(
                f"只基于随任务附带的最终候选 PDF 页图做出版终审，写 {terminal_review_rel}。"
                "顶层给出 通过(boolean)，并注明依据版本/页码。不得用旧 PDF 判断。"
            ),
            expected=[
                ExpectedArtifact(
                    rel_path=terminal_review_rel,
                    schema_model=PublicationReviewVerdict,
                )
            ],
            image_paths=rel_images,
            cancel=cancel,
        )
        terminal_review_pass = False
        if review_status == "SUCCEEDED":
            try:
                data = json.loads(
                    (policy.root / terminal_review_rel).read_text(encoding="utf-8")
                )
                terminal_review_pass = (
                    isinstance(data, dict) and bool(data.get("通过", False))
                )
            except (OSError, json.JSONDecodeError):
                terminal_review_pass = False
        if not terminal_review_pass:
            events.append_event(
                db,
                "s6.terminal_review_failed",
                {
                    "status": review_status,
                    "node": f"S6:出版终审{suffix}",
                    "batch": batch_index,
                },
                run_id=run_id,
            )
            return {
                "pass": False,
                "issues": [f"S6 出版终审复核未通过 batch={batch_index}"],
            }

    metrics = _run_metrics(db, run_id)
    metrics_path = policy.root / "审稿" / "回流账.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    retro = await _leg(
        db, provider, registry, policy, run_id,
        role_id="retrospector", node="S6:复盘",
        instructions=(
            "读取日志/台账/审稿/交接以及 审稿/回流账.json，写 审稿/复盘报告.json。"
            "必须引用量化回流账，区分一次性故障和可复现病根。"
        ),
        expected=[ExpectedArtifact(rel_path="审稿/复盘报告.json")], cancel=cancel,
    )
    if retro != "SUCCEEDED":
        return {"pass": False, "issues": ["复盘官失败"]}

    copied = _harvest(policy.root)
    events.append_event(
        db, "checkpoint.s6_complete", {"delivery": copied, "metrics": metrics}, run_id=run_id
    )
    return {"pass": True, "issues": [], "delivery": copied, "metrics": metrics}
