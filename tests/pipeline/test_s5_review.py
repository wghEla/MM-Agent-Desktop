from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.mm.pipeline.s5_review import _retention_decision, run_s5
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.state import events, repositories
from mmagent.tools.filesystem import FsReadTool, FsWriteTool
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.path_policy import PathPolicy


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(FsReadTool())
    reg.register(FsWriteTool())
    return reg


def _write_turn(call_id: str, path: str, payload: object) -> list[MockTurn]:
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return [
        MockTurn(tool_calls=[(call_id, "fs.write", {"path": path, "content": content})]),
        MockTurn(text="完成"),
    ]


def _review_script() -> MockScript:
    turns: list[MockTurn] = []
    turns += _write_turn("r1a", "审稿/审稿意见_轮1A.json", {
        "意见": [{
            "级别": "正确性",
            "目标": "文",
            "定位": "论文/论文.tex 问题1",
            "问题": "问题1 的结论缺少验证说明",
            "指令": "在点名段补充验证说明，不改其他段落",
            "验收": "结论后出现验证证据",
        }],
        "裁定": [],
    })
    turns += _write_turn("r1b", "审稿/审稿意见_轮1B.json", {"意见": [], "裁定": []})
    turns += _write_turn("h1", "审稿/硬伤_轮1.json", {"意见": [], "裁定": []})
    turns += _write_turn("j1", "审稿/评委模拟_轮1.json", {"意见": [], "裁定": []})
    turns += _write_turn("w1", "审稿/回执_R1_文.json", [{
        "id": "审-1-01",
        "generation": 0,
        "改动": "补充验证说明",
        "证据": "论文/论文.tex 对应段落",
    }])
    turns += _write_turn("r2a", "审稿/审稿意见_轮2A.json", {
        "意见": [],
        "裁定": [{"id": "审-1-01", "generation": 0, "裁定": "已消解"}],
    })
    turns += _write_turn("r2b", "审稿/审稿意见_轮2B.json", {"意见": [], "裁定": []})
    turns += _write_turn("h2", "审稿/硬伤_轮2.json", {"意见": [], "裁定": []})
    turns += _write_turn("j2", "审稿/评委模拟_轮2.json", {"意见": [], "裁定": []})
    return MockScript(turns)


def _fake_compile(root: Path) -> dict:
    (root / "论文" / "论文.log").write_text(
        "Output written on 论文.pdf (10 pages).", encoding="utf-8"
    )
    (root / "论文" / "论文.pdf").write_bytes(b"%PDF-s5-test")
    return {"rc": 0, "errors": [], "pages": 10}


def _fake_render(root: Path) -> list[Path]:
    page_dir = root / "论文" / "页"
    page_dir.mkdir(parents=True, exist_ok=True)
    page = page_dir / "page-001.png"
    page.write_bytes(b"PNG")
    return [page]


@pytest.mark.asyncio
async def test_s5_review_receipt_verdict_converges_without_broad_permissions(tmp_path: Path) -> None:
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj", name="s5", profile="标准")
    try:
        root = handle.workspace.root
        (root / "论文").mkdir(parents=True, exist_ok=True)
        (root / "论文" / "论文.tex").write_text("正文内容。", encoding="utf-8")
        (root / "论文" / "0.摘要.tex").write_text("摘要内容。", encoding="utf-8")
        (root / "交接" / "需求追踪矩阵.json").write_text(
            json.dumps([{"需求号": "一", "状态": "已销号"}], ensure_ascii=False),
            encoding="utf-8",
        )
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="标准"
        )
        result = await run_s5(
            handle.workspace.db,
            MockProvider(_review_script()),
            _registry(),
            PathPolicy(root),
            run_id,
            max_rounds=2,
            compile_paper=_fake_compile,
            render_pages=_fake_render,
        )
        assert result["converged"] is True
        assert result["ledger_summary"].get("正确性/已消解") == 1
        assert result["rounds"][0]["converged"] is False
        assert result["rounds"][0]["rework"]["文"] == 1
        assert result["rounds"][1]["converged"] is True
        assert (root / "台账" / "审稿台账.json").is_file()
        checkpoints = events.query_events(
            handle.workspace.db, run_id=run_id, type="checkpoint.s5_round_complete"
        )
        assert [e.payload["round"] for e in checkpoints] == [1, 2]
    finally:
        handle.workspace.db.close()



