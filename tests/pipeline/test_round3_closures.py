"""Round-3 distinguishing behavior tests (P1-A/P1-B/P1-C local validation).

These tests drive the REAL production paths — run_s5(), run_g5_rework(),
verified recompute/escalation primitives, IssueLedger transitions, event
persistence and filesystem mutation — through MockProvider scripts.  They
distinguish the new semantics from the old ones:

- a Modeler/Plotter receipt alone can never move an Issue to 待复核;
- S5 calc repair executes solver → red-team → G2 → downstream cascade →
  change manifests → plot rerun → guarded writer sync before any receipt;
- escalation winner promotion makes one canonical solver/result truth;
- guarded repair carries a durable pre-repair snapshot and reverts broad
  rewrites (0.45) while escalated repairs use 0.70.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.mm.guards.guards import change_guard
from mmagent.mm.ledger.issue_ledger import IssueLedger
from mmagent.mm.pipeline.s5_finalize import run_g5_rework
from mmagent.mm.pipeline.s5_review import run_s5
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


def _write_turn(call_id: str, path: str, payload: object) -> list[MockTurn]:
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return [
        MockTurn(tool_calls=[(call_id, "fs.write", {"path": path, "content": content})]),
        MockTurn(text="完成"),
    ]


def _multi_write_turn(call_id: str, writes: list[tuple[str, object]]) -> list[MockTurn]:
    calls = [
        (f"{call_id}-{i}", "fs.write", {
            "path": p,
            "content": c if isinstance(c, str) else json.dumps(c, ensure_ascii=False),
        })
        for i, (p, c) in enumerate(writes)
    ]
    return [MockTurn(tool_calls=calls), MockTurn(text="完成")]


def _empty_leg(turn_id: str, path: str) -> list[MockTurn]:
    return _write_turn(turn_id, path, {"意见": [], "裁定": []})


def _verdict_leg(turn_id: str, path: str, verdicts: list[dict]) -> list[MockTurn]:
    return _write_turn(turn_id, path, {
        "总分": 8.0, "相对判断": "持平", "意见": [], "裁定": verdicts,
    })


def _raise_issue_leg(turn_id: str, path: str, issue: dict) -> list[MockTurn]:
    return _write_turn(turn_id, path, {"总分": 8.0, "意见": [issue], "裁定": []})


def _fake_compile(root: Path) -> dict:
    (root / "论文").mkdir(parents=True, exist_ok=True)
    (root / "论文" / "论文.log").write_text(
        "Output written on 论文.pdf (10 pages).", encoding="utf-8"
    )
    (root / "论文" / "论文.pdf").write_bytes(b"%PDF-test")
    return {"rc": 0, "errors": [], "pages": 10}


def _fake_render(root: Path) -> list[Path]:
    page_dir = root / "论文" / "页"
    page_dir.mkdir(parents=True, exist_ok=True)
    page = page_dir / "page-001.png"
    page.write_bytes(b"PNG")
    return [page]


def _seed_workspace(tmp_path: Path, name: str, *, plan: list[dict] | None = None):
    from mmagent.api.projects import create_project
    handle = create_project(tmp_path / name, name=name, profile="标准")
    root = handle.workspace.root
    (root / "论文").mkdir(parents=True, exist_ok=True)
    (root / "论文" / "论文.tex").write_text("正文内容。", encoding="utf-8")
    (root / "论文" / "0.摘要.tex").write_text("摘要内容。", encoding="utf-8")
    (root / "交接").mkdir(parents=True, exist_ok=True)
    (root / "交接" / "需求追踪矩阵.json").write_text(
        json.dumps([{"需求号": "一", "状态": "已销号"}], ensure_ascii=False),
        encoding="utf-8",
    )
    if plan is not None:
        (root / "交接" / "计划.json").write_text(
            json.dumps({"问题清单": plan}, ensure_ascii=False), encoding="utf-8"
        )
    run_id = repositories.create_run(
        handle.workspace.db, project_id=handle.project_id, profile="标准"
    )
    return handle, run_id


def _seed_ledger(root: Path, rows: list[dict]) -> None:
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


def _ledger_rows(root: Path) -> list[dict]:
    return json.loads(
        (root / "台账" / "审稿台账.json").read_text(encoding="utf-8")
    )


def _seed_plan(root: Path, rows: list[dict]) -> None:
    (root / "交接" / "计划.json").write_text(
        json.dumps({"问题清单": rows}, ensure_ascii=False), encoding="utf-8"
    )


def _seed_plot_script(root: Path, question: int) -> None:
    script = root / "求解" / f"问题{question}" / "绘图_图1.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "from pathlib import Path\n"
        f"p = Path('求解/问题{question}/图片')\n"
        "p.mkdir(parents=True, exist_ok=True)\n"
        "(p / '图1.png').write_bytes(b'PNG')\n",
        encoding="utf-8",
    )


_SOLVER_TEMPLATE = (
    "import json\nfrom pathlib import Path\n"
    "p = Path({result_dir!r})\n"
    "p.mkdir(parents=True, exist_ok=True)\n"
    "(p / '结果.json').write_text(json.dumps({{{key!r}: {value!r}}}), encoding='utf-8')\n"
)


def _solver_script(result_dir: str, key: str, value: float, filename: str = "结果.json") -> str:
    return (
        "import json\nfrom pathlib import Path\n"
        f"p = Path({result_dir!r})\n"
        "p.mkdir(parents=True, exist_ok=True)\n"
        f"(p / {filename!r}).write_text(json.dumps({{{key!r}: {value!r}}}), encoding='utf-8')\n"
    )


def _recompute_turns(prefix: str, q: int, value: float) -> list[MockTurn]:
    """One verified recompute: modeler → runtime run → interpreter →
    red-team script → runtime run → red-team report (aligned)."""
    turns: list[MockTurn] = []
    turns += _write_turn(
        f"{prefix}-solver",
        f"求解/问题{q}/求解_问题{q}.py",
        _solver_script(f"求解/问题{q}/结果", "厚度", value),
    )
    turns += _multi_write_turn(f"{prefix}-decl", [
        (f"交接/结果声明_问题{q}.json", {"问题编号": q, "核心指标": {"厚度": value}}),
        (f"交接/结果解读_问题{q}.md", f"问题{q} 厚度为 {value}。"),
    ])
    turns += _write_turn(
        f"{prefix}-red",
        f"求解/问题{q}/复算.py",
        _solver_script(f"求解/问题{q}/红队结果", "厚度", value, filename="复算.json"),
    )
    turns += _write_turn(
        f"{prefix}-report",
        f"交接/红队_问题{q}.json",
        {"问题编号": q, "结论": "对齐", "分歧明细": []},
    )
    return turns


def _escalation_turns(prefix: str, q: int, value: float) -> list[MockTurn]:
    """Verified escalation: 3 variant legs → adjudication (获胜变体) →
    red-team script → red-team report."""
    turns: list[MockTurn] = []
    for idx in (1, 2, 3):
        turns += _write_turn(
            f"{prefix}-v{idx}",
            f"求解/问题{q}/升格/变体{idx}/求解.py",
            _solver_script(f"求解/问题{q}/升格/变体{idx}/结果", "厚度", value),
        )
    turns += _multi_write_turn(f"{prefix}-adj", [
        (f"交接/升格裁决_问题{q}.json", {"获胜变体": 1, "理由": "变体1 证据最充分"}),
        (f"交接/结果声明_问题{q}.json", {"问题编号": q, "核心指标": {"厚度": value}}),
    ])
    turns += _write_turn(
        f"{prefix}-red",
        f"求解/问题{q}/复算.py",
        _solver_script(f"求解/问题{q}/红队结果", "厚度", value, filename="复算.json"),
    )
    turns += _write_turn(
        f"{prefix}-report",
        f"交接/红队_问题{q}.json",
        {"问题编号": q, "结论": "对齐", "分歧明细": []},
    )
    return turns


# ==================== P1-A: S5 calc verified cascade ====================

@pytest.mark.asyncio
async def test_s5_calc_repair_runs_solver_redteam_g2_and_downstream(
    tmp_path: Path,
) -> None:
    """Normal S5 calc repair must execute the verified recompute protocol for
    the source question AND all downstream questions, write change manifests,
    and only then create a ledger receipt."""
    handle, run_id = _seed_workspace(
        tmp_path, "s5-calc-cascade",
        plan=[
            {"编号": 1, "依赖问题": [], "主方法": "A"},
            {"编号": 2, "依赖问题": [1], "主方法": "B"},
            {"编号": 3, "依赖问题": [2], "主方法": "C"},
        ],
    )
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        _seed_plot_script(root, 1)
        _seed_plot_script(root, 2)
        _seed_plot_script(root, 3)
        for q in (1, 2, 3):
            _seed_plot_script(root, q)
        issue = {
            "级别": "硬伤", "目标": "算", "定位": "问题1 结果",
            "问题": "问题1 求解结果与数据不符",
            "指令": "按验证协议重算问题1", "验收": "G2 通过且下游一致",
        }
        turns: list[MockTurn] = []
        turns += _raise_issue_leg("r1a", "审稿/审稿意见_轮1A.json", issue)
        turns += _empty_leg("r1b", "审稿/审稿意见_轮1B.json")
        turns += _empty_leg("h1", "审稿/硬伤_轮1.json")
        turns += _empty_leg("j1", "审稿/评委模拟_轮1.json")
        turns += _recompute_turns("q1", 1, 2.17)
        turns += _recompute_turns("q2", 2, 2.17)
        turns += _recompute_turns("q3", 3, 2.17)
        turns += _write_turn(
            "sync1", "审稿/回执_S5R1_算级联问1.json",
            [{"id": "审-1-01", "改动": "同步正文数字与图题", "证据": "论文/论文.tex"}],
        )
        turns += _verdict_leg(
            "r2a", "审稿/审稿意见_轮2A.json",
            [{"id": "审-1-01", "generation": 0, "裁定": "已消解", "理由": "级联完成"}],
        )
        turns += _empty_leg("r2b", "审稿/审稿意见_轮2B.json")
        turns += _empty_leg("h2", "审稿/硬伤_轮2.json")
        turns += _empty_leg("j2", "审稿/评委模拟_轮2.json")
        result = await run_s5(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            max_rounds=2, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        assert result["converged"] is True, result["ledger_summary"]
        # Verified protocol events, in the durable event log.
        assert events.query_events(db, run_id=run_id, type="s5.calc_cascade_started")
        assert events.query_events(db, run_id=run_id, type="s5.calc_cascade_succeeded")
        inv = events.query_events(
            db, run_id=run_id, type="pipeline.s2_downstream_invalidated"
        )
        assert any(
            e.payload.get("source") == "S5"
            and sorted(e.payload.get("downstream") or []) == [2, 3]
            for e in inv
        )
        # Fresh S2 checkpoints for every affected question.
        checkpoints = events.query_events(
            db, run_id=run_id, type="checkpoint.s2_question"
        )
        assert sorted(e.payload["question"] for e in checkpoints) == [1, 2, 3]
        assert all(e.payload.get("source") == "S5_calc_cascade" for e in checkpoints)
        # Change manifests frozen before carrier propagation.
        manifest = json.loads(
            (root / "交接" / "换版清单_问题1.json").read_text(encoding="utf-8")
        )
        assert manifest["来源"] == "S5 verified calc cascade"
        # Solver actually executed through the Runtime boundary.
        assert (root / "求解" / "问题1" / "结果" / "结果.json").is_file()
        assert (root / "求解" / "问题3" / "红队结果" / "复算.json").is_file()
        rows = _ledger_rows(root)
        assert rows[0]["状态"] == "已消解"
        assert rows[0]["回执"]
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s5_calc_failure_does_not_create_ledger_receipt(tmp_path: Path) -> None:
    """A failing verified recompute (solver crash) must leave the Issue active
    with no ledger receipt — no receipt self-certification."""
    handle, run_id = _seed_workspace(
        tmp_path, "s5-calc-fail", plan=[{"编号": 1, "依赖问题": [], "主方法": "A"}],
    )
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        issue = {
            "级别": "硬伤", "目标": "算", "定位": "问题1 结果",
            "问题": "问题1 求解结果与数据不符",
            "指令": "按验证协议重算问题1", "验收": "G2 通过且下游一致",
        }
        turns: list[MockTurn] = []
        turns += _raise_issue_leg("r1a", "审稿/审稿意见_轮1A.json", issue)
        turns += _empty_leg("r1b", "审稿/审稿意见_轮1B.json")
        turns += _empty_leg("h1", "审稿/硬伤_轮1.json")
        turns += _empty_leg("j1", "审稿/评委模拟_轮1.json")
        # Modeler writes a crashing solver; the Runtime execution fails.
        turns += _write_turn(
            "q1-solver", "求解/问题1/求解_问题1.py",
            "raise RuntimeError('boom')\n",
        )
        # R2 review legs (final round; rework only runs in non-final rounds).
        turns += _empty_leg("r2a", "审稿/审稿意见_轮2A.json")
        turns += _empty_leg("r2b", "审稿/审稿意见_轮2B.json")
        turns += _empty_leg("h2", "审稿/硬伤_轮2.json")
        turns += _empty_leg("j2", "审稿/评委模拟_轮2.json")
        result = await run_s5(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            max_rounds=2, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        failed = events.query_events(db, run_id=run_id, type="s5.calc_cascade_failed")
        assert len(failed) == 1
        assert failed[0].payload["step"] == "verified_recompute"
        assert not events.query_events(db, run_id=run_id, type="s5.calc_cascade_succeeded")
        assert not events.query_events(db, run_id=run_id, type="checkpoint.s2_question")
        rows = _ledger_rows(root)
        assert rows[0]["状态"] == "待改"
        assert rows[0]["回执"] == []
        assert result["converged"] is False
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s5_calc_cascade_writes_change_manifest_before_text_sync(
    tmp_path: Path,
) -> None:
    """The change manifest is frozen BEFORE the guarded writer sync; a failed
    sync must still leave the manifest on disk so stale-value gates can see
    the numerical delta (fail closed)."""
    handle, run_id = _seed_workspace(
        tmp_path, "s5-calc-manifest", plan=[{"编号": 1, "依赖问题": [], "主方法": "A"}],
    )
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        # Pre-existing declaration: 厚度 2.0. The recompute refreshes it to 2.17.
        (root / "交接" / "结果声明_问题1.json").write_text(
            json.dumps({"问题编号": 1, "核心指标": {"厚度": 2.0}}, ensure_ascii=False),
            encoding="utf-8",
        )
        _seed_plot_script(root, 1)
        issue = {
            "级别": "硬伤", "目标": "算", "定位": "问题1 结果",
            "问题": "问题1 求解结果与数据不符",
            "指令": "按验证协议重算问题1", "验收": "G2 通过且下游一致",
        }
        turns: list[MockTurn] = []
        turns += _raise_issue_leg("r1a", "审稿/审稿意见_轮1A.json", issue)
        turns += _empty_leg("r1b", "审稿/审稿意见_轮1B.json")
        turns += _empty_leg("h1", "审稿/硬伤_轮1.json")
        turns += _empty_leg("j1", "审稿/评委模拟_轮1.json")
        turns += _recompute_turns("q1", 1, 2.17)
        # Writer sync leg never writes its receipt (initial attempt + retry).
        turns += [MockTurn(text="拒绝同步"), MockTurn(text="拒绝同步")]
        # R2 review legs (final round; rework only runs in non-final rounds).
        turns += _empty_leg("r2a", "审稿/审稿意见_轮2A.json")
        turns += _empty_leg("r2b", "审稿/审稿意见_轮2B.json")
        turns += _empty_leg("h2", "审稿/硬伤_轮2.json")
        turns += _empty_leg("j2", "审稿/评委模拟_轮2.json")
        result = await run_s5(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            max_rounds=2, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        failed = events.query_events(db, run_id=run_id, type="s5.calc_cascade_failed")
        assert len(failed) == 1
        assert failed[0].payload["step"] == "writer_sync"
        # The manifest survived the sync failure and records the delta.
        manifest = json.loads(
            (root / "交接" / "换版清单_问题1.json").read_text(encoding="utf-8")
        )
        assert any(
            e["旧值"] == "2.0" and e["新值"] == "2.17" for e in manifest["条目"]
        )
        rows = _ledger_rows(root)
        assert rows[0]["状态"] == "待改"
        assert rows[0]["回执"] == []
        assert result["converged"] is False
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s5_calc_escalation_promotes_winner_to_canonical_truth(
    tmp_path: Path,
) -> None:
    """S5 calc fuse escalation must run the verified escalation (3 variants →
    获胜变体 adjudication → Runtime promotion) before red-team/G2 and receipt.

    The issue is driven through two real verified-recompute repair rounds
    (尝试=2) so the fuse fires in round 3; the accepted escalation earns the
    extension round where the reviewer resolves it."""
    handle, run_id = _seed_workspace(
        tmp_path, "s5-calc-esc", plan=[{"编号": 1, "依赖问题": [], "主方法": "A"}],
    )
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        _seed_plot_script(root, 1)
        issue = {
            "级别": "硬伤", "目标": "算", "定位": "问题1 结果",
            "问题": "问题1 求解路线失败",
            "指令": "换技术路线重做问题1", "验收": "G2 通过",
        }
        turns: list[MockTurn] = []
        # R1: issue raised → verified recompute (尝试=1).
        turns += _raise_issue_leg("r1a", "审稿/审稿意见_轮1A.json", issue)
        turns += _empty_leg("r1b", "审稿/审稿意见_轮1B.json")
        turns += _empty_leg("h1", "审稿/硬伤_轮1.json")
        turns += _empty_leg("j1", "审稿/评委模拟_轮1.json")
        turns += _recompute_turns("q1r1", 1, 2.17)
        turns += _write_turn(
            "sync1", "审稿/回执_S5R1_算级联问1.json",
            [{"id": "审-1-01", "改动": "按新结果同步正文", "证据": "论文/论文.tex"}],
        )
        # R2: verdict 未消解 → verified recompute again (尝试=2).
        turns += _verdict_leg(
            "r2a", "审稿/审稿意见_轮2A.json",
            [{"id": "审-1-01", "generation": 0, "裁定": "未消解", "理由": "仍不一致"}],
        )
        turns += _empty_leg("r2b", "审稿/审稿意见_轮2B.json")
        turns += _empty_leg("h2", "审稿/硬伤_轮2.json")
        turns += _empty_leg("j2", "审稿/评委模拟_轮2.json")
        turns += _recompute_turns("q1r2", 1, 2.17)
        turns += _write_turn(
            "sync2", "审稿/回执_S5R2_算级联问1.json",
            [{"id": "审-1-01", "改动": "再次同步正文", "证据": "论文/论文.tex"}],
        )
        # R3: verdict 未消解 → fuse escalates → verified escalation.
        turns += _verdict_leg(
            "r3a", "审稿/审稿意见_轮3A.json",
            [{"id": "审-1-01", "generation": 0, "裁定": "未消解", "理由": "仍不一致"}],
        )
        turns += _empty_leg("r3b", "审稿/审稿意见_轮3B.json")
        turns += _empty_leg("h3", "审稿/硬伤_轮3.json")
        turns += _empty_leg("j3", "审稿/评委模拟_轮3.json")
        turns += _escalation_turns("q1esc", 1, 3.14)
        turns += _write_turn(
            "sync3", "审稿/回执_S5R3_算级联问1_升格.json",
            [{"id": "审-1-01", "改动": "按获胜变体同步正文", "证据": "论文/论文.tex"}],
        )
        # Extension round: the reviewer resolves the escalated issue.
        turns += _verdict_leg(
            "r4a", "审稿/审稿意见_轮4A.json",
            [{"id": "审-1-01", "generation": 0, "裁定": "已消解", "理由": "升格成功"}],
        )
        turns += _empty_leg("r4b", "审稿/审稿意见_轮4B.json")
        turns += _empty_leg("h4", "审稿/硬伤_轮4.json")
        turns += _empty_leg("j4", "审稿/评委模拟_轮4.json")
        result = await run_s5(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            max_rounds=3, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        assert result["converged"] is True, result["ledger_summary"]
        assert events.query_events(
            db, run_id=run_id, type="checkpoint.s5_escalation_extension"
        )
        promoted = events.query_events(
            db, run_id=run_id, type="pipeline.s2_escalation_promoted"
        )
        assert len(promoted) == 1
        assert promoted[0].payload["winner"] == 1
        # The winning variant was promoted into the canonical carrier.
        canonical_solver = (root / "求解" / "问题1" / "求解_问题1.py")
        variant_solver = (root / "求解" / "问题1" / "升格" / "变体1" / "求解.py")
        assert canonical_solver.read_text(encoding="utf-8") == (
            variant_solver.read_text(encoding="utf-8")
        )
        assert (root / "求解" / "问题1" / "结果" / "结果.json").is_file()
        decision = json.loads(
            (root / "交接" / "升格裁决_问题1.json").read_text(encoding="utf-8")
        )
        assert decision["获胜变体"] == 1
        cascades = events.query_events(
            db, run_id=run_id, type="s5.calc_cascade_succeeded"
        )
        assert any(e.payload.get("escalated") for e in cascades)
        assert events.query_events(db, run_id=run_id, type="s5.escalation_succeeded")
        rows = _ledger_rows(root)
        assert rows[0]["状态"] == "已消解"
    finally:
        handle.workspace.db.close()


# ==================== P1-B: figure repair transactions ====================

@pytest.mark.asyncio
async def test_s5_figure_receipt_alone_cannot_advance_issue(tmp_path: Path) -> None:
    """A plotter receipt without a Runtime-executed plot script must not move
    the Issue to 待复核."""
    handle, run_id = _seed_workspace(tmp_path, "s5-fig-alone")
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        issue = {
            "级别": "硬伤", "目标": "图", "定位": "问题3 图4",
            "问题": "问题3 图内数字过期",
            "指令": "重绘问题3 的图并同步正文", "验收": "图与结果一致",
        }
        turns: list[MockTurn] = []
        turns += _raise_issue_leg("r1a", "审稿/审稿意见_轮1A.json", issue)
        turns += _empty_leg("r1b", "审稿/审稿意见_轮1B.json")
        turns += _empty_leg("h1", "审稿/硬伤_轮1.json")
        turns += _empty_leg("j1", "审稿/评委模拟_轮1.json")
        # The plotter writes a receipt, but no plot script exists.
        turns += _write_turn(
            "p1", "审稿/回执_R1_图问3.json",
            [{"id": "审-1-01", "改动": "改了脚本", "证据": "diff"}],
        )
        # R2 review legs (final round; rework only runs in non-final rounds).
        turns += _empty_leg("r2a", "审稿/审稿意见_轮2A.json")
        turns += _empty_leg("r2b", "审稿/审稿意见_轮2B.json")
        turns += _empty_leg("h2", "审稿/硬伤_轮2.json")
        turns += _empty_leg("j2", "审稿/评委模拟_轮2.json")
        result = await run_s5(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            max_rounds=2, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        failed = events.query_events(db, run_id=run_id, type="s5.figure_repair_failed")
        assert len(failed) == 1
        assert failed[0].payload["step"] == "plot_runtime"
        assert not events.query_events(db, run_id=run_id, type="s5.figure_repair_succeeded")
        # The receipt file exists on disk, but the ledger never accepted it.
        assert (root / "审稿" / "回执_R1_图问3.json").is_file()
        rows = _ledger_rows(root)
        assert rows[0]["状态"] == "待改"
        assert rows[0]["回执"] == []
        assert result["converged"] is False
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s5_figure_transaction_requires_plot_execution_and_writer_sync(
    tmp_path: Path,
) -> None:
    """Plotter receipt → Runtime executes the plot → guarded writer sync →
    only then a combined runtime receipt is accepted."""
    handle, run_id = _seed_workspace(tmp_path, "s5-fig-tx")
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        _seed_plot_script(root, 3)
        issue = {
            "级别": "硬伤", "目标": "图", "定位": "问题3 图4",
            "问题": "问题3 图内数字过期",
            "指令": "重绘问题3 的图并同步正文", "验收": "图与结果一致",
        }
        turns: list[MockTurn] = []
        turns += _raise_issue_leg("r1a", "审稿/审稿意见_轮1A.json", issue)
        turns += _empty_leg("r1b", "审稿/审稿意见_轮1B.json")
        turns += _empty_leg("h1", "审稿/硬伤_轮1.json")
        turns += _empty_leg("j1", "审稿/评委模拟_轮1.json")
        turns += _write_turn(
            "p1", "审稿/回执_R1_图问3.json",
            [{"id": "审-1-01", "改动": "同步图内数字", "证据": "diff"}],
        )
        turns += _write_turn(
            "s1", "审稿/回执_R1_图同步问3.json",
            [{"id": "审-1-01", "改动": "同步图题与引用", "证据": "论文/论文.tex"}],
        )
        turns += _verdict_leg(
            "r2a", "审稿/审稿意见_轮2A.json",
            [{"id": "审-1-01", "generation": 0, "裁定": "已消解", "理由": "图已重建"}],
        )
        turns += _empty_leg("r2b", "审稿/审稿意见_轮2B.json")
        turns += _empty_leg("h2", "审稿/硬伤_轮2.json")
        turns += _empty_leg("j2", "审稿/评委模拟_轮2.json")
        result = await run_s5(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            max_rounds=2, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        assert result["converged"] is True, result["ledger_summary"]
        assert (root / "求解" / "问题3" / "图片" / "图1.png").is_file()
        ok = events.query_events(db, run_id=run_id, type="s5.figure_repair_succeeded")
        assert len(ok) == 1
        rows = _ledger_rows(root)
        assert rows[0]["状态"] == "已消解"
        assert rows[0]["回执"]
        assert rows[0]["回执"][0]["receipt_id"] == "S5:R1:图同步问3:审-1-01:g0"
        assert "图=" in rows[0]["回执"][0]["改动"] and "文=" in rows[0]["回执"][0]["改动"]
    finally:
        handle.workspace.db.close()


# ==================== P1-B: G5 figure → dependent text ====================

def _seed_g5_workspace(tmp_path: Path, name: str):
    from mmagent.api.projects import create_project
    handle = create_project(tmp_path / name, name=name, profile="快速")
    root = handle.workspace.root
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
    run_id = repositories.create_run(
        handle.workspace.db, project_id=handle.project_id, profile="快速"
    )
    return handle, run_id


@pytest.mark.asyncio
async def test_g5_figure_receipt_alone_cannot_advance_issue(tmp_path: Path) -> None:
    """G5 figure rework without a runnable plot script fails the transaction;
    the issue stays active and the final publication gate fails closed."""
    import re as _re

    handle, run_id = _seed_g5_workspace(tmp_path, "g5-fig-alone")
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        _seed_ledger(root, [{
            "级别": "硬伤", "目标": "图", "定位": "问题3 图4",
            "问题": "图内数字与正文不一致",
        }])
        safe = _re.sub(r"[^0-9A-Za-z_-]+", "_", "审-1-01")
        turns: list[MockTurn] = []
        turns += _write_turn(
            "p", f"审稿/回执_G5R1_图问3_{safe}.json",
            [{"id": "审-1-01", "改动": "同步图内数字", "证据": "diff"}],
        )
        turns += _write_turn("h", "审稿/G5复核1.json",
                             {"通过": True, "依据版本": "当前PDF"})
        turns += _write_turn("f", "审稿/G5复核.json",
                             {"通过": True, "依据版本": "当前PDF"})
        result = await run_g5_rework(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            beauty_baseline_pages=10, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        failed = events.query_events(
            db, run_id=run_id, type="gate.g5_figure_transaction_failed"
        )
        assert len(failed) == 1
        assert failed[0].payload["step"] == "plot_runtime"
        assert not events.query_events(
            db, run_id=run_id, type="gate.g5_figure_transaction_succeeded"
        )
        rows = _ledger_rows(root)
        assert rows[0]["状态"] == "待改"
        assert rows[0]["回执"] == []
        assert result["pass"] is False
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_g5_failed_figure_transaction_cannot_fall_through_text_route(tmp_path: Path) -> None:
    """R4-P1: a failed G5 figure transaction must not fall through to the
    Writer-only text route — even with a would-succeed Writer response queued,
    the 图 issue stays active without a ledger receipt."""
    import re as _re

    handle, run_id = _seed_g5_workspace(tmp_path, "g5-fig-syncfail")
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        _seed_ledger(root, [{
            "级别": "硬伤", "目标": "图", "定位": "问题3 图4",
            "问题": "图内数字与正文不一致",
        }])
        _seed_plot_script(root, 3)
        safe = _re.sub(r"[^0-9A-Za-z_-]+", "_", "审-1-01")
        turns: list[MockTurn] = []
        turns += _write_turn(
            "p", f"审稿/回执_G5R1_图问3_{safe}.json",
            [{"id": "审-1-01", "改动": "同步图内数字", "证据": "diff"}],
        )
        # Figure-sync leg writes nothing (initial attempt + wave retry).
        turns += [MockTurn(text="不同步"), MockTurn(text="不同步")]
        # A Writer-only response that WOULD succeed is queued afterwards, but
        # the 图 issue must never reach the G5 text route (R4-P1: failed
        # figure transactions cannot fall through to Writer-only repair).
        turns += _write_turn(
            "w-would-succeed", "审稿/回执_G5R1_文.json",
            [{"id": "审-1-01", "改动": "writer-only 整改", "证据": "论文/论文.tex"}],
        )
        turns += _write_turn("h", "审稿/G5复核1.json",
                             {"通过": True, "依据版本": "当前PDF"})
        turns += _write_turn("f", "审稿/G5复核.json",
                             {"通过": True, "依据版本": "当前PDF"})
        result = await run_g5_rework(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            beauty_baseline_pages=10, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        failed = events.query_events(
            db, run_id=run_id, type="gate.g5_figure_transaction_failed"
        )
        assert len(failed) == 1
        assert failed[0].payload["step"] == "writer_sync"
        # Only the figure-sync leg was rolled back; the 图 issue never entered
        # the Writer-only text route (which would have produced a second
        # guarded-repair leg with node G5:R1:文).
        reverts = events.query_events(db, run_id=run_id, type="guard.structure_revert")
        assert len(reverts) == 1
        assert reverts[0].payload["leg_status"] != "SUCCEEDED"
        assert not any(
            r.payload["node"].startswith("G5:R1:文") for r in reverts
        )
        # The would-succeed Writer-only response was never consumed: the mock
        # script retained the recheck turns, proving no extra text leg ran.
        rows = _ledger_rows(root)
        assert rows[0]["状态"] == "待改"
        assert rows[0]["回执"] == []
        assert result["pass"] is False
    finally:
        handle.workspace.db.close()


# ==================== P1-C: change/structure guard enforcement ====================

_BROAD_OLD = "第一句独特内容甲。第二句独特内容乙。第三句独特内容丙。第四句独特内容丁。"
_BROAD_NEW = "完全重写的开头段落内容。与原文毫无继承关系。结论也换了一套说法。收尾另起炉灶。"


@pytest.mark.asyncio
async def test_change_guard_reverts_broad_late_writer_rewrite(tmp_path: Path) -> None:
    """A late S5 text repair that rewrites the whole paper (no named fragments)
    exceeds the 0.45 Change Guard and must be rolled back with its receipt
    invalidated."""
    handle, run_id = _seed_workspace(tmp_path, "s5-broad")
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        (root / "论文" / "论文.tex").write_text(_BROAD_OLD, encoding="utf-8")
        issue = {
            "级别": "硬伤", "目标": "文", "定位": "论文/论文.tex",
            "问题": "表述与结果不一致",
            "指令": "做最小修订", "验收": "改动最小",
        }
        turns: list[MockTurn] = []
        turns += _raise_issue_leg("r1a", "审稿/审稿意见_轮1A.json", issue)
        turns += _empty_leg("r1b", "审稿/审稿意见_轮1B.json")
        turns += _empty_leg("h1", "审稿/硬伤_轮1.json")
        turns += _empty_leg("j1", "审稿/评委模拟_轮1.json")
        # The writer "repairs" by wholesale replacement + writes a receipt.
        turns += _multi_write_turn("w1", [
            ("论文/论文.tex", _BROAD_NEW),
            ("审稿/回执_R1_文.json",
             [{"id": "审-1-01", "改动": "全文重写", "证据": "论文/论文.tex"}]),
        ])
        turns += _empty_leg("r2a", "审稿/审稿意见_轮2A.json")
        turns += _empty_leg("r2b", "审稿/审稿意见_轮2B.json")
        turns += _empty_leg("h2", "审稿/硬伤_轮2.json")
        turns += _empty_leg("j2", "审稿/评委模拟_轮2.json")
        result = await run_s5(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            max_rounds=2, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        # The paper was rolled back to the pre-repair snapshot.
        assert (root / "论文" / "论文.tex").read_text(encoding="utf-8") == _BROAD_OLD
        # The rejected receipt was deleted so a retry cannot reuse it.
        assert not (root / "审稿" / "回执_R1_文.json").is_file()
        reverts = events.query_events(db, run_id=run_id, type="guard.structure_revert")
        assert len(reverts) == 1
        assert any("Change Guard 超限" in x for x in reverts[0].payload["issues"])
        rows = _ledger_rows(root)
        assert rows[0]["状态"] == "待改"
        assert rows[0]["回执"] == []
        assert result["converged"] is False
    finally:
        handle.workspace.db.close()


_ESCALATED_KEEP4 = [
    "此段保持原样不动。", "该段依旧完整如初。", "这段文字维持原貌。", "本段内容继续留存。",
]
_ESCALATED_OLD = "".join([
    "首位待更句子内容。", "其次待更句子内容。", "第三待更句子内容。",
    "第四待更句子内容。", "第五待更句子内容。", "第六待更句子内容。",
] + _ESCALATED_KEEP4)
_ESCALATED_NEW = "".join([
    "ALPHA REWRITE UNIT ONE。", "BRAVO REWRITE UNIT TWO。", "CHARLIE REWRITE UNIT THREE。",
    "DELTA REWRITE UNIT FOUR。", "ECHO REWRITE UNIT FIVE。", "FOXTROT REWRITE UNIT SIX。",
] + _ESCALATED_KEEP4)


@pytest.mark.asyncio
async def test_escalated_change_guard_uses_070_limit(tmp_path: Path) -> None:
    """S5 text escalation runs the Change Guard at 0.70: a rewrite that the
    normal 0.45 limit would reject passes the escalated limit and the accepted
    escalation receipt reaches the ledger."""

    # Distinguishing ratio: the same texts must fail at 0.45 and pass at 0.70.
    ok_normal, ratio_normal, _ = change_guard(_ESCALATED_OLD, _ESCALATED_NEW, [], 上限=0.45)
    ok_esc, ratio_esc, _ = change_guard(_ESCALATED_OLD, _ESCALATED_NEW, [], 上限=0.70)
    assert not ok_normal
    assert ok_esc
    assert 0.45 < ratio_esc <= 0.70

    handle, run_id = _seed_workspace(tmp_path, "s5-esc70")
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        (root / "论文" / "论文.tex").write_text(_ESCALATED_OLD, encoding="utf-8")
        issue = {
            "级别": "硬伤", "目标": "文", "定位": "论文/论文.tex",
            "问题": "叙事组织需要换一种结构",
            "指令": "换一种技术路线重做叙事", "验收": "叙事完整",
        }
        turns: list[MockTurn] = []
        # R1: raise issue → receipt-only repair (尝试=1).
        turns += _raise_issue_leg("r1a", "审稿/审稿意见_轮1A.json", issue)
        turns += _empty_leg("r1b", "审稿/审稿意见_轮1B.json")
        turns += _empty_leg("h1", "审稿/硬伤_轮1.json")
        turns += _empty_leg("j1", "审稿/评委模拟_轮1.json")
        turns += _write_turn(
            "w1", "审稿/回执_R1_文.json",
            [{"id": "审-1-01", "改动": "小幅修订", "证据": "论文/论文.tex"}],
        )
        # R2: 未消解 → receipt-only repair (尝试=2).
        turns += _verdict_leg(
            "r2a", "审稿/审稿意见_轮2A.json",
            [{"id": "审-1-01", "generation": 0, "裁定": "未消解", "理由": "未修复"}],
        )
        turns += _empty_leg("r2b", "审稿/审稿意见_轮2B.json")
        turns += _empty_leg("h2", "审稿/硬伤_轮2.json")
        turns += _empty_leg("j2", "审稿/评委模拟_轮2.json")
        turns += _write_turn(
            "w2", "审稿/回执_R2_文.json",
            [{"id": "审-1-01", "改动": "再次小幅修订", "证据": "论文/论文.tex"}],
        )
        # R3: 未消解 → fuse escalates → escalated rewrite within 0.70.
        turns += _verdict_leg(
            "r3a", "审稿/审稿意见_轮3A.json",
            [{"id": "审-1-01", "generation": 0, "裁定": "未消解", "理由": "仍未修复"}],
        )
        turns += _empty_leg("r3b", "审稿/审稿意见_轮3B.json")
        turns += _empty_leg("h3", "审稿/硬伤_轮3.json")
        turns += _empty_leg("j3", "审稿/评委模拟_轮3.json")
        turns += _multi_write_turn("esc", [
            ("论文/论文.tex", _ESCALATED_NEW),
            ("审稿/回执_升格_审-1-01_g0.json",
             [{"id": "审-1-01", "改动": "换结构重做叙事", "证据": "论文/论文.tex"}]),
        ])
        # Extension round: the reviewer resolves the escalated issue.
        turns += _verdict_leg(
            "r4a", "审稿/审稿意见_轮4A.json",
            [{"id": "审-1-01", "generation": 0, "裁定": "已消解", "理由": "升格成功"}],
        )
        turns += _empty_leg("r4b", "审稿/审稿意见_轮4B.json")
        turns += _empty_leg("h4", "审稿/硬伤_轮4.json")
        turns += _empty_leg("j4", "审稿/评委模拟_轮4.json")
        result = await run_s5(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            max_rounds=3, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        assert result["converged"] is True, result["ledger_summary"]
        # No guard revert fired for the escalated rewrite.
        assert not events.query_events(db, run_id=run_id, type="guard.structure_revert")
        assert events.query_events(db, run_id=run_id, type="s5.escalation_succeeded")
        rows = _ledger_rows(root)
        assert rows[0]["状态"] == "已消解"
        assert (root / "论文" / "论文.tex").read_text(encoding="utf-8") == _ESCALATED_NEW
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_guard_snapshot_survives_resume_after_role_success(
    tmp_path: Path, monkeypatch,
) -> None:
    """A crash after the role leg sealed success but before the guard ran must
    not erase the pre-repair baseline: the durable snapshot drives the resumed
    guard, which rolls the orphaned mutation back."""
    from mmagent.mm.pipeline import guarded_repair

    handle, run_id = _seed_workspace(tmp_path, "guard-snapshot")
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        policy = PathPolicy(root)
        (root / "论文" / "论文.tex").write_text(
            "原始内容完整无损。第二段落继续陈述。第三段落进一步展开。",
            encoding="utf-8",
        )

        def boom(*args, **kwargs):
            raise RuntimeError("simulated crash after role success")

        monkeypatch.setattr(guarded_repair, "structure_guard", boom)
        script = MockScript(
            _multi_write_turn("w", [
                ("论文/论文.tex", "XYZQJK 全然不同的篇章结构。"),
                ("审稿/回执_快照.json", [{"id": "审-1-01", "改动": "改写", "证据": "x"}]),
            ])
        )
        with pytest.raises(RuntimeError):
            await guarded_repair.guarded_text_repair(
                db, MockProvider(script), _registry(), policy, run_id,
                stage_key="S5", node_key="S5:R1:回炉文",
                instructions="修复", receipt_rel="审稿/回执_快照.json",
            )
        # The durable snapshot survived the crash and holds the ORIGINAL tex.
        snapshot_files = list((root / ".mmagent" / "guard_snapshots").glob("*.json"))
        assert len(snapshot_files) == 1
        raw = json.loads(snapshot_files[0].read_text(encoding="utf-8"))
        assert raw["files"]["论文/论文.tex"] == (
            "原始内容完整无损。第二段落继续陈述。第三段落进一步展开。"
        )
        monkeypatch.undo()

        # Resume: the same node reuses the durable baseline (not the mutated
        # on-disk state), so the orphaned mutation is rolled back.
        script2 = MockScript(
            _write_turn(
                "w2", "审稿/回执_快照.json",
                [{"id": "审-1-01", "改动": "再次尝试", "证据": "x"}],
            )
        )
        status, issues = await guarded_repair.guarded_text_repair(
            db, MockProvider(script2), _registry(), policy, run_id,
            stage_key="S5", node_key="S5:R1:回炉文",
            instructions="修复", receipt_rel="审稿/回执_快照.json",
        )
        assert status == "REVERTED"
        assert any("Change Guard 超限" in x for x in issues)
        assert (root / "论文" / "论文.tex").read_text(encoding="utf-8") == (
            "原始内容完整无损。第二段落继续陈述。第三段落进一步展开。"
        )
        assert not (root / "审稿" / "回执_快照.json").is_file()
        # The snapshot is consumed after the completed guard cycle.
        assert not list((root / ".mmagent" / "guard_snapshots").glob("*.json"))
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_reverted_guarded_repair_deletes_stale_receipt(tmp_path: Path) -> None:
    """When a guarded repair is reverted (broad rewrite), the attempt's receipt
    artifact is deleted with it — a retry can never satisfy artifact
    verification by reusing the rejected attempt's stale evidence."""
    from mmagent.mm.pipeline.guarded_repair import guarded_text_repair

    handle, run_id = _seed_workspace(tmp_path, "stale-receipt")
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        policy = PathPolicy(root)
        original = "原始内容完整无损。第二段落继续陈述。"
        mutated = "XYZQJK 全然不同的篇章结构与结论表述。"
        (root / "论文" / "论文.tex").write_text(original, encoding="utf-8")
        receipt_rel = "审稿/回执_清理.json"
        (root / "审稿").mkdir(parents=True, exist_ok=True)
        (root / receipt_rel).write_text(
            json.dumps([{"id": "审-1-01", "改动": "旧回执", "证据": "x"}], ensure_ascii=False),
            encoding="utf-8",
        )
        # The leg mutates the paper; the guard must revert both the mutation
        # and the receipt (pre-existing or freshly written).
        script = MockScript(
            _write_turn("w", "论文/论文.tex", mutated)
        )
        status, issues = await guarded_text_repair(
            db, MockProvider(script), _registry(), policy, run_id,
            stage_key="S5", node_key="S5:R1:回炉文",
            instructions="修复", receipt_rel=receipt_rel,
        )
        assert status == "REVERTED"
        assert any("Change Guard 超限" in x for x in issues)
        assert (root / "论文" / "论文.tex").read_text(encoding="utf-8") == original
        assert not (root / receipt_rel).is_file()
        reverts = events.query_events(db, run_id=run_id, type="guard.structure_revert")
        assert len(reverts) == 1
    finally:
        handle.workspace.db.close()
