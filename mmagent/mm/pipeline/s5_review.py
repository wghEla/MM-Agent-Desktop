"""S5 review arena with role-bounded permissions, ledger verdicts and round checkpoints."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from mmagent.mm.audit import audit_paper
from mmagent.mm.contracts.degraded_release import upsert_degraded_review_issue
from mmagent.mm.contracts.repair_receipts import ModelRepairReceiptArtifact
from mmagent.mm.contracts.s5_contracts import ReviewArtifact
from mmagent.mm.gates.g4 import check_g4
from mmagent.mm.ledger.issue_ledger import (
    Issue,
    IssueLedger,
    merge_channel_verdicts,
)
from mmagent.mm.pipeline.compile_runtime import run_compile
from mmagent.mm.pipeline.guarded_repair import guarded_text_repair
from mmagent.mm.pipeline.plot_runtime import run_question_plot_scripts
from mmagent.mm.pipeline.s2_model import (
    run_verified_question_escalation,
    run_verified_question_recompute,
)
from mmagent.mm.retention import (
    ensure_paper_snapshot as _ensure_shared_snapshot,
)
from mmagent.mm.retention import (
    restore_paper_snapshot as _restore_shared_snapshot,
)
from mmagent.mm.retention import retention_decision as _retention_decision
from mmagent.mm.roles.registry import get_role
from mmagent.orchestration.dag import all_downstreams, build_dependency_graph, topological_layers
from mmagent.orchestration.role_leg import run_role_leg
from mmagent.orchestration.wave import WaveJob, run_status_wave
from mmagent.providers.base import BaseProvider
from mmagent.state import events
from mmagent.state.db import Database
from mmagent.tools.latex import LatexTool, render_pdf_pages
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy

CompileFn = Callable[[Path], dict[str, Any]]
RenderFn = Callable[[Path], list[Path]]


@dataclass(frozen=True)
class ReviewAssessment:
    opinions: list[dict]
    verdicts: list[dict]
    relative_judgment: str | None = None
    score: float | None = None


@dataclass(frozen=True)
class ReviewBatch:
    opinions: list[dict]
    channel_verdicts: list[tuple[str, list[dict]]]
    relative_judgment: str | None
    score: float | None


def _normalize_relative(value: Any) -> str | None:
    raw = str(value or "").strip()
    if raw.startswith(("更差", "差")):
        return "更差"
    if raw.startswith(("更好", "好")):
        return "更好"
    if raw:
        return "持平"
    return None


def _ensure_paper_snapshot(policy: PathPolicy, round_num: int) -> int:
    return _ensure_shared_snapshot(policy, "s5", round_num)


def _restore_paper_snapshot(policy: PathPolicy, round_num: int) -> int:
    return _restore_shared_snapshot(policy, "s5", round_num)


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


def _parse_review_assessment(path: Path) -> ReviewAssessment:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ReviewAssessment([], [])
    if isinstance(data, list):
        return ReviewAssessment([x for x in data if isinstance(x, dict)], [])
    if not isinstance(data, dict):
        return ReviewAssessment([], [])

    opinions = data.get("意见", data.get("最高优先级修改", [])) or []
    verdicts = (
        data.get("裁定", data.get("逐条裁定", data.get("逐项", []))) or []
    )
    if isinstance(opinions, dict):
        opinions = [opinions]
    if isinstance(verdicts, dict):
        verdicts = [verdicts]

    score: float | None = None
    for key in ("总分", "分数"):
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            score = float(value)
            break

    return ReviewAssessment(
        opinions=[x for x in opinions if isinstance(x, dict)],
        verdicts=[x for x in verdicts if isinstance(x, dict)],
        relative_judgment=_normalize_relative(
            data.get("相对判断", data.get("相对"))
        ),
        score=score,
    )


def _extract_review_payload(path: Path) -> tuple[list[dict], list[dict]]:
    """Backward-compatible focused parser used by older tests/helpers."""
    assessment = _parse_review_assessment(path)
    return assessment.opinions, assessment.verdicts


def _sample_representative_pages(pages: list[Path], limit: int = 8) -> list[Path]:
    if len(pages) <= limit:
        return pages
    if limit <= 1:
        return [pages[0]]
    indices = {
        round(i * (len(pages) - 1) / (limit - 1))
        for i in range(limit)
    }
    return [pages[i] for i in sorted(indices)]


async def _run_review_legs(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    round_num: int,
    *,
    page_images: list[Path] | None = None,
    cancel=None,
) -> ReviewBatch:
    opinions: list[dict] = []
    channel_verdicts: list[tuple[str, list[dict]]] = []
    relative_judgments: list[str] = []
    reviewer_scores: list[float] = []
    legs = [
        ("reviewer", "A"),
        ("reviewer", "B"),
        ("defect_hunter", ""),
        ("judge_simulator", ""),
    ]

    jobs: list[WaveJob[str]] = []
    artifacts: dict[str, tuple[str, str, str]] = {}
    for role_id, suffix in legs:
        role = get_role(role_id)
        artifact = _artifact_for_review(role_id, round_num, suffix)
        node = f"S5:R{round_num}:{role_id}{suffix}"
        name = f"{role_id}{suffix}"
        visual_paths: list[str] = []
        instructions = (
            f"执行第{round_num}轮独立审稿并写 {artifact}。"
            "新意见写入 意见；若审稿台账视图中存在待复核条目，逐条给出 "
            "id、generation、裁定、理由。"
            + (
                " 同时对比上一版给顶层 相对判断=更好|持平|更差。"
                if round_num > 1
                else ""
            )
            + (" 审稿员顶层给 1-10 总分。" if role_id == "reviewer" else "")
        )
        if role_id == "judge_simulator":
            selected = _sample_representative_pages(list(page_images or []))
            visual_paths = [p.relative_to(policy.root).as_posix() for p in selected]
            instructions += (
                " 你是页图评委，只依据随任务附带的当前 PDF 代表页判断第一印象与版式；"
                "看不到的内容必须弃权，不得推测。"
            )
        artifacts[name] = (role_id, suffix, artifact)

        async def run_review_leg(
            *,
            role_key=role_id,
            node_key=node,
            prompt=instructions,
            expected_artifact=artifact,
            images=tuple(visual_paths),
        ) -> str:
            return await run_role_leg(
                db,
                provider,
                registry,
                policy,
                run_id,
                stage_key="S5",
                role_id=role_key,
                node_key=node_key,
                instructions=prompt,
                expected_artifacts=[ExpectedArtifact(rel_path=expected_artifact, schema_model=ReviewArtifact)],
                image_paths=list(images),
                cancel=cancel,
            )

        jobs.append(WaveJob(name, run_review_leg))

    wave = await run_status_wave(
        db,
        run_id,
        jobs,
        cancel=cancel,
        wave_key=f"S5:审稿R{round_num}",
        serial=provider.protocol == "mock",
        timeout_s=3600,
    )

    for role_id, suffix in legs:
        name = f"{role_id}{suffix}"
        if wave.results.get(name) != "SUCCEEDED":
            continue
        _, _, artifact = artifacts[name]
        assessment = _parse_review_assessment(policy.root / artifact)
        role = get_role(role_id)
        for item in assessment.opinions:
            item.setdefault("来源", role.display_name + suffix)
        opinions.extend(assessment.opinions)
        channel_verdicts.append((role_id, assessment.verdicts))
        if assessment.relative_judgment:
            relative_judgments.append(assessment.relative_judgment)
        if role_id == "reviewer" and assessment.score is not None:
            reviewer_scores.append(assessment.score)

    relative = (
        "更差"
        if "更差" in relative_judgments
        else (
            "更好"
            if "更好" in relative_judgments
            else ("持平" if relative_judgments else None)
        )
    )
    score = (
        sum(reviewer_scores) / len(reviewer_scores)
        if reviewer_scores
        else None
    )
    return ReviewBatch(
        opinions=opinions,
        channel_verdicts=channel_verdicts,
        relative_judgment=relative,
        score=score,
    )

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


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _flatten_scalars(value: Any, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten_scalars(child, child_prefix))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_prefix = f"{prefix}[{index}]"
            out.update(_flatten_scalars(child, child_prefix))
    elif value is not None:
        out[prefix or "$"] = str(value)
    return out


def _calc_cascade_questions(policy: PathPolicy, source_q: int) -> list[int]:
    plan_path = policy.root / "交接" / "计划.json"
    plan = _read_json_object(plan_path)
    rows = plan.get("问题清单", [])
    if not isinstance(rows, list):
        return [source_q]
    graph = build_dependency_graph(rows)
    affected = {source_q, *all_downstreams(graph, source_q)}
    ordered: list[int] = []
    for layer in topological_layers(graph):
        for q in layer:
            if q in affected:
                ordered.append(q)
    return ordered or [source_q]


def _write_calc_change_manifests(
    policy: PathPolicy,
    before: dict[int, dict[str, Any]],
    questions: list[int],
) -> None:
    handoff = policy.root / "交接"
    handoff.mkdir(parents=True, exist_ok=True)
    for q in questions:
        after = _read_json_object(handoff / f"结果声明_问题{q}.json")
        old_flat = _flatten_scalars(before.get(q, {}))
        new_flat = _flatten_scalars(after)
        entries: list[dict[str, str]] = []
        for key in sorted(set(old_flat) | set(new_flat)):
            old = old_flat.get(key, "")
            new = new_flat.get(key, "")
            if old != new:
                entries.append({"键": key, "旧值": old, "新值": new})
        (handoff / f"换版清单_问题{q}.json").write_text(
            json.dumps(
                {"问题": q, "条目": entries, "来源": "S5 verified calc cascade"},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


async def _run_verified_calc_cascade(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    round_num: int,
    *,
    source_q: int,
    items: list[Issue],
    escalated: bool = False,
    cancel=None,
) -> list[dict]:
    """Recompute one late calc issue and every dependent carrier before receipt.

    The Issue Ledger is intentionally untouched until solver execution,
    independent red-team/G2 checks, downstream recomputation, figure rebuild,
    and guarded text synchronization all succeed.
    """
    questions = _calc_cascade_questions(policy, source_q)
    before = {
        q: _read_json_object(
            policy.root / "交接" / f"结果声明_问题{q}.json"
        )
        for q in questions
    }
    downstream = [q for q in questions if q != source_q]
    if downstream:
        events.append_event(
            db,
            "pipeline.s2_downstream_invalidated",
            {"question": source_q, "downstream": downstream, "source": "S5"},
            run_id=run_id,
        )

    events.append_event(
        db,
        "s5.calc_cascade_started",
        {
            "round": round_num,
            "source_question": source_q,
            "questions": questions,
            "escalated": escalated,
            "issues": [x.id for x in items],
        },
        run_id=run_id,
    )

    for q in questions:
        identity = (
            f"S5:R{round_num}:calc:{source_q}:Q{q}:"
            + ("escalated" if escalated and q == source_q else "recompute")
        )
        if escalated and q == source_q:
            ok, verify_issues = await run_verified_question_escalation(
                db, provider, registry, policy, run_id, q,
                identity=identity, cancel=cancel,
            )
        else:
            ok, verify_issues = await run_verified_question_recompute(
                db, provider, registry, policy, run_id, q,
                identity=identity, cancel=cancel,
            )
        if not ok:
            events.append_event(
                db,
                "s5.calc_cascade_failed",
                {
                    "round": round_num,
                    "source_question": source_q,
                    "question": q,
                    "step": "verified_recompute",
                    "issues": verify_issues,
                },
                run_id=run_id,
            )
            return []

    # Freeze the numerical delta before touching downstream carriers.  These
    # manifests remain even if figure/text propagation later fails, so stale
    # values are mechanically visible to publication guards.
    _write_calc_change_manifests(policy, before, questions)

    for q in questions:
        plot_issues = await run_question_plot_scripts(
            registry, policy, q, cancel=cancel
        )
        if plot_issues:
            events.append_event(
                db,
                "s5.calc_cascade_failed",
                {
                    "round": round_num,
                    "source_question": source_q,
                    "question": q,
                    "step": "plot_runtime",
                    "issues": plot_issues,
                },
                run_id=run_id,
            )
            return []

    sync_rel = (
        f"审稿/回执_S5R{round_num}_算级联问{source_q}"
        + ("_升格" if escalated else "")
        + ".json"
    )
    sync_node = (
        f"S5:R{round_num}:算级联同步问{source_q}"
        + (":升格" if escalated else "")
    )
    sync_status, _guard_issues = await guarded_text_repair(
        db, provider, registry, policy, run_id,
        stage_key="S5",
        node_key=sync_node,
        instructions=(
            f"问题{source_q}及其依赖问题 {questions} 已由 Runtime 完成求解、"
            "独立红队与 G2 验证，并重跑现有绘图脚本。"
            "只同步论文中受这些新结果影响的数字、图题、引用和解释；"
            "不得改动已验证的计算事实。"
            f"完成后写 {sync_rel}，对每个原台账 id 各写一条回执。"
        ),
        receipt_rel=sync_rel,
        receipt_schema=ModelRepairReceiptArtifact,
        review_items=[
            {"问题": x.问题, "指令": x.指令, "定位": x.定位}
            for x in items
        ],
        cancel=cancel,
    )
    if sync_status != "SUCCEEDED":
        events.append_event(
            db,
            "s5.calc_cascade_failed",
            {
                "round": round_num,
                "source_question": source_q,
                "step": "writer_sync",
                "status": sync_status,
            },
            run_id=run_id,
        )
        return []

    try:
        raw = json.loads((policy.root / sync_rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = []
    by_id = {
        str(row.get("id", "")).strip(): row
        for row in (raw if isinstance(raw, list) else [])
        if isinstance(row, dict)
    }
    if any(item.id not in by_id for item in items):
        return []

    for q in questions:
        events.append_event(
            db,
            "checkpoint.s2_question",
            {"question": q, "pass": True, "issues": [], "downgraded": False,
             "source": "S5_calc_cascade"},
            run_id=run_id,
        )

    receipts: list[dict] = []
    for item in items:
        row = by_id[item.id]
        receipts.append({
            "id": item.id,
            "generation": item.generation,
            "receipt_id": (
                f"{sync_node}:{item.id}:g{item.generation}"
            ),
            "改动": str(row.get("改动", "已完成算→图→文级联"))[:300],
            "证据": (
                f"G2 verified questions={questions}; {sync_rel}"
            )[:200],
        })
    events.append_event(
        db,
        "s5.calc_cascade_succeeded",
        {
            "round": round_num,
            "source_question": source_q,
            "questions": questions,
            "issues": [x.id for x in items],
            "escalated": escalated,
        },
        run_id=run_id,
    )
    return receipts


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
    suffix = f"问{question_num}" if question_num is not None else ""
    receipt_rel = f"审稿/回执_R{round_num}_{target}{suffix}.json"
    node = f"S5:R{round_num}:回炉{target}{suffix}"
    instructions = (
        "只处理下面点名的台账条目，不扩大修改范围。"
        f"条目={_items_json(items)}。修改完成后写 {receipt_rel}，"
        "每条回执包含 id、generation、改动、证据。"
    )
    if target == "文":
        status, _guard_issues = await guarded_text_repair(
            db, provider, registry, policy, run_id,
            stage_key="S5",
            node_key=node,
            instructions=instructions,
            receipt_rel=receipt_rel,
            receipt_schema=ModelRepairReceiptArtifact,
            review_items=[
                {"问题": x.问题, "指令": x.指令, "定位": x.定位}
                for x in items
            ],
            question_num=question_num,
            cancel=cancel,
        )
    else:
        status = await run_role_leg(
            db, provider, registry, policy, run_id,
            stage_key="S5",
            role_id=role_id,
            node_key=node,
            question_num=question_num,
            instructions=instructions,
            expected_artifacts=[
                ExpectedArtifact(
                    rel_path=receipt_rel,
                    schema_model=ModelRepairReceiptArtifact,
                )
            ],
            cancel=cancel,
        )
    if status != "SUCCEEDED":
        return []
    try:
        data = json.loads((policy.root / receipt_rel).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        data = data.get("回执", [data])

    # Runtime, not the model, owns repair identity and routing.  Only
    # issues assigned to this leg may produce receipts; generation and the
    # deterministic receipt_id come from the runtime's current ledger view.
    assigned = {item.id: item.generation for item in items}
    receipts: list[dict] = []
    for raw in data or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        issue_id = str(item.get("id", "")).strip()
        if issue_id not in assigned:
            continue
        generation = assigned[issue_id]
        claimed_generation = item.get("generation")
        if claimed_generation is not None:
            try:
                if int(claimed_generation) != generation:
                    continue
            except (TypeError, ValueError):
                continue
        item["generation"] = generation
        item["receipt_id"] = f"{node}:{issue_id}:g{generation}"
        receipts.append(item)
    return receipts


async def _run_verified_figure_repair(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    round_num: int,
    *,
    q: int,
    items: list[Issue],
    cancel=None,
) -> list[dict]:
    """Plotter -> Runtime execution -> guarded dependent-text sync."""
    plot_receipts = await _run_rework_leg(
        db, provider, registry, policy, run_id, round_num,
        target="图", items=items, question_num=q, cancel=cancel,
    )
    plot_by_id = {
        str(row.get("id", "")).strip(): row
        for row in plot_receipts
        if isinstance(row, dict)
    }
    if any(item.id not in plot_by_id for item in items):
        return []

    plot_issues = await run_question_plot_scripts(
        registry, policy, q, cancel=cancel
    )
    if plot_issues:
        events.append_event(
            db,
            "s5.figure_repair_failed",
            {"round": round_num, "question": q, "step": "plot_runtime",
             "issues": plot_issues},
            run_id=run_id,
        )
        return []

    sync_rel = f"审稿/回执_R{round_num}_图同步问{q}.json"
    sync_node = f"S5:R{round_num}:图同步问{q}"
    sync_status, _guard_issues = await guarded_text_repair(
        db, provider, registry, policy, run_id,
        stage_key="S5",
        node_key=sync_node,
        instructions=(
            f"问题{q}的绘图脚本已经由 Runtime 重跑成功。"
            "只同步这些图类台账条目影响的图题、正文引用、数字引用和解释，"
            "不得修改冻结计算事实。"
            f"完成后写 {sync_rel}，每个原台账 id 各一条回执。"
        ),
        receipt_rel=sync_rel,
        receipt_schema=ModelRepairReceiptArtifact,
        review_items=[
            {"问题": x.问题, "指令": x.指令, "定位": x.定位}
            for x in items
        ],
        question_num=q,
        cancel=cancel,
    )
    if sync_status != "SUCCEEDED":
        return []
    try:
        sync_raw = json.loads(
            (policy.root / sync_rel).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        sync_raw = []
    sync_by_id = {
        str(row.get("id", "")).strip(): row
        for row in (sync_raw if isinstance(sync_raw, list) else [])
        if isinstance(row, dict)
    }
    if any(item.id not in sync_by_id for item in items):
        return []

    out: list[dict] = []
    for item in items:
        plot_row = plot_by_id[item.id]
        sync_row = sync_by_id[item.id]
        out.append({
            "id": item.id,
            "generation": item.generation,
            "receipt_id": (
                f"{sync_node}:{item.id}:g{item.generation}"
            ),
            "改动": (
                f"图={str(plot_row.get('改动', ''))[:140]}; "
                f"文={str(sync_row.get('改动', ''))[:140]}"
            ),
            "证据": (
                f"{str(plot_row.get('证据', ''))[:90]}; {sync_rel}"
            )[:200],
        })
    events.append_event(
        db,
        "s5.figure_repair_succeeded",
        {"round": round_num, "question": q,
         "issues": [item.id for item in items]},
        run_id=run_id,
    )
    return out


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
            # One ledger issue is one repair identity.  A calc/figure issue
            # that names multiple questions must be split by the reviewer
            # rather than consumed by multiple transactions in the same
            # generation (which would double-count attempts/receipts).
            if len(questions) != 1:
                stats["unrouted"].append(item.id)
                continue
            q = next(iter(questions))
            groups.setdefault(q, []).append(item)
        for q, group in sorted(groups.items()):
            if target == "算":
                receipts = await _run_verified_calc_cascade(
                    db, provider, registry, policy, run_id, round_num,
                    source_q=q, items=group, cancel=cancel,
                )
                leg_name = f"回炉算级联问{q}"
            elif target == "图":
                receipts = await _run_verified_figure_repair(
                    db, provider, registry, policy, run_id, round_num,
                    q=q, items=group, cancel=cancel,
                )
                leg_name = f"回炉图事务问{q}"
            else:
                receipts = await _run_rework_leg(
                    db, provider, registry, policy, run_id, round_num,
                    target=target, items=group, question_num=q, cancel=cancel,
                )
                leg_name = f"回炉{target}问{q}"
            result = ledger.收回执(
                receipts, 腿名=leg_name, 轮次=round_num
            )
            stats[target] += result["受理"]

    text_items = ledger.待改条目(目标们=["文"])
    if text_items:
        receipts = await _run_rework_leg(
            db, provider, registry, policy, run_id, round_num,
            target="文", items=text_items, cancel=cancel,
        )
        result = ledger.收回执(
            receipts, 腿名="回炉文", 轮次=round_num
        )
        stats["文"] += result["受理"]
    return stats


def _restore_round_checkpoint(
    db: Database, run_id: str
) -> tuple[IssueLedger, list[dict[str, Any]], int, bool, list[str]]:
    """Restore S5 only from post-rework round-complete checkpoints."""
    checkpoints = events.query_events(
        db, run_id=run_id, type="checkpoint.s5_round_complete", limit=100
    )
    if not checkpoints:
        return IssueLedger(前缀="审"), [], 1, False, []

    ordered = sorted(
        (
            event for event in checkpoints
            if isinstance(event.payload.get("round"), int)
        ),
        key=lambda event: (int(event.payload["round"]), event.id),
    )
    if not ordered:
        return IssueLedger(前缀="审"), [], 1, False, []

    latest = ordered[-1]
    ledger = IssueLedger.从快照(
        latest.payload.get("ledger") or [], 前缀="审"
    )
    rounds = [
        event.payload.get("round_info")
        for event in ordered
        if isinstance(event.payload.get("round_info"), dict)
    ]
    converged = bool(latest.payload.get("converged", False))
    escalations = [
        str(value)
        for value in (latest.payload.get("needs_escalation") or [])
    ]
    return ledger, rounds, int(latest.payload["round"]) + 1, converged, escalations


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
    ledger, rounds, start_round, converged, needs_escalation = _restore_round_checkpoint(
        db, run_id
    )
    compiler = compile_paper or _default_compile
    renderer = render_pages or _default_render
    _write_ledger_view(policy, ledger)

    extension_events = events.query_events(
        db,
        run_id=run_id,
        type="checkpoint.s5_escalation_extension",
        limit=100,
    )
    extension_pending = any(
        event.payload.get("round") == max_rounds
        for event in extension_events
    )
    extension_resume = start_round == max_rounds + 1 and extension_pending

    if converged or (start_round > max_rounds and not extension_resume):
        return {
            "rounds": rounds,
            "converged": converged,
            "ledger_summary": ledger.摘要(),
            "needs_escalation": needs_escalation,
            "ledger": _ledger_view(ledger),
        }

    round_limit = max_rounds + (1 if extension_resume else 0)
    round_num = start_round
    while round_num <= round_limit:
        snapshot_files = _ensure_paper_snapshot(policy, round_num)
        compile_result = await run_compile(compiler, policy.root, cancel=cancel)
        render_issue: str | None = None
        rendered_pages: list[Path] = []
        if compile_result.get("rc") in (0, None) and not compile_result.get("errors"):
            try:
                rendered_pages = renderer(policy.root)
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
        review = await _run_review_legs(
            db,
            provider,
            registry,
            policy,
            run_id,
            round_num,
            page_images=rendered_pages,
            cancel=cancel,
        )
        merged_verdicts, abstention_votes = merge_channel_verdicts(
            review.channel_verdicts
        )
        verdict_stats = ledger.收裁定(merged_verdicts, 轮次=round_num)
        missed_verdict_ids = {
            item.id for item in ledger.条目 if item.状态 == "待复核"
        }
        missed_verdicts = ledger.待复核未裁()

        previous_score = None
        if rounds:
            previous = rounds[-1]
            if isinstance(previous, dict):
                value = previous.get("effective_score", previous.get("score"))
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    previous_score = float(value)

        retention_action, retention_reason = _retention_decision(
            review.relative_judgment,
            previous_score,
            review.score,
        )
        restored_files = 0
        rolled_back_issues = 0
        effective_score = review.score
        if round_num > 1 and retention_action == "回退":
            restored_files = _restore_paper_snapshot(policy, round_num - 1)
            if restored_files:
                rolled_back_issues = ledger.回退轮修订(
                    round_num - 1, retention_reason
                )
                effective_score = previous_score
                events.append_event(
                    db,
                    "s5.rollback",
                    {
                        "round": round_num,
                        "to_round": round_num - 1,
                        "reason": retention_reason,
                        "restored_files": restored_files,
                        "reopened_issues": rolled_back_issues,
                    },
                    run_id=run_id,
                )
            else:
                retention_action = "无法回退"
                retention_reason += "；缺少上一轮持久快照"
                events.append_event(
                    db,
                    "s5.rollback_unavailable",
                    {"round": round_num, "reason": retention_reason},
                    run_id=run_id,
                )

        stats = ledger.并入(mechanical + review.opinions, round_num)

        converged, blocking = ledger.收敛()
        round_info: dict[str, Any] = {
            "round": round_num,
            "stats": stats,
            "verdicts": verdict_stats,
            "missed_verdicts": missed_verdicts,
            "abstention_votes": abstention_votes,
            "relative_judgment": review.relative_judgment,
            "score": review.score,
            "effective_score": effective_score,
            "retention_action": retention_action,
            "retention_reason": retention_reason,
            "snapshot_files": snapshot_files,
            "restored_files": restored_files,
            "rolled_back_issues": rolled_back_issues,
            "converged": converged,
            "blocking": len(blocking),
        }
        rounds.append(round_info)
        _write_ledger_view(policy, ledger)
        events.append_event(
            db, "s5.round_reviewed",
            {"round": round_num, "converged": converged, "ledger": ledger.摘要()},
            run_id=run_id,
        )

        # Fuse processing: escalate blocking, shelve narrative (ALWAYS runs, even on final round)
        escalated_this_round = False
        escalated_count = 0
        prior_successful_escalations: set[str] = set()
        prior_failed_escalations: set[str] = set()
        for ev in events.query_events(db, run_id=run_id, type="s5.escalation_succeeded"):
            ek = f"{ev.payload.get('issue_id')}:{ev.payload.get('generation')}"
            prior_successful_escalations.add(ek)
        for ev in events.query_events(db, run_id=run_id, type="s5.escalation_failed"):
            ek = f"{ev.payload.get('issue_id')}:{ev.payload.get('generation')}"
            prior_failed_escalations.add(ek)
        for item in ledger.熔断候选(阈值=2):
            ek = f"{item.id}:{item.generation}"
            if item.级别 in ("硬伤", "正确性"):
                if ek in prior_successful_escalations:
                    # A missing verdict is not an unresolved verdict.  Only an
                    # explicit reviewer "未消解" after a successful escalation
                    # can exhaust the single escalation chance.
                    if item.id in missed_verdict_ids:
                        continue
                    # A successful escalation produced a valid repair receipt,
                    # and the reviewer explicitly left this generation
                    # unresolved: the single escalation chance is exhausted.
                    upsert_degraded_review_issue(
                        policy.root,
                        issue_id=item.id,
                        generation=item.generation,
                        severity=item.级别,
                        reason="S5 升格重做已耗尽，登记降级放行",
                        source_stage="S5",
                    )
                    ledger.搁置条目(item.id, "升格重做已耗尽，登记降级放行")
                    events.append_event(
                        db, "s5.degraded_release_registered",
                        {"issue_id": item.id, "generation": item.generation,
                         "round": round_num},
                        run_id=run_id,
                    )
                    continue
                if ek in prior_failed_escalations:
                    # Technical/model failure is not evidence that a genuine
                    # alternative repair was attempted and reviewed.  Never
                    # auto-authorize degraded release from a failed leg.
                    continue
                if round_num > max_rounds:
                    # The single extension round exists only to adjudicate
                    # escalations started in the final normal round.  Do not
                    # start a fresh escalation that would have no later
                    # reviewer round.
                    continue
                needs_escalation.append(item.id)
                role_id = {"算": "calc_cascade", "图": "plotter", "文": "writer"}.get(
                    item.目标, "writer"
                )
                esc_node = f"S5:R{round_num}:升格{item.id}"
                receipt_path = (
                    f"审稿/回执_升格_{item.id}_g{item.generation}.json"
                )
                events.append_event(
                    db, "s5.escalation_started",
                    {"issue_id": item.id, "generation": item.generation,
                     "round": round_num, "role": role_id},
                    run_id=run_id,
                )

                receipts: list[dict] = []
                esc_status = "FAILED"

                if item.目标 == "算":
                    questions = sorted(_related_questions(item))
                    if len(questions) == 1:
                        receipts = await _run_verified_calc_cascade(
                            db, provider, registry, policy, run_id, round_num,
                            source_q=questions[0],
                            items=[item],
                            escalated=True,
                            cancel=cancel,
                        )
                        esc_status = "SUCCEEDED" if receipts else "FAILED"
                    else:
                        esc_status = "UNROUTABLE_CALC_ISSUE"

                elif item.目标 == "文":
                    esc_status, _guard_issues = await guarded_text_repair(
                        db, provider, registry, policy, run_id,
                        stage_key="S5",
                        node_key=esc_node,
                        instructions=(
                            f"【升格】台账条目 {item.id} 两次定向修订仍未消解。"
                            "换一种叙事/组织方式做最小修订，不改冻结计算事实。"
                            f"完成后写 {receipt_path}。"
                        ),
                        receipt_rel=receipt_path,
                        receipt_schema=ModelRepairReceiptArtifact,
                        review_items=[
                            {"问题": item.问题, "指令": item.指令, "定位": item.定位}
                        ],
                        change_limit=0.70,
                        cancel=cancel,
                    )
                    if esc_status == "SUCCEEDED":
                        try:
                            raw = json.loads(
                                (policy.root / receipt_path).read_text(
                                    encoding="utf-8"
                                )
                            )
                        except (json.JSONDecodeError, OSError):
                            raw = []
                        for candidate in raw if isinstance(raw, list) else []:
                            if (
                                isinstance(candidate, dict)
                                and str(candidate.get("id", "")).strip() == item.id
                            ):
                                enriched = dict(candidate)
                                enriched["generation"] = item.generation
                                enriched["receipt_id"] = (
                                    f"{esc_node}:{item.id}:g{item.generation}"
                                )
                                receipts.append(enriched)

                else:
                    esc_status = await run_role_leg(
                        db, provider, registry, policy, run_id,
                        stage_key="S5", role_id="plotter", node_key=esc_node,
                        instructions=(
                            f"【升格改图】台账条目 {item.id} 两次定向修订仍未消解。"
                            "换一种绘图实现或视觉表达，只改脚本，不自行执行。"
                            f"完成后写 {receipt_path}。"
                        ),
                        expected_artifacts=[
                            ExpectedArtifact(
                                rel_path=receipt_path,
                                schema_model=ModelRepairReceiptArtifact,
                            )
                        ],
                        question_num=(
                            next(iter(_related_questions(item)))
                            if len(_related_questions(item)) == 1
                            else None
                        ),
                        cancel=cancel,
                    )
                    questions = sorted(_related_questions(item))
                    if esc_status == "SUCCEEDED" and len(questions) == 1:
                        q = questions[0]
                        try:
                            raw = json.loads(
                                (policy.root / receipt_path).read_text(
                                    encoding="utf-8"
                                )
                            )
                        except (json.JSONDecodeError, OSError):
                            raw = []
                        plot_receipt = next(
                            (
                                row for row in (
                                    raw if isinstance(raw, list) else []
                                )
                                if isinstance(row, dict)
                                and str(row.get("id", "")).strip() == item.id
                            ),
                            None,
                        )
                        plot_issues = await run_question_plot_scripts(
                            registry, policy, q, cancel=cancel
                        )
                        if plot_receipt is not None and not plot_issues:
                            sync_rel = (
                                f"审稿/回执_升格图同步_{item.id}_"
                                f"g{item.generation}.json"
                            )
                            sync_status, _guard_issues = await guarded_text_repair(
                                db, provider, registry, policy, run_id,
                                stage_key="S5",
                                node_key=f"{esc_node}:正文同步",
                                instructions=(
                                    f"升格图条目 {item.id} 已由 Runtime 重跑成功。"
                                    f"只同步问题{q}依赖该图的图题、正文引用、数字引用"
                                    f"与解释，并写 {sync_rel}。"
                                ),
                                receipt_rel=sync_rel,
                                receipt_schema=ModelRepairReceiptArtifact,
                                review_items=[{
                                    "问题": item.问题,
                                    "指令": item.指令,
                                    "定位": item.定位,
                                }],
                                change_limit=0.70,
                                question_num=q,
                                cancel=cancel,
                            )
                            if sync_status == "SUCCEEDED":
                                try:
                                    sync_raw = json.loads(
                                        (policy.root / sync_rel).read_text(
                                            encoding="utf-8"
                                        )
                                    )
                                except (json.JSONDecodeError, OSError):
                                    sync_raw = []
                                sync_receipt = next(
                                    (
                                        row for row in (
                                            sync_raw
                                            if isinstance(sync_raw, list)
                                            else []
                                        )
                                        if isinstance(row, dict)
                                        and str(row.get("id", "")).strip()
                                        == item.id
                                    ),
                                    None,
                                )
                                if sync_receipt is not None:
                                    receipts.append({
                                        "id": item.id,
                                        "generation": item.generation,
                                        "receipt_id": (
                                            f"{esc_node}:图事务:{item.id}:"
                                            f"g{item.generation}"
                                        ),
                                        "改动": (
                                            f"图={str(plot_receipt.get('改动', ''))[:140]}; "
                                            f"文={str(sync_receipt.get('改动', ''))[:140]}"
                                        ),
                                        "证据": f"{receipt_path}; {sync_rel}",
                                    })
                                else:
                                    esc_status = "INVALID_SYNC_RECEIPT"
                            else:
                                esc_status = sync_status
                        else:
                            esc_status = "PLOT_RUNTIME_FAILED"
                    elif esc_status == "SUCCEEDED":
                        esc_status = "UNROUTABLE_FIGURE_ISSUE"

                receipt_stats = ledger.收回执(
                    receipts, 腿名=esc_node, 轮次=round_num
                )
                if esc_status == "SUCCEEDED" and receipt_stats["受理"] > 0:
                    escalated_this_round = True
                    escalated_count += 1
                    events.append_event(
                        db, "s5.escalation_succeeded",
                        {"issue_id": item.id, "generation": item.generation,
                         "round": round_num, "role": role_id,
                         "receipts": receipt_stats["受理"]},
                        run_id=run_id,
                    )
                else:
                    events.append_event(
                        db, "s5.escalation_failed",
                        {"issue_id": item.id, "generation": item.generation,
                         "round": round_num, "role": role_id,
                         "status": (
                             esc_status
                             if esc_status != "SUCCEEDED"
                             else "INVALID_RECEIPT"
                         )},
                        run_id=run_id,
                    )
                continue
            ledger.搁置条目(item.id, "两次定向修订仍未消解")

        # Persist shelve/degraded-registration before any break path so the
        # carrier on disk always matches the post-fuse ledger state.
        _write_ledger_view(policy, ledger)

        # Post-fuse convergence check
        converged, blocking = ledger.收敛()
        round_info["converged"] = converged
        round_info["blocking"] = len(blocking)

        if converged:
            events.append_event(
                db,
                "checkpoint.s5_round_complete",
                {
                    "round": round_num,
                    "converged": True,
                    "ledger": ledger.快照(),
                    "round_info": round_info,
                },
                run_id=run_id,
            )
            break

        # Break only if: final round AND no escalation was started this round
        # (escalation gives the issue one more round for reviewer re-verdict)
        if round_num >= max_rounds and not escalated_this_round:
            events.append_event(
                db,
                "checkpoint.s5_round_complete",
                {
                    "round": round_num,
                    "converged": False,
                    "ledger": ledger.快照(),
                    "round_info": round_info,
                    "needs_escalation": needs_escalation,
                },
                run_id=run_id,
            )
            break

        if round_num == max_rounds and escalated_this_round:
            # Allow exactly one extra reviewer round for escalations started
            # in the last normal round.  The event also makes this extension
            # recoverable after a crash.
            round_limit = max_rounds + 1
            events.append_event(
                db,
                "checkpoint.s5_escalation_extension",
                {"round": round_num, "escalated": escalated_count},
                run_id=run_id,
            )

        round_info["rework"] = await _run_rework(
            db, provider, registry, policy, run_id, round_num, ledger, cancel=cancel
        )
        _write_ledger_view(policy, ledger)
        events.append_event(
            db,
            "checkpoint.s5_round_complete",
            {
                "round": round_num,
                "converged": False,
                "ledger": ledger.快照(),
                "round_info": round_info,
                "needs_escalation": needs_escalation,
            },
            run_id=run_id,
        )
        round_num += 1

    return {
        "rounds": rounds,
        "converged": converged,
        "ledger_summary": ledger.摘要(),
        "needs_escalation": needs_escalation,
        "ledger": _ledger_view(ledger),
    }
