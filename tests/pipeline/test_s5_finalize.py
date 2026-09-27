from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.mm.contracts.degraded_release import (
    DegradedReviewIssueEntry,
    write_degraded_release,
)
from mmagent.mm.gates.g5 import check_g5
from mmagent.mm.guards.guards import stale_value_guard
from mmagent.mm.pipeline.s5_finalize import run_g5, run_s5a, run_s5b
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.state import events, repositories
from mmagent.tools.filesystem import FsReadTool, FsWriteTool
from mmagent.tools.python import PythonRunTool
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.path_policy import PathPolicy


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(FsReadTool())
    reg.register(FsWriteTool())
    reg.register(PythonRunTool())
    return reg


def _write(call_id: str, path: str, payload) -> list[MockTurn]:
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return [
        MockTurn(tool_calls=[(call_id, "fs.write", {"path": path, "content": content})]),
        MockTurn(text="完成"),
    ]


def _seed_publishable(root: Path) -> None:
    (root / "论文").mkdir(parents=True, exist_ok=True)
    (root / "交接").mkdir(parents=True, exist_ok=True)
    (root / "台账").mkdir(parents=True, exist_ok=True)
    (root / "论文" / "论文.tex").write_text("正文没有统计数字。", encoding="utf-8")
    (root / "论文" / "0.摘要.tex").write_text("摘要。", encoding="utf-8")
    (root / "交接" / "需求追踪矩阵.json").write_text(
        json.dumps([{"需求号": "1-1", "状态": "已销号"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "台账" / "审稿台账.json").write_text("[]", encoding="utf-8")


def _compile(root: Path) -> dict:
    (root / "论文").mkdir(parents=True, exist_ok=True)
    (root / "论文" / "论文.log").write_text(
        "Output written on 论文.pdf (10 pages).", encoding="utf-8"
    )
    (root / "论文" / "论文.pdf").write_bytes(b"%PDF-test")
    return {"rc": 0, "errors": [], "pages": 10}


def _render(root: Path) -> list[Path]:
    page_dir = root / "论文" / "页"
    page_dir.mkdir(parents=True, exist_ok=True)
    p = page_dir / "page-001.png"
    p.write_bytes(b"PNG")
    return [p]


@pytest.mark.asyncio
async def test_s5a_abstract_restate_gate(tmp_path: Path) -> None:
    from mmagent.api.projects import create_project
    handle = create_project(tmp_path / "proj", name="s5a", profile="快速")
    try:
        root = handle.workspace.root
        (root / "论文" / "论文.tex").write_text("正文", encoding="utf-8")
        run_id = repositories.create_run(handle.workspace.db, project_id=handle.project_id, profile="快速")
        script = MockScript(
            _write("a", "论文/0.摘要.tex", "对象、方法、结果、局限都能从摘要复述。")
            + _write("v", "审稿/摘要复述_定稿1.json", {"通过": True, "分数": 8.5})
        )
        result = await run_s5a(
            handle.workspace.db, MockProvider(script), _registry(), PathPolicy(root), run_id
        )
        assert result["pass"] is True
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s5b_routes_text_issue_and_keeps_page_guard(tmp_path: Path) -> None:
    from mmagent.api.projects import create_project
    handle = create_project(tmp_path / "proj", name="s5b", profile="快速")
    try:
        root = handle.workspace.root
        _seed_publishable(root)
        run_id = repositories.create_run(handle.workspace.db, project_id=handle.project_id, profile="快速")
        script = MockScript(
            _write("b", "审稿/美1.json", {
                "页问题": [{"页": 1, "目标": "文", "严重度": 2, "问题": "标题拥挤", "修改指令": "压缩标题间距"}]
            })
            + _write("w", "审稿/回执_美化R1_文.json", {"改动": "压缩标题间距"})
        )
        result = await run_s5b(
            handle.workspace.db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            profile="快速", compile_paper=_compile, render_pages=_render,
        )
        assert result["pass"] is True
        assert result["beauty_baseline_pages"] == 10
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s5b_routes_figure_issue_to_plotter_question_scope(tmp_path: Path) -> None:
    from mmagent.api.projects import create_project
    handle = create_project(tmp_path / "proj", name="s5b-figure", profile="快速")
    try:
        root = handle.workspace.root
        _seed_publishable(root)
        run_id = repositories.create_run(handle.workspace.db, project_id=handle.project_id, profile="快速")
        script = MockScript(
            _write("b", "审稿/美1.json", {
                "页问题": [{"页": 4, "目标": "图", "严重度": 2, "问题": "问题1 图例过小", "修改指令": "放大图例"}]
            })
            + [
                MockTurn(tool_calls=[
                    ("p-script", "fs.write", {
                        "path": "求解/问题1/绘图_美化.py",
                        "content": "from pathlib import Path\nPath('求解/问题1/图片').mkdir(parents=True, exist_ok=True)\nPath('求解/问题1/图片/beauty-rerun.marker').write_text('rerun', encoding='utf-8')\n",
                    }),
                    ("p-receipt", "fs.write", {
                        "path": "审稿/回执_美化R1_图问1.json",
                        "content": json.dumps({"改动": "放大图例"}, ensure_ascii=False),
                    }),
                ]),
                MockTurn(text="图修改完成"),
            ]
        )
        result = await run_s5b(
            handle.workspace.db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            profile="快速", compile_paper=_compile, render_pages=_render,
        )
        assert result["pass"] is True
        assert (root / "求解" / "问题1" / "图片" / "beauty-rerun.marker").read_text(
            encoding="utf-8"
        ) == "rerun"
    finally:
        handle.workspace.db.close()


def test_stale_value_guard_detects_old_release_value(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    (root / "交接").mkdir(parents=True)
    (root / "论文").mkdir(parents=True)
    (root / "交接" / "换版清单_问题1.json").write_text(
        json.dumps({"条目": [{"键": "厚度", "旧值": "2.58", "新值": "2.17"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "论文" / "论文.tex").write_text("最终厚度仍写成 2.58。", encoding="utf-8")
    ok, issues = stale_value_guard(root)
    assert not ok
    assert any("2.58" in x for x in issues)


def test_g5_blocks_unapproved_blocking_shelved_issue(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    _seed_publishable(root)
    _compile(root)
    from mmagent.mm.audit import audit_paper
    audit_paper(root)
    (root / "台账" / "审稿台账.json").write_text(json.dumps([
        {"id": "审-1-01", "级别": "正确性", "状态": "搁置", "generation": 0}
    ], ensure_ascii=False), encoding="utf-8")
    ok, issues = check_g5(root, beauty_baseline_pages=10, current_pages=10)
    assert not ok
    assert any("降级放行" in x for x in issues)


def test_g5_degraded_approval_matches_exact_issue_generation(tmp_path: Path) -> None:
    root = tmp_path / "proj-degraded"
    _seed_publishable(root)
    _compile(root)
    from mmagent.mm.audit import audit_paper
    audit_paper(root)
    (root / "台账" / "审稿台账.json").write_text(json.dumps([
        {
            "id": "审-1-01",
            "级别": "正确性",
            "状态": "搁置",
            "generation": 2,
        }
    ], ensure_ascii=False), encoding="utf-8")

    write_degraded_release(
        root,
        review_issue_entries=[
            DegradedReviewIssueEntry(
                id="审-1-01",
                generation=1,
                severity="正确性",
                reason="old generation",
            )
        ],
    )
    ok, issues = check_g5(root, beauty_baseline_pages=10, current_pages=10)
    assert not ok
    assert any("generation=2" in x for x in issues)

    write_degraded_release(
        root,
        review_issue_entries=[
            DegradedReviewIssueEntry(
                id="审-1-01",
                generation=2,
                severity="正确性",
                reason="current generation exhausted",
            )
        ],
    )
    ok, issues = check_g5(root, beauty_baseline_pages=10, current_pages=10)
    assert ok, issues


@pytest.mark.asyncio
async def test_g5_compiles_before_defect_hunter_and_passes(tmp_path: Path) -> None:
    from mmagent.api.projects import create_project
    handle = create_project(tmp_path / "proj", name="g5", profile="快速")
    try:
        root = handle.workspace.root
        _seed_publishable(root)
        run_id = repositories.create_run(handle.workspace.db, project_id=handle.project_id, profile="快速")
        script = MockScript(
            _write("g", "审稿/G5复核.json", {"通过": True, "依据版本": "当前PDF"})
        )
        result = await run_g5(
            handle.workspace.db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            beauty_baseline_pages=10, compile_paper=_compile,
        )
        assert result["pass"] is True, result["issues"]
    finally:
        handle.workspace.db.close()


# ==================== G5 authoritative rework closure (round2 P1-2) ====================

def _seed_ledger(root: Path, rows: list[dict]) -> None:
    """Build a valid S5 ledger carrier via 并入 → 快照, then apply overrides."""
    from mmagent.mm.ledger.issue_ledger import IssueLedger
    ledger = IssueLedger(前缀="审")
    ledger.并入([
        {k: v for k, v in row.items() if k not in ("状态", "尝试次数", "generation")}
        for row in rows
    ], 轮次=1)
    snapshot = ledger.快照()
    for row, overrides in zip(snapshot, rows, strict=True):
        for k in ("状态", "尝试次数", "generation"):
            if k in overrides:
                row[k] = overrides[k]
    (root / "台账").mkdir(parents=True, exist_ok=True)
    (root / "台账" / "审稿台账.json").write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_g5_rework_figure_receipt_then_verdict_resolves_issue(tmp_path: Path) -> None:
    """R49: plotter receipt → 收回执(待复核) → hunter 逐项裁定 → 已消解，
    且状态迁移持久化到台账 carrier（durable writeback）。"""
    from mmagent.api.projects import create_project
    from mmagent.mm.pipeline.s5_finalize import run_g5_rework
    handle = create_project(tmp_path / "proj", name="g5fig", profile="快速")
    try:
        root = handle.workspace.root
        _seed_publishable(root)
        _seed_ledger(root, [{
            "级别": "硬伤", "目标": "图", "定位": "问题3 图4",
            "问题": "图内数字与正文不一致",
        }])
        db = handle.workspace.db
        run_id = repositories.create_run(db, project_id=handle.project_id, profile="快速")
        script = MockScript(
            _write("p", "审稿/回执_G5R1_图问3.json",
                   [{"id": "审-1-01", "改动": "同步图内数字为 3.14", "证据": "脚本 diff"}])
            + _write("h", "审稿/G5复核1.json",
                     {"通过": True, "依据版本": "当前PDF",
                      "逐项": [{"id": "审-1-01", "裁定": "已消解", "理由": "图已同步"}]})
            + _write("f", "审稿/G5复核.json", {"通过": True, "依据版本": "当前PDF"})
        )
        result = await run_g5_rework(
            db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            beauty_baseline_pages=10, compile_paper=_compile,
        )
        assert result["pass"] is True, result["issues"]
        assert result["rework_rounds"] == 1
        # Durable writeback: transitions must be on disk, not just in memory.
        rows = json.loads(
            (root / "台账" / "审稿台账.json").read_text(encoding="utf-8")
        )
        assert rows[0]["状态"] == "已消解"
        assert any(rc.get("receipt_id") == "g5r1_fig3" for rc in rows[0]["回执"])
        assert any(h.get("裁定") == "已消解" for h in rows[0]["历史"])
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_g5_rework_calc_upsert_preserves_s2_entries(tmp_path: Path) -> None:
    """R50: 算类搁置 + 降级放行 upsert 不得清空 S2 的 question 条目。"""
    from mmagent.api.projects import create_project
    from mmagent.mm.contracts.degraded_release import (
        DegradedQuestionEntry,
        read_degraded_release,
        upsert_degraded_review_issue,
        write_degraded_release,
    )
    from mmagent.mm.pipeline.s5_finalize import run_g5_rework
    handle = create_project(tmp_path / "proj", name="g5calc", profile="快速")
    try:
        root = handle.workspace.root
        _seed_publishable(root)
        _seed_ledger(root, [{
            "级别": "正确性", "目标": "算", "定位": "问题2 结果",
            "问题": "求解结果无法复现", "尝试次数": 2,
        }])
        write_degraded_release(root, question_entries=[
            DegradedQuestionEntry(question=2, issues=["输入数据缺失"], source_stage="S2")
        ])
        upsert_degraded_review_issue(
            root,
            issue_id="审-1-01",
            generation=0,
            severity="正确性",
            reason="S5 escalation exhausted",
            source_stage="S5",
        )
        db = handle.workspace.db
        run_id = repositories.create_run(db, project_id=handle.project_id, profile="快速")
        script = MockScript(
            _write("h", "审稿/G5复核1.json", {"通过": True, "依据版本": "当前PDF"})
            + _write("f", "审稿/G5复核.json", {"通过": True, "依据版本": "当前PDF"})
        )
        result = await run_g5_rework(
            db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            beauty_baseline_pages=10, compile_paper=_compile,
        )
        assert result["pass"] is True, result["issues"]
        carrier = read_degraded_release(root)
        assert carrier is not None
        # S2 question entry preserved alongside the G5 review-issue entry.
        assert any(q.question == 2 for q in carrier.questions)
        assert any(e.id == "审-1-01" and e.generation == 0 for e in carrier.review_issues)
        rows = json.loads(
            (root / "台账" / "审稿台账.json").read_text(encoding="utf-8")
        )
        assert rows[0]["状态"] == "搁置"
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_g5_rework_stale_verdict_generation_is_rejected(tmp_path: Path) -> None:
    """CAS fail-closed：hunter 带过期 generation 的裁定不得翻转条目状态。"""
    from mmagent.api.projects import create_project
    from mmagent.mm.pipeline.s5_finalize import run_g5_rework
    handle = create_project(tmp_path / "proj", name="g5stale", profile="快速")
    try:
        root = handle.workspace.root
        _seed_publishable(root)
        _seed_ledger(root, [{
            "级别": "硬伤", "目标": "图", "定位": "问题3 图4",
            "问题": "图内数字与正文不一致",
        }])
        db = handle.workspace.db
        run_id = repositories.create_run(db, project_id=handle.project_id, profile="快速")
        script = MockScript(
            _write("p", "审稿/回执_G5R1_图问3.json",
                   [{"id": "审-1-01", "改动": "同步图内数字", "证据": "diff"}])
            + _write("h", "审稿/G5复核1.json",
                     {"通过": True, "依据版本": "当前PDF",
                      "逐项": [{"id": "审-1-01", "generation": 99,
                                "裁定": "已消解", "理由": "过期裁定"}]})
            + _write("f", "审稿/G5复核.json", {"通过": True, "依据版本": "当前PDF"})
        )
        result = await run_g5_rework(
            db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            beauty_baseline_pages=10, compile_paper=_compile,
        )
        # Receipt moved the issue to 待复核; the stale verdict must not have
        # resolved it.  At loop end the missed-verdict path honestly marks it
        # 评审未裁 (待改), so the mechanical gate still sees an active row.
        rows = json.loads(
            (root / "台账" / "审稿台账.json").read_text(encoding="utf-8")
        )
        assert rows[0]["状态"] != "已消解"
        assert any(h.get("裁定") == "评审未裁" for h in rows[0]["历史"])
        assert result["pass"] is False
    finally:
        handle.workspace.db.close()


# ==================== E8: bounded compile-repair protocol ====================

@pytest.mark.asyncio
async def test_compile_repair_uses_writer_leg_then_recovers(tmp_path: Path) -> None:
    """E8: compile failure → writer leg with log errors + REQUIRED receipt →
    recompile succeeds.  A successful initial compile runs no legs at all."""
    from mmagent.api.projects import create_project
    from mmagent.mm.pipeline.compile_repair import run_compile_repair

    handle = create_project(tmp_path / "proj-fix", name="cfix", profile="快速")
    try:
        root = handle.workspace.root
        (root / "论文").mkdir(parents=True, exist_ok=True)
        (root / "论文" / "论文.tex").write_text("正文", encoding="utf-8")
        db = handle.workspace.db
        run_id = repositories.create_run(db, project_id=handle.project_id, profile="快速")

        calls: list[dict] = []

        def flaky_compiler(root_: Path) -> dict:
            calls.append({"n": len(calls)})
            if len(calls) == 1:
                (root_ / "论文" / "论文.log").write_text(
                    "! LaTeX Error: File missing.sty not found.", encoding="utf-8"
                )
                return {"rc": 1, "errors": ["! LaTeX Error: File missing.sty not found."],
                        "pages": 0}
            return {"rc": 0, "errors": [], "pages": 10}

        script = MockScript(
            _write("fix", "审稿/回执_编译修复_S4_1.json",
                   [{"改动": "补上缺失宏包", "证据": "论文/论文.tex"}])
        )
        result = await run_compile_repair(
            db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            flaky_compiler, stage_key="S4",
        )
        assert result["rc"] == 0 and result["pages"] == 10
        assert len(calls) == 2
        evs = events.query_events(
            db, run_id=run_id, type="compile.repair_attempt"
        )
        assert len(evs) == 1 and evs[0].payload["attempt"] == 1

        # Clean compile → no repair legs, no new events.
        before = len(events.query_events(
            db, run_id=run_id, type="compile.repair_attempt"
        ))
        script2 = MockScript([])
        result2 = await run_compile_repair(
            db, MockProvider(script2), _registry(), PathPolicy(root), run_id,
            lambda _r: {"rc": 0, "errors": [], "pages": 10}, stage_key="S4",
        )
        assert result2["rc"] == 0
        after = len(events.query_events(
            db, run_id=run_id, type="compile.repair_attempt"
        ))
        assert after == before == 1
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_compile_repair_without_receipt_stops_bounded(tmp_path: Path) -> None:
    """E8: a repair leg that writes no receipt ends the loop immediately and
    the last failing compile result is returned (fail-closed)."""
    from mmagent.api.projects import create_project
    from mmagent.mm.pipeline.compile_repair import run_compile_repair

    handle = create_project(tmp_path / "proj-nofix", name="cnofix", profile="快速")
    try:
        root = handle.workspace.root
        (root / "论文").mkdir(parents=True, exist_ok=True)
        (root / "论文" / "论文.tex").write_text("正文", encoding="utf-8")
        db = handle.workspace.db
        run_id = repositories.create_run(db, project_id=handle.project_id, profile="快速")

        def broken_compiler(_root: Path) -> dict:
            return {"rc": 1, "errors": ["! Emergency stop."], "pages": 0}

        # Text-only turns: the leg completes but writes no receipt → FAILED
        # (initial attempt + the wave's single retry).
        script = MockScript([MockTurn(text="我不改"), MockTurn(text="我不改")])
        result = await run_compile_repair(
            db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            broken_compiler, stage_key="S4", max_attempts=2,
        )
        assert result["rc"] == 1
        evs = events.query_events(db, run_id=run_id, type="compile.repair_attempt")
        assert len(evs) == 1 and evs[0].payload["status"] != "SUCCEEDED"
    finally:
        handle.workspace.db.close()


# ==================== B9: structure guard R38③/R68⑤ + guard rollback ====================

def test_structure_guard_appendix_lstlisting_shrink_detected() -> None:
    from mmagent.mm.guards.guards import structure_guard
    lst = "\\begin{lstlisting}"
    endlst = "\\end{lstlisting}"
    old = {
        "论文/8.1.问题1源码.tex": (
            f"{lst}\ndef a():\n    pass\n{endlst}\n"
            f"{lst}\ndef b():\n    pass\n{endlst}\n"
        ),
    }
    new = {"论文/8.1.问题1源码.tex": f"{lst}\ndef a():\n{endlst}\n"}
    ok, issues = structure_guard(old, new)
    assert not ok
    assert any("附录源码清单减少" in x for x in issues)


def test_structure_guard_body_graphics_move_detected() -> None:
    from mmagent.mm.guards.guards import structure_guard
    old = {
        "论文/4.模型求解.tex": "\\includegraphics{a.png}\n\\includegraphics{b.png}\n",
        "论文/8.7.补充验证.tex": "补充。\n",
    }
    moved = {
        "论文/4.模型求解.tex": "\\includegraphics{a.png}\n",
        "论文/8.7.补充验证.tex": "\\includegraphics{b.png}\n补充。\n",
    }
    ok, issues = structure_guard(old, moved)
    assert not ok
    assert any("正文插图减少" in x for x in issues)
    assert any("接收挪入插图" in x for x in issues)


@pytest.mark.asyncio
async def test_g5_rework_text_leg_violating_guard_is_reverted(tmp_path: Path) -> None:
    """R38: a G5 text repair leg that deletes body graphics gets rolled back,
    its receipt must not resolve the issue, and the final gate fails closed."""
    from mmagent.api.projects import create_project
    from mmagent.mm.pipeline.s5_finalize import run_g5_rework

    handle = create_project(tmp_path / "proj-guard", name="g5guard", profile="快速")
    try:
        root = handle.workspace.root
        _seed_publishable(root)
        _seed_ledger(root, [{
            "级别": "硬伤", "目标": "文", "定位": "论文/论文.tex",
            "问题": "表述与结果不一致",
        }])
        body = root / "论文" / "4.模型.tex"
        body.write_text(
            "\\includegraphics{a.png}\n正文没有统计数字。\n", encoding="utf-8"
        )
        db = handle.workspace.db
        run_id = repositories.create_run(db, project_id=handle.project_id, profile="快速")
        script = MockScript(
            # The repair leg "fixes" the wording but illegally removes the figure.
            _write("w", "论文/4.模型.tex", "改正后的表述。\n")
            + _write("p", "审稿/回执_G5R1_文.json",
                     [{"id": "审-1-01", "改动": "改正表述", "证据": "论文/4.模型.tex"}])
            + _write("h", "审稿/G5复核1.json", {"通过": True, "依据版本": "当前PDF"})
            + _write("f", "审稿/G5复核.json", {"通过": True, "依据版本": "当前PDF"})
        )
        result = await run_g5_rework(
            db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            beauty_baseline_pages=10, compile_paper=_compile,
        )
        # Guard rolled the paper back to the snapshot with the figure intact.
        assert "\\includegraphics{a.png}" in body.read_text(encoding="utf-8")
        assert not (root / "论文" / "4.模型.tex").read_text(
            encoding="utf-8"
        ).startswith("改正后")
        rows = json.loads(
            (root / "台账" / "审稿台账.json").read_text(encoding="utf-8")
        )
        assert rows[0]["状态"] != "已消解"
        assert result["pass"] is False
        reverts = events.query_events(
            db, run_id=run_id, type="guard.structure_revert"
        )
        assert len(reverts) == 1
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_g5_calc_blocker_without_prior_degraded_approval_fails_closed(
    tmp_path: Path,
) -> None:
    from mmagent.api.projects import create_project
    from mmagent.mm.pipeline.s5_finalize import run_g5_rework

    handle = create_project(tmp_path / "proj", name="g5calc-noapproval", profile="快速")
    try:
        root = handle.workspace.root
        _seed_publishable(root)
        _seed_ledger(root, [{
            "级别": "正确性", "目标": "算", "定位": "问题2 结果",
            "问题": "求解结果无法复现", "尝试次数": 2,
        }])
        db = handle.workspace.db
        run_id = repositories.create_run(
            db, project_id=handle.project_id, profile="快速"
        )
        script = MockScript(
            _write("h", "审稿/G5复核1.json", {"通过": True, "依据版本": "当前PDF"})
            + _write("h2", "审稿/G5复核2.json", {"通过": True, "依据版本": "当前PDF"})
            + _write("h3", "审稿/G5复核3.json", {"通过": True, "依据版本": "当前PDF"})
            + _write("f", "审稿/G5复核.json", {"通过": True, "依据版本": "当前PDF"})
        )
        result = await run_g5_rework(
            db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            beauty_baseline_pages=10, compile_paper=_compile,
        )
        assert result["pass"] is False
        rows = json.loads(
            (root / "台账" / "审稿台账.json").read_text(encoding="utf-8")
        )
        assert rows[0]["状态"] != "搁置"
    finally:
        handle.workspace.db.close()


def test_structure_guard_detects_neutral_named_code_chapter_by_content() -> None:
    from mmagent.mm.guards.guards import structure_guard

    lst = "\\begin{lstlisting}"
    endlst = "\\end{lstlisting}"
    old = {
        "论文/8.7.补充.tex": (
            f"{lst}\nprint('a')\n{endlst}\n"
            f"{lst}\nprint('b')\n{endlst}\n"
        )
    }
    new = {
        "论文/8.7.补充.tex": f"{lst}\nprint('a')\n{endlst}\n"
    }
    ok, issues = structure_guard(old, new)
    assert not ok
    assert any("附录源码清单减少" in x for x in issues)