@pytest.mark.parametrize(
    ("relative", "old_score", "new_score", "expected"),
    [
        ("更差", 8.0, 9.0, "回退"),
        ("更好", 8.0, 7.0, "接受"),
        ("持平", 8.0, 7.49, "回退"),
        ("持平", 8.0, 7.50, "接受"),
        (None, 8.0, 7.60, "接受"),
    ],
)
def test_s5_best_retention_decision(
    relative: str | None,
    old_score: float | None,
    new_score: float | None,
    expected: str,
) -> None:
    action, _ = _retention_decision(relative, old_score, new_score)
    assert action == expected


def _rollback_script() -> MockScript:
    turns: list[MockTurn] = []
    turns += _write_turn("r1a", "审稿/审稿意见_轮1A.json", {
        "总分": 8.0,
        "意见": [{
            "级别": "正确性",
            "目标": "文",
            "定位": "论文/论文.tex 问题1",
            "问题": "问题1 需要补验证",
            "指令": "只补验证",
            "验收": "验证可复核",
        }],
        "裁定": [],
    })
    turns += _write_turn(
        "r1b",
        "审稿/审稿意见_轮1B.json",
        {"总分": 8.0, "意见": [], "裁定": []},
    )
    turns += _write_turn("h1", "审稿/硬伤_轮1.json", {"意见": [], "裁定": []})
    turns += _write_turn("j1", "审稿/评委模拟_轮1.json", {"意见": [], "裁定": []})
    turns += [
        MockTurn(tool_calls=[
            ("w-paper", "fs.write", {"path": "论文/论文.tex", "content": "WORSE"}),
            (
                "w-receipt",
                "fs.write",
                {
                    "path": "审稿/回执_R1_文.json",
                    "content": json.dumps([{
                        "id": "审-1-01",
                        "generation": 0,
                        "改动": "补验证但整体变差",
                        "证据": "论文/论文.tex",
                    }], ensure_ascii=False),
                },
            ),
        ]),
        MockTurn(text="回炉完成"),
    ]
    turns += _write_turn("r2a", "审稿/审稿意见_轮2A.json", {
        "总分": 7.0,
        "相对判断": "更差",
        "意见": [],
        "裁定": [{
            "id": "审-1-01",
            "generation": 0,
            "裁定": "已消解",
            "理由": "局部问题看似已修",
        }],
    })
    turns += _write_turn("r2b", "审稿/审稿意见_轮2B.json", {
        "总分": 7.0,
        "相对判断": "更差",
        "意见": [],
        "裁定": [],
    })
    turns += _write_turn(
        "h2",
        "审稿/硬伤_轮2.json",
        {"相对判断": "持平", "意见": [], "裁定": []},
    )
    turns += _write_turn(
        "j2",
        "审稿/评委模拟_轮2.json",
        {"相对判断": "持平", "意见": [], "裁定": []},
    )
    return MockScript(turns)


@pytest.mark.asyncio
async def test_s5_rolls_back_worse_round_and_reopens_resolved_issue(
    tmp_path: Path,
) -> None:
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj-rollback", name="s5-rollback", profile="标准")
    try:
        root = handle.workspace.root
        (root / "论文").mkdir(parents=True, exist_ok=True)
        (root / "论文" / "论文.tex").write_text("BASE", encoding="utf-8")
        (root / "论文" / "0.摘要.tex").write_text("摘要内容。", encoding="utf-8")
        (root / "交接" / "需求追踪矩阵.json").write_text(
            json.dumps([{"需求号": "一", "状态": "已销号"}], ensure_ascii=False),
            encoding="utf-8",
        )
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="标准"
        )

        result = await run_s5(
            handle.workspace.db,
            MockProvider(_rollback_script()),
            _registry(),
            PathPolicy(root),
            run_id,
            max_rounds=2,
            compile_paper=_fake_compile,
            render_pages=_fake_render,
        )

        assert result["converged"] is False
        assert (root / "论文" / "论文.tex").read_text(encoding="utf-8") == "BASE"
        assert result["ledger_summary"].get("正确性/未消解") == 1
        assert result["rounds"][1]["retention_action"] == "回退"
        assert result["rounds"][1]["restored_files"] >= 1
        assert result["rounds"][1]["rolled_back_issues"] == 1

        rollback_events = events.query_events(
            handle.workspace.db, run_id=run_id, type="s5.rollback"
        )
        assert len(rollback_events) == 1
        assert rollback_events[0].payload["to_round"] == 1
    finally:
        handle.workspace.db.close()


