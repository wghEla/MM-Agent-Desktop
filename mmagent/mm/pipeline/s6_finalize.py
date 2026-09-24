"""S6 final page review, final compile, delivery harvest and retrospective."""
from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mmagent.agent.loop import AgentLoop, AgentTask
from mmagent.mm.pipeline.plot_runtime import run_question_plot_scripts
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


async def _leg(
    db, provider, registry, policy, run_id, *, role_id, node, instructions,
    expected, image_paths: list[str] | None = None, cancel=None,
):
    role = get_role(role_id)
    loop = AgentLoop(
        db, provider, registry, PermissionChecker(role.permissions(), policy), policy, cancel=cancel
    )
    task = repositories.create_task(
        db, run_id=run_id, stage_key="S6", node_key=node, role_id=role_id
    )
    result = await loop.run(AgentTask(
        task_id=task.id, node_key=node, role_id=role_id,
        system_prompt=get_system_prompt(role_id), instructions=instructions,
        model="mock", reasoning=role.reasoning, expected_artifacts=expected,
        image_paths=list(image_paths or []),
    ))
    return result.status.value


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
    render_pages: RenderFn | None = None, cancel=None,
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
            expected=[ExpectedArtifact(rel_path=review_rel)],
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
        role = get_role("plotter")
        loop = AgentLoop(
            db, provider, registry,
            PermissionChecker(role.permissions(question=str(q)), policy), policy, cancel=cancel,
        )
        node = f"S6:终审改图问{q}"
        task = repositories.create_task(
            db, run_id=run_id, stage_key="S6", node_key=node, role_id="plotter"
        )
        receipt = f"审稿/回执_S6_图问{q}.json"
        outcome = await loop.run(AgentTask(
            task_id=task.id, node_key=node, role_id="plotter",
            system_prompt=get_system_prompt("plotter"),
            instructions=(
                "只修下面终审点名的图问题，不改冻结结果："
                + json.dumps(group, ensure_ascii=False)
                + f"。写 {receipt}。"
            ),
            model="mock", reasoning=role.reasoning,
            expected_artifacts=[ExpectedArtifact(rel_path=receipt)],
        ))
        if outcome.status.value != "SUCCEEDED":
            return {"pass": False, "issues": [f"S6 问{q}终审改图失败"]}
        execute_issues = await run_question_plot_scripts(
            registry, policy, q, cancel=cancel
        )
        if execute_issues:
            return {"pass": False, "issues": execute_issues}

    compiled = compiler(policy.root)
    if compiled.get("rc") not in (0, None) or compiled.get("errors"):
        return {"pass": False, "issues": [f"S6 final compile 失败: {compiled.get('errors')}"]}
    if not (policy.root / "论文" / "论文.pdf").is_file():
        return {"pass": False, "issues": ["S6 final compile 后论文.pdf 缺失"]}

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
