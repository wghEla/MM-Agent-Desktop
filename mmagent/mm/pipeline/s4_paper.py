"""S4 paper swarm: narrative -> draft -> dual review -> integration -> abstract swarm -> G4."""
from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mmagent.mm.audit import audit_paper
from mmagent.mm.config.profiles import get_profile
from mmagent.mm.config.thresholds import DEFAULT_THRESHOLDS
from mmagent.mm.contracts.s4_contracts import (
    AbstractRestatementVerdict,
    BlindReaderReview,
    ChapterReview,
    RequirementCoverageDocument,
)
from mmagent.mm.gates.g4 import check_g4, check_narrative
from mmagent.mm.pipeline.guarded_repair import guarded_text_repair
from mmagent.mm.retention import (
    ensure_paper_snapshot,
    restore_paper_snapshot,
    retention_decision,
)
from mmagent.orchestration.role_leg import run_role_leg
from mmagent.orchestration.wave import WaveJob, run_status_wave
from mmagent.providers.base import BaseProvider
from mmagent.state import events
from mmagent.state.db import Database
from mmagent.tools.latex import LatexTool
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy

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


def _relative_judgment(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    raw = str(data.get("相对判断", "")).strip()
    if raw.startswith(("更差", "差")):
        return "更差"
    if raw.startswith(("更好", "好")):
        return "更好"
    if raw:
        return "持平"
    return None


def _review_items(path: Path, *keys: str) -> list[dict[str, str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    out: list[dict[str, str]] = []
    for key in keys:
        raw = data.get(key, [])
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, dict):
                out.append({
                    "问题": str(item.get("问题", item.get("内容", ""))),
                    "指令": str(item.get("指令", item.get("修改指令", ""))),
                    "定位": str(item.get("定位", item.get("章节", ""))),
                })
            elif item is not None:
                out.append({"问题": str(item), "指令": "", "定位": ""})
    return out


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



def _apply_requirement_coverage(root: Path) -> tuple[bool, list[str]]:
    matrix_path = root / "交接" / "需求追踪矩阵.json"
    coverage_path = root / "交接" / "需求覆盖.json"
    try:
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, [f"需求覆盖证据缺失或不可解析: {exc}"]
    if not isinstance(matrix, list) or not isinstance(coverage, list):
        return False, ["需求追踪矩阵/需求覆盖 顶层必须是数组"]
    by_id = {
        str(x.get("需求号")): x
        for x in coverage
        if isinstance(x, dict) and x.get("需求号")
    }
    issues: list[str] = []
    for row in matrix:
        if not isinstance(row, dict):
            issues.append("需求追踪矩阵存在非对象条目")
            continue
        rid = str(row.get("需求号", ""))
        evidence = by_id.get(rid)
        if not evidence:
            issues.append(f"需求 {rid or '?'} 缺论文覆盖证据")
            continue
        chapter = str(evidence.get("章节", "")).strip()
        proof = str(evidence.get("证据", "")).strip()
        if not chapter or not proof:
            issues.append(f"需求 {rid} 覆盖证据缺章节或证据说明")
            continue
        row["状态"] = "已销号"
        row["章节"] = chapter
        row["图表"] = str(evidence.get("图表", ""))
        row["关键数字"] = str(evidence.get("关键数字", ""))
    if issues:
        return False, issues
    matrix_path.write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True, []


async def _leg(
    db: Database, provider: BaseProvider, registry: ToolRegistry, policy: PathPolicy,
    run_id: str, *, role_id: str, node_key: str, instructions: str,
    expected: list[ExpectedArtifact], cancel=None
) -> str:
    return await run_role_leg(
        db, provider, registry, policy, run_id,
        stage_key="S4",
        role_id=role_id,
        node_key=node_key,
        instructions=instructions,
        expected_artifacts=expected,
        cancel=cancel,
    )

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
        instructions=(
            "依据论点脊柱、结果声明、图证与实验记录写 论文/论文.tex；不得自行改变冻结事实。"
            "同时写 交接/需求覆盖.json，数组中逐个需求号给出 章节、证据、图表、关键数字；"
            "只声明论文中真实存在的覆盖证据。"
        ),
        expected=[
            ExpectedArtifact(rel_path="论文/论文.tex", kind="text"),
            ExpectedArtifact(rel_path="交接/需求覆盖.json", schema_model=RequirementCoverageDocument),
        ], cancel=cancel,
    )
    if draft_status != "SUCCEEDED":
        return {"g4_pass": False, "g4_issues": ["正文初稿腿失败"], "reviews": review_history}
    coverage_ok, coverage_issues = _apply_requirement_coverage(policy.root)
    if not coverage_ok:
        return {"g4_pass": False, "g4_issues": coverage_issues, "reviews": review_history}

    for round_num in range(1, cfg.章评轮数 + 1):
        snapshot_files = ensure_paper_snapshot(policy, "s4", round_num)
        visible_snapshot = (
            policy.root / "审稿" / "章快照" / f"R{round_num}" / "论文.tex"
        )
        visible_snapshot.parent.mkdir(parents=True, exist_ok=True)
        current_paper = policy.root / "论文" / "论文.tex"
        if current_paper.is_file() and not visible_snapshot.is_file():
            shutil.copy2(current_paper, visible_snapshot)

        chapter_rel = f"审稿/章评R{round_num}.json"
        reader_rel = f"审稿/读者R{round_num}.json"
        async def chapter_review(
            *, review_round=round_num, review_path=chapter_rel
        ) -> str:
            return await _leg(
                db, provider, registry, policy, run_id,
                role_id="chapter_reviewer", node_key=f"S4:章评R{review_round}",
                instructions=(
                    f"评审论文各章并写 {review_path}，顶层给出数值字段 总分。"
                    + (
                        f" 同时对比 审稿/章快照/R{review_round - 1}/论文.tex "
                        "与当前 论文/论文.tex，顶层给 相对判断=更好|持平|更差。"
                        if review_round > 1
                        else ""
                    )
                ),
                expected=[ExpectedArtifact(rel_path=review_path, schema_model=ChapterReview)], cancel=cancel,
            )

        async def blind_review(
            *, review_round=round_num, review_path=reader_rel
        ) -> str:
            return await _leg(
                db, provider, registry, policy, run_id,
                role_id="blind_reader", node_key=f"S4:闭卷R{review_round}",
                instructions=(
                    f"只读论文内容做闭卷理解测试并写 {review_path}，"
                    "顶层给出数值字段 读者分。"
                ),
                expected=[ExpectedArtifact(rel_path=review_path, schema_model=BlindReaderReview)], cancel=cancel,
            )

        review_wave = await run_status_wave(
            db,
            run_id,
            [
                WaveJob("章评", chapter_review),
                WaveJob("闭卷", blind_review),
            ],
            cancel=cancel,
            wave_key=f"S4:评审R{round_num}",
            serial=provider.protocol == "mock",
            timeout_s=3600,
        )
        chapter_status = review_wave.results.get("章评", "FAILED")
        reader_status = review_wave.results.get("闭卷", "FAILED")
        chapter_score = _score(policy.root / chapter_rel)
        reader_score = _score(policy.root / reader_rel)
        relative = (
            _relative_judgment(policy.root / chapter_rel)
            if chapter_status == "SUCCEEDED"
            else None
        )
        previous = review_history[-1] if review_history else None
        previous_chapter = (
            float(previous["effective_chapter_score"])
            if previous is not None
            else None
        )
        previous_reader = (
            float(previous["effective_reader_score"])
            if previous is not None
            else None
        )
        retention_action, retention_reason = retention_decision(
            relative,
            previous_chapter,
            chapter_score if chapter_status == "SUCCEEDED" else None,
        )
        restored_files = 0
        effective_chapter_score = chapter_score
        effective_reader_score = reader_score
        if round_num > 1 and retention_action == "回退":
            restored_files = restore_paper_snapshot(policy, "s4", round_num - 1)
            if restored_files:
                effective_chapter_score = (
                    previous_chapter if previous_chapter is not None else chapter_score
                )
                effective_reader_score = (
                    previous_reader if previous_reader is not None else reader_score
                )
                events.append_event(
                    db,
                    "s4.rollback",
                    {
                        "round": round_num,
                        "to_round": round_num - 1,
                        "reason": retention_reason,
                        "restored_files": restored_files,
                    },
                    run_id=run_id,
                )
            else:
                retention_action = "无法回退"
                retention_reason += "；缺少上一轮持久快照"

        review_history.append({
            "round": round_num,
            "chapter_score": chapter_score,
            "reader_score": reader_score,
            "effective_chapter_score": effective_chapter_score,
            "effective_reader_score": effective_reader_score,
            "relative_judgment": relative,
            "retention_action": retention_action,
            "retention_reason": retention_reason,
            "snapshot_files": snapshot_files,
            "restored_files": restored_files,
        })
        if (
            chapter_status == "SUCCEEDED" and reader_status == "SUCCEEDED"
            and effective_chapter_score >= chapter_threshold
            and effective_reader_score >= chapter_threshold
        ):
            break
        if round_num >= cfg.章评轮数:
            break
        source_round = round_num - 1 if restored_files else round_num
        source_chapter_rel = f"审稿/章评R{source_round}.json"
        source_reader_rel = f"审稿/读者R{source_round}.json"
        revision_receipt = f"审稿/回执_S4定向修订R{round_num}.json"
        revision_items = (
            _review_items(policy.root / source_chapter_rel, "问题")
            + _review_items(policy.root / source_reader_rel, "卡住")
        )
        revision, _guard_issues = await guarded_text_repair(
            db, provider, registry, policy, run_id,
            stage_key="S4",
            node_key=f"S4:定向修订R{round_num}",
            instructions=(
                f"只根据 {source_chapter_rel} 与 {source_reader_rel} 做定向修订；"
                "保持数字/公式事实不变，修改既有论文内容。"
                f"完成后写 {revision_receipt} 说明修改证据。"
            ),
            receipt_rel=revision_receipt,
            review_items=revision_items,
            cancel=cancel,
        )
        if revision != "SUCCEEDED":
            return {"g4_pass": False, "g4_issues": ["S4 定向修订失败"], "reviews": review_history}

    if review_history:
        last = review_history[-1]
        if (
            last["effective_chapter_score"] < chapter_threshold
            or last["effective_reader_score"] < chapter_threshold
        ):
            return {
                "g4_pass": False,
                "g4_issues": [
                    f"章评/闭卷末轮未达 {chapter_threshold:.1f}: "
                    f"{last['effective_chapter_score']:.2f}/"
                    f"{last['effective_reader_score']:.2f}"
                ],
                "reviews": review_history,
            }

    latest_items: list[dict[str, str]] = []
    if review_history:
        last_round = int(review_history[-1]["round"])
        latest_items = (
            _review_items(policy.root / f"审稿/章评R{last_round}.json", "问题")
            + _review_items(policy.root / f"审稿/读者R{last_round}.json", "卡住")
        )
    integrate, _guard_issues = await guarded_text_repair(
        db, provider, registry, policy, run_id,
        stage_key="S4",
        node_key="S4:统稿",
        role_id="integrator",
        instructions="统一全文语言与跨章衔接，只动语言层；写 审稿/统稿回执.json。",
        receipt_rel="审稿/统稿回执.json",
        review_items=latest_items,
        cancel=cancel,
    )
    if integrate != "SUCCEEDED":
        return {"g4_pass": False, "g4_issues": ["统稿腿失败"], "reviews": review_history}

    candidate_rows: dict[int, dict[str, Any]] = {}
    candidate_jobs: list[WaveJob[str]] = []
    for index in range(1, cfg.摘要变体数 + 1):
        candidate_rel = f"论文/摘要候选_{index}.tex"
        verdict_rel = f"审稿/摘要复述_{index}.json"

        async def run_candidate(
            *,
            candidate_index=index,
            candidate_path=candidate_rel,
            verdict_path=verdict_rel,
        ) -> str:
            status = await _leg(
                db, provider, registry, policy, run_id,
                role_id="writer", node_key=f"S4:摘要候选{candidate_index}",
                instructions=(
                    f"独立写摘要候选 {candidate_path}；"
                    "突出题目对象、方法、各问结果与可信性。"
                ),
                expected=[ExpectedArtifact(rel_path=candidate_path, kind="text")],
                cancel=cancel,
            )
            if status != "SUCCEEDED":
                return status

            verdict_status = await _leg(
                db, provider, registry, policy, run_id,
                role_id="blind_reader", node_key=f"S4:摘要复述{candidate_index}",
                instructions=(
                    f"只读 {candidate_path} 做四要素复述门，写 {verdict_path}；"
                    "顶层必须有 通过(boolean) 与 分数(number)。"
                ),
                expected=[ExpectedArtifact(rel_path=verdict_path, schema_model=AbstractRestatementVerdict)],
                cancel=cancel,
            )
            if verdict_status == "SUCCEEDED":
                passed, score = _abstract_verdict(policy.root / verdict_path)
                candidate_rows[candidate_index] = {
                    "index": candidate_index,
                    "path": candidate_path,
                    "passed": passed,
                    "score": score,
                }
            return verdict_status

        candidate_jobs.append(WaveJob(f"摘要{index}", run_candidate))

    candidate_wave = await run_status_wave(
        db,
        run_id,
        candidate_jobs,
        cancel=cancel,
        wave_key="S4:摘要蜂群",
        serial=provider.protocol == "mock",
    )
    candidates: list[dict[str, Any]] = []
    for index in range(1, cfg.摘要变体数 + 1):
        row = candidate_rows.get(index)
        if row is None:
            candidates.append({
                "index": index,
                "path": f"论文/摘要候选_{index}.tex",
                "passed": False,
                "score": 0.0,
                "status": candidate_wave.results.get(f"摘要{index}", "FAILED"),
            })
            continue
        row["status"] = candidate_wave.results.get(f"摘要{index}", "FAILED")
        row["passed"] = bool(row["passed"] and row["status"] == "SUCCEEDED")
        candidates.append(row)

    passing = [x for x in candidates if x["passed"]]
    if not passing:
        return {"g4_pass": False, "g4_issues": ["摘要复述门无候选通过"], "reviews": review_history, "abstracts": candidates}
    best = max(passing, key=lambda x: (x["score"], -x["index"]))
    shutil.copyfile(policy.root / best["path"], policy.root / "论文" / "0.摘要.tex")

    audit_paper(policy.root)
    compiler = compile_paper or _default_compile
    # E8: bounded compile-repair protocol before the final gate — the writer
    # gets the log errors and must fix 论文/*.tex (with receipt), then the
    # paper is recompiled; exhaustion still fails closed below.
    from mmagent.mm.pipeline.compile_repair import run_compile_repair
    compile_result = await run_compile_repair(
        db, provider, registry, policy, run_id, compiler,
        stage_key="S4", cancel=cancel,
    )
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