# ==================== S5 fuse escalation — real run_s5() path (round2 P1-3/P1-6) ====================

def _empty_leg(turn_id: str, path: str) -> list[MockTurn]:
    return _write_turn(turn_id, path, {"意见": [], "裁定": []})


def _unresolved_verdict(turn_id: str, path: str) -> list[MockTurn]:
    return _write_turn(turn_id, path, {
        "总分": 8.0,
        "相对判断": "持平",
        "意见": [],
        "裁定": [{
            "id": "审-1-01", "generation": 0,
            "裁定": "未消解", "理由": "问题仍然存在",
        }],
    })


def _escalation_script(*, max_rounds: int, escalation_receipt: bool) -> MockScript:
    """Drive a 硬伤/文 issue through repeated 未消解 verdicts.

    Timeline: R1 raises the issue + first receipt (尝试=1); R2 verdict
    未消解 + second receipt (尝试=2); R3 verdict 未消解 → fuse escalates →
    the escalation leg either delivers the required receipt or fails;
    R4 (max_rounds>=4) verdict 未消解 → escalation exhausted → degraded.
    """
    turns: list[MockTurn] = []
    turns += _write_turn("r1a", "审稿/审稿意见_轮1A.json", {
        "总分": 8.0,
        "意见": [{
            "级别": "硬伤", "目标": "文", "定位": "论文/论文.tex 问题1",
            "问题": "结论与求解结果矛盾",
            "指令": "修正结论", "验收": "结论与结果一致",
        }],
        "裁定": [],
    })
    turns += _write_turn("r1b", "审稿/审稿意见_轮1B.json", {"总分": 8.0, "意见": [], "裁定": []})
    turns += _empty_leg("h1", "审稿/硬伤_轮1.json")
    turns += _empty_leg("j1", "审稿/评委模拟_轮1.json")
    turns += _write_turn("w1", "审稿/回执_R1_文.json",
                         [{"id": "审-1-01", "改动": "修正结论", "证据": "论文/论文.tex"}])
    # R2: verdict 未消解 → rework receipt (尝试=2)
    turns += _unresolved_verdict("r2a", "审稿/审稿意见_轮2A.json")
    turns += _write_turn("r2b", "审稿/审稿意见_轮2B.json",
                         {"总分": 8.0, "相对判断": "持平", "意见": [], "裁定": []})
    turns += _empty_leg("h2", "审稿/硬伤_轮2.json")
    turns += _empty_leg("j2", "审稿/评委模拟_轮2.json")
    turns += _write_turn("w2", "审稿/回执_R2_文.json",
                         [{"id": "审-1-01", "改动": "再次修正", "证据": "论文/论文.tex"}])
    # R3: verdict 未消解 → fuse escalates → escalation leg
    turns += _unresolved_verdict("r3a", "审稿/审稿意见_轮3A.json")
    turns += _write_turn("r3b", "审稿/审稿意见_轮3B.json",
                         {"总分": 8.0, "相对判断": "持平", "意见": [], "裁定": []})
    turns += _empty_leg("h3", "审稿/硬伤_轮3.json")
    turns += _empty_leg("j3", "审稿/评委模拟_轮3.json")
    if escalation_receipt:
        # Successful escalation: required receipt → 收回执 → 待复核, so the
        # round's rework lane has no 待改 item left (no w3 leg).
        turns += _write_turn("esc3", "审稿/回执_升格_审-1-01_g0.json",
                             [{"id": "审-1-01", "改动": "换技术路线重做", "证据": "论文/论文.tex"}])
    else:
        # Escalation leg writes nothing → artifact gate fails it
        # (initial attempt + the wave's single retry, both text-only).
        turns += [MockTurn(text="跳过"), MockTurn(text="跳过")]
        # The issue stays 未消解 → the rework lane still runs for it.
        turns += _write_turn("w3", "审稿/回执_R3_文.json",
                             [{"id": "审-1-01", "改动": "再次修正", "证据": "论文/论文.tex"}])
    # R4: verdict 未消解 again → exhausted → Runtime degraded registration
    if max_rounds >= 4:
        turns += _unresolved_verdict("r4a", "审稿/审稿意见_轮4A.json")
        turns += _write_turn("r4b", "审稿/审稿意见_轮4B.json",
                             {"总分": 8.0, "相对判断": "持平", "意见": [], "裁定": []})
        turns += _empty_leg("h4", "审稿/硬伤_轮4.json")
        turns += _empty_leg("j4", "审稿/评委模拟_轮4.json")
    return MockScript(turns)


