"""S5a/S5b/G5: abstract finalization, beautification, and publication gate."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mmagent.mm.audit import audit_paper
from mmagent.mm.config.profiles import get_profile
from mmagent.mm.gates.g5 import check_g5
from mmagent.mm.guards.guards import page_guard
from mmagent.mm.pipeline.plot_runtime import run_question_plot_scripts
from mmagent.orchestration.role_leg import run_role_leg
from mmagent.providers.base import BaseProvider
from mmagent.state import events
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


def _default_render(root: Path) -> list[Path]:
    return render_pdf_pages(root)


async def _leg(
    db: Database, provider: BaseProvider, registry: ToolRegistry, policy: PathPolicy,
    run_id: str, *, stage: str, role_id: str, node: str, instructions: str,
    expected: list[ExpectedArtifact], question_num: int | None = None,
    image_paths: list[str] | None = None, cancel=None,
) -> str:
    return await run_role_leg(
        db, provider, registry, policy, run_id,
        stage_key=stage,
        role_id=role_id,
        node_key=node,
        instructions=instructions,
        expected_artifacts=expected,
        question_num=question_num,
        image_paths=image_paths,
        cancel=cancel,
    )

def _abstract_pass(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and bool(data.get("通过", data.get("pass", False)))


async def run_s5a(
    db: Database, provider: BaseProvider, registry: ToolRegistry, policy: PathPolicy,
    run_id: str, *, max_attempts: int = 2, cancel=None,
) -> dict[str, Any]:
    """Finalize the abstract with a closed-book restatement gate."""
    history: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        writer = await _leg(
            db, provider, registry, policy, run_id,
            stage="S5a", role_id="writer", node=f"S5a:摘要定稿{attempt}",
            instructions=(
                "根据完整成稿定稿 论文/0.摘要.tex；摘要自身必须能说明对象、方法、各问结果与可信性/局限。"
            ),
            expected=[ExpectedArtifact(rel_path="论文/0.摘要.tex", kind="text")], cancel=cancel,
        )
        if writer != "SUCCEEDED":
            history.append({"attempt": attempt, "pass": False, "reason": "writer_failed"})
            continue
        verdict = f"审稿/摘要复述_定稿{attempt}.json"
        reader = await _leg(
            db, provider, registry, policy, run_id,
            stage="S5a", role_id="blind_reader", node=f"S5a:复述门{attempt}",
            instructions=(
                f"只读 论文/0.摘要.tex，检查是否能复述研究对象、核心方法、各问主要结果、可信性/局限；"
                f"写 {verdict}，顶层给出 通过(boolean)。"
            ),
            expected=[ExpectedArtifact(rel_path=verdict)], cancel=cancel,
        )
        passed = reader == "SUCCEEDED" and _abstract_pass(policy.root / verdict)
        history.append({"attempt": attempt, "pass": passed})
        if passed:
            events.append_event(db, "checkpoint.s5a", {"attempt": attempt}, run_id=run_id)
            return {"pass": True, "attempts": history}
    return {"pass": False, "attempts": history}


def _page_issues(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        raw = data.get("页问题", data.get("问题", [])) or []
        if isinstance(raw, dict):
            raw = [raw]
        return [x for x in raw if isinstance(x, dict)]
    return []


def _question_from_issue(item: dict) -> int | None:
    text = " ".join(str(item.get(k, "")) for k in ("页", "定位", "问题", "修改指令"))
    m = re.search(r"(?:问题|问)\s*(\d+)", text)
    return int(m.group(1)) if m else None


async def _apply_beauty_issues(
    db: Database, provider: BaseProvider, registry: ToolRegistry, policy: PathPolicy,
    run_id: str, round_num: int, issues: list[dict], *, cancel=None,
) -> list[str]:
    failures: list[str] = []
    text_issues = [x for x in issues if str(x.get("目标", "文")) == "文"]
    figure_issues = [x for x in issues if str(x.get("目标", "")) == "图"]

    if text_issues:
        receipt = f"审稿/回执_美化R{round_num}_文.json"
        status = await _leg(
            db, provider, registry, policy, run_id,
            stage="S5b", role_id="writer", node=f"S5b:R{round_num}:文",
            instructions=(
                "只处理以下版面文字问题，不能改变模型事实或关键数字："
                + json.dumps(text_issues, ensure_ascii=False)
                + f"。写 {receipt} 记录改动证据。"
            ),
            expected=[ExpectedArtifact(rel_path=receipt)], cancel=cancel,
        )
        if status != "SUCCEEDED":
            failures.append("美化文路失败")

    groups: dict[int, list[dict]] = {}
    for item in figure_issues:
        q = _question_from_issue(item)
        if q is None:
            failures.append("图类美化意见无法定位到问题号")
            continue
        groups.setdefault(q, []).append(item)
    for q, group in groups.items():
        receipt = f"审稿/回执_美化R{round_num}_图问{q}.json"
        status = await _leg(
            db, provider, registry, policy, run_id,
            stage="S5b", role_id="plotter", node=f"S5b:R{round_num}:图问{q}",
            question_num=q,
            instructions=(
                "只处理以下图类版面问题，不改冻结结果："
                + json.dumps(group, ensure_ascii=False)
                + f"。写 {receipt} 记录改动证据。"
            ),
            expected=[ExpectedArtifact(rel_path=receipt)], cancel=cancel,
        )
        if status != "SUCCEEDED":
            failures.append(f"美化图路问{q}失败")
            continue
        execute_issues = await run_question_plot_scripts(
            registry, policy, q, cancel=cancel
        )
        failures.extend(execute_issues)
    return failures


async def run_s5b(
    db: Database, provider: BaseProvider, registry: ToolRegistry, policy: PathPolicy,
    run_id: str, *, profile: str = "标准", compile_paper: CompileFn | None = None,
    render_pages: RenderFn | None = None, cancel=None,
) -> dict[str, Any]:
    """Page-image beautification loop with figure/text routing and page guard."""
    cfg = get_profile(profile)
    compiler = compile_paper or _default_compile
    renderer = render_pages or _default_render
    initial = compiler(policy.root)
    if initial.get("rc") not in (0, None) or initial.get("errors"):
        return {"pass": False, "issues": ["美化前编译失败"], "rounds": []}
    baseline = int(initial.get("pages") or 0)
    if baseline <= 0:
        return {"pass": False, "issues": ["美化前页数不可得"], "rounds": []}

    rounds: list[dict[str, Any]] = []
    for round_num in range(1, cfg.美化轮数 + 1):
        try:
            pages = renderer(policy.root)
        except (OSError, RuntimeError, ValueError) as exc:
            return {
                "pass": False,
                "issues": [f"论文页图渲染失败: {exc}"],
                "rounds": rounds,
            }
        if not pages:
            return {"pass": False, "issues": ["论文页图缺失，无法执行美化页审"], "rounds": rounds}
        batches = [pages[i:i + 8] for i in range(0, len(pages), 8)]
        issues: list[dict] = []
        for batch_index, batch in enumerate(batches, 1):
            suffix = "" if len(batches) == 1 else f"_B{batch_index}"
            review_rel = f"审稿/美{round_num}{suffix}.json"
            rel_images = [p.relative_to(policy.root).as_posix() for p in batch]
            status = await _leg(
                db, provider, registry, policy, run_id,
                stage="S5b", role_id="beautifier",
                node=f"S5b:页审R{round_num}{suffix}",
                instructions=(
                    f"逐页视觉检查本批当前 PDF 页图，写 {review_rel}。"
                    "每条页问题必须含 目标=图|文、页、严重度、问题、修改指令；"
                    "必须依据附带图片本身，不得根据文件名猜测。"
                ),
                expected=[ExpectedArtifact(rel_path=review_rel)],
                image_paths=rel_images,
                cancel=cancel,
            )
            if status != "SUCCEEDED":
                return {
                    "pass": False,
                    "issues": [f"美化师页审失败 batch={batch_index}"],
                    "rounds": rounds,
                }
            issues.extend(_page_issues(policy.root / review_rel))
        failures = await _apply_beauty_issues(
            db, provider, registry, policy, run_id, round_num, issues, cancel=cancel
        )
        compiled = compiler(policy.root)
        new_pages = int(compiled.get("pages") or 0)
        page_ok, page_issue = page_guard(baseline, new_pages, baseline=baseline)
        rounds.append({
            "round": round_num, "issue_count": len(issues), "pages": new_pages,
            "page_guard": page_ok, "routing_failures": failures,
        })
        if compiled.get("rc") not in (0, None) or compiled.get("errors"):
            return {"pass": False, "issues": ["美化后编译失败"], "rounds": rounds}
        if not page_ok:
            return {"pass": False, "issues": [page_issue], "rounds": rounds}
        if failures:
            return {"pass": False, "issues": failures, "rounds": rounds}
        if not issues:
            break

    events.append_event(
        db, "checkpoint.s5b", {"beauty_baseline_pages": baseline, "rounds": rounds}, run_id=run_id
    )
    return {"pass": True, "issues": [], "rounds": rounds, "beauty_baseline_pages": baseline}


async def run_g5(
    db: Database, provider: BaseProvider, registry: ToolRegistry, policy: PathPolicy,
    run_id: str, *, beauty_baseline_pages: int, compile_paper: CompileFn | None = None,
    cancel=None,
) -> dict[str, Any]:
    """Final publication gate. R51 semantics: compile immediately before final defect review."""
    compiler = compile_paper or _default_compile
    compiled = compiler(policy.root)
    audit_paper(policy.root)
    pages = int(compiled.get("pages") or 0)
    ok, issues = check_g5(
        policy.root, beauty_baseline_pages=beauty_baseline_pages, current_pages=pages
    )
    if compiled.get("rc") not in (0, None) or compiled.get("errors"):
        ok = False
        issues = list(issues) + [f"G5 复核前编译失败: {compiled.get('errors')}"]

    review_rel = "审稿/G5复核.json"
    status = await _leg(
        db, provider, registry, policy, run_id,
        stage="G5", role_id="defect_hunter", node="G5:硬伤复核",
        instructions=(
            f"只基于刚刚编译的当前 PDF 做出版前硬伤复核，写 {review_rel}。"
            "顶层给出 通过(boolean)，并注明依据版本/页码。不得用旧 PDF 判断。"
        ),
        expected=[ExpectedArtifact(rel_path=review_rel)], cancel=cancel,
    )
    final_pass = False
    if status == "SUCCEEDED":
        try:
            data = json.loads((policy.root / review_rel).read_text(encoding="utf-8"))
            final_pass = isinstance(data, dict) and bool(data.get("通过", False))
        except (OSError, json.JSONDecodeError):
            final_pass = False
    if not final_pass:
        ok = False
        issues = list(issues) + ["G5 硬伤猎手复核未通过"]

    events.append_event(
        db, "gate.result", {"gate": "G5", "pass": bool(ok), "issues": issues}, run_id=run_id
    )
    return {"pass": bool(ok), "issues": issues, "pages": pages}