def _seed_s5_workspace(tmp_path: Path, name: str):
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
    run_id = repositories.create_run(
        handle.workspace.db, project_id=handle.project_id, profile="标准"
    )
    return handle, run_id


@pytest.mark.asyncio
async def test_s5_escalation_runs_real_leg_then_degrades_after_exhaustion(
    tmp_path: Path,
) -> None:
    """Round3 fuse escalates via a real writer leg with a REQUIRED receipt;
    round4 the still-unresolved candidate is degraded-registered by the
    Runtime (never by the model) and shelved with an exact record."""
    from mmagent.mm.contracts.degraded_release import read_degraded_release

    handle, run_id = _seed_s5_workspace(tmp_path, "s5-esc")
    try:
        db = handle.workspace.db
        result = await run_s5(
            db, MockProvider(_escalation_script(max_rounds=4, escalation_receipt=True)),
            _registry(), PathPolicy(handle.workspace.root), run_id,
            max_rounds=4, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        root = handle.workspace.root
        # Real escalation leg executed exactly once for this generation.
        started = events.query_events(db, run_id=run_id, type="s5.escalation_started")
        succeeded = events.query_events(db, run_id=run_id, type="s5.escalation_succeeded")
        assert [e.payload["issue_id"] for e in started] == ["审-1-01"]
        assert len(succeeded) == 1
        assert (root / "审稿" / "回执_升格_审-1-01_g0.json").is_file()
        # Escalation exhaustion → Runtime-owned degraded registration.
        degraded = events.query_events(
            db, run_id=run_id, type="s5.degraded_release_registered"
        )
        assert len(degraded) == 1
        carrier = read_degraded_release(root)
        assert carrier is not None
        assert any(
            e.id == "审-1-01" and e.generation == 0 and e.source_stage == "S5"
            for e in carrier.review_issues
        )
        # Shelved blocking rows must persist to the carrier on disk.
        rows = json.loads(
            (root / "台账" / "审稿台账.json").read_text(encoding="utf-8")
        )
        assert rows[0]["状态"] == "搁置"
        assert result["ledger_summary"].get("硬伤/搁置") == 1
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s5_escalation_leg_without_receipt_fails_and_degrades_later(
    tmp_path: Path,
) -> None:
    """A failed escalation leg must be recorded as failed (never 'executed'),
    must not resolve the issue, and must not register a degraded release
    before exhaustion is actually observed."""
    from mmagent.mm.contracts.degraded_release import read_degraded_release

    handle, run_id = _seed_s5_workspace(tmp_path, "s5-esc-fail")
    try:
        db = handle.workspace.db
        root = handle.workspace.root
        result = await run_s5(
            db, MockProvider(_escalation_script(max_rounds=3, escalation_receipt=False)),
            _registry(), PathPolicy(root), run_id,
            max_rounds=3, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        failed = events.query_events(db, run_id=run_id, type="s5.escalation_failed")
        assert len(failed) == 1
        assert failed[0].payload["status"] != "SUCCEEDED"
        assert not events.query_events(
            db, run_id=run_id, type="s5.escalation_succeeded"
        )
        # The required escalation receipt was never written.
        assert not (root / "审稿" / "回执_升格_审-1-01_g0.json").is_file()
        # Exhaustion was not observed in a later fuse pass → no degraded record.
        carrier = read_degraded_release(root)
        assert carrier is None or not carrier.review_issues
        # The issue was not silently resolved; the post-failure rework receipt
        # moved it to 待复核 (still an active blocking state).
        assert result["converged"] is False
        rows = json.loads(
            (root / "台账" / "审稿台账.json").read_text(encoding="utf-8")
        )
        assert rows[0]["状态"] == "待复核"
    finally:
        handle.workspace.db.close()
