from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.mm.pipeline.s2_model import run_s2
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


def _write_turn(call_id: str, writes: list[tuple[str, str]]) -> list[MockTurn]:
    calls = [
        (f"{call_id}-{i}", "fs.write", {"path": p, "content": c})
        for i, (p, c) in enumerate(writes)
    ]
    return [MockTurn(tool_calls=calls), MockTurn(text="完成")]


def _aligned_script() -> MockScript:
    solver = (
        "from pathlib import Path\nimport json\n"
        "p=Path('求解/问题1/结果'); p.mkdir(parents=True, exist_ok=True)\n"
        "(p/'结果.json').write_text(json.dumps({'厚度':2.17}), encoding='utf-8')\n"
    )
    red = (
        "from pathlib import Path\nimport json\n"
        "p=Path('求解/问题1/红队结果'); p.mkdir(parents=True, exist_ok=True)\n"
        "(p/'复算.json').write_text(json.dumps({'厚度':2.17}), encoding='utf-8')\n"
    )
    turns: list[MockTurn] = []
    turns += _write_turn("m", [("求解/问题1/求解_问题1.py", solver)])
    turns += _write_turn("i", [
        (
            "交接/结果声明_问题1.json",
            json.dumps({"问题编号": 1, "核心指标": {"厚度": 2.17}}, ensure_ascii=False),
        ),
        ("交接/结果解读_问题1.md", "厚度为2.17。"),
    ])
    turns += _write_turn("rscript", [("求解/问题1/复算.py", red)])
    turns += _write_turn("rreport", [
        (
            "交接/红队_问题1.json",
            json.dumps({"问题编号": 1, "结论": "对齐", "分歧明细": []}, ensure_ascii=False),
        )
    ])
    return MockScript(turns)


@pytest.mark.asyncio
async def test_s2_driver_executes_solver_and_red_scripts_then_g2_passes(tmp_path: Path) -> None:
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj", name="s2", profile="快速")
    try:
        root = handle.workspace.root
        plan = {"问题清单": [{"编号": 1, "依赖问题": [], "主方法": "测试法"}]}
        plan_path = root / "交接" / "计划.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        result = await run_s2(
            handle.workspace.db,
            MockProvider(_aligned_script()),
            _registry(),
            PathPolicy(root),
            run_id,
            plan_path,
        )
        assert result["gates"]["问1"]["pass"] is True, result
        assert (root / "求解" / "问题1" / "结果" / "结果.json").is_file()
        assert (root / "求解" / "问题1" / "红队结果" / "复算.json").is_file()
        assert result["downgraded"] == []
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s2_pinned_layer_execution_is_sequential_with_layer_barrier(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Pinned 5f507e0b mechanically runs each question pipeline sequentially."""
    import asyncio

    import mmagent.mm.pipeline.s2_model as s2
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj-layer", name="s2-layer", profile="快速")
    try:
        plan = {
            "问题清单": [
                {"编号": 1, "依赖问题": [], "主方法": "A"},
                {"编号": 3, "依赖问题": [], "主方法": "C"},
                {"编号": 2, "依赖问题": [1, 3], "主方法": "B"},
            ]
        }
        plan_path = handle.workspace.root / "交接" / "计划.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        run_id = repositories.create_run(
            handle.workspace.db,
            project_id=handle.project_id,
            profile="快速",
        )

        order: list[tuple[str, int]] = []
        active = 0
        peak = 0

        async def fake_attempt(*args, **kwargs):
            nonlocal active, peak
            q = int(args[5])
            active += 1
            peak = max(peak, active)
            order.append(("start", q))
            await asyncio.sleep(0.01)
            order.append(("end", q))
            active -= 1
            return True, []

        monkeypatch.setattr(s2, "_normal_attempt", fake_attempt)

        result = await run_s2(
            handle.workspace.db,
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            PathPolicy(handle.workspace.root),
            run_id,
            plan_path,
        )

        assert result["layers"] == [[1, 3], [2]]
        assert order == [
            ("start", 1),
            ("end", 1),
            ("start", 3),
            ("end", 3),
            ("start", 2),
            ("end", 2),
        ]
        assert peak == 1
        assert result["downgraded"] == []
        checkpoints = events.query_events(
            handle.workspace.db,
            run_id=run_id,
            type="checkpoint.s2_question",
        )
        assert [e.payload["question"] for e in checkpoints] == [1, 3, 2]
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s2_question_checkpoint_skips_completed_driver_work(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import mmagent.mm.pipeline.s2_model as s2
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj-resume", name="s2-resume", profile="快速")
    try:
        root = handle.workspace.root
        plan = {"问题清单": [{"编号": 1, "依赖问题": [], "主方法": "测试法"}]}
        plan_path = root / "交接" / "计划.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        run_id = repositories.create_run(
            handle.workspace.db,
            project_id=handle.project_id,
            profile="快速",
        )
        policy = PathPolicy(root)

        first = await run_s2(
            handle.workspace.db,
            MockProvider(_aligned_script()),
            _registry(),
            policy,
            run_id,
            plan_path,
        )
        assert first["gates"]["问1"]["pass"] is True

        async def must_not_run(*args, **kwargs):
            raise AssertionError("completed S2 question driver work must be skipped")

        monkeypatch.setattr(s2, "_normal_attempt", must_not_run)
        monkeypatch.setattr(s2, "_run_script", must_not_run)

        second = await run_s2(
            handle.workspace.db,
            MockProvider(MockScript([])),
            _registry(),
            policy,
            run_id,
            plan_path,
        )

        assert second["gates"]["问1"]["pass"] is True
        assert second["downgraded"] == []
        reused = events.query_events(
            handle.workspace.db,
            run_id=run_id,
            type="pipeline.s2_question_reused",
        )
        assert len(reused) == 1
        checkpoints = events.query_events(
            handle.workspace.db,
            run_id=run_id,
            type="checkpoint.s2_question",
        )
        assert len(checkpoints) == 1
    finally:
        handle.workspace.db.close()



@pytest.mark.asyncio
async def test_s2_downgraded_checkpoint_without_carrier_is_rerun(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import mmagent.mm.pipeline.s2_model as s2
    from mmagent.api.projects import create_project

    handle = create_project(
        tmp_path / "proj-degraded-resume",
        name="s2-degraded-resume",
        profile="快速",
    )
    try:
        root = handle.workspace.root
        plan = {"问题清单": [{"编号": 1, "依赖问题": [], "主方法": "测试法"}]}
        plan_path = root / "交接" / "计划.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        run_id = repositories.create_run(
            handle.workspace.db,
            project_id=handle.project_id,
            profile="快速",
        )
        events.append_event(
            handle.workspace.db,
            "checkpoint.s2_question",
            {
                "question": 1,
                "pass": False,
                "issues": ["old failure"],
                "downgraded": True,
            },
            run_id=run_id,
        )

        calls = 0

        async def repaired_attempt(*args, **kwargs):
            nonlocal calls
            calls += 1
            return True, []

        monkeypatch.setattr(s2, "_normal_attempt", repaired_attempt)

        result = await run_s2(
            handle.workspace.db,
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            PathPolicy(root),
            run_id,
            plan_path,
        )

        assert calls == 1
        assert result["gates"]["问1"]["pass"] is True
        assert result["downgraded"] == []
        invalidated = events.query_events(
            handle.workspace.db,
            run_id=run_id,
            type="pipeline.s2_question_invalidated",
        )
        assert len(invalidated) == 1
        assert "降级放行" in invalidated[0].payload["issues"][0]
    finally:
        handle.workspace.db.close()


# ==================== B14: durable downstream cascade invalidation ====================

def _seed_g2_artifacts(root: Path, questions: list[int]) -> None:
    for q in questions:
        decl = root / "交接" / f"结果声明_问题{q}.json"
        decl.parent.mkdir(parents=True, exist_ok=True)
        decl.write_text(
            json.dumps({"问题编号": q, "核心指标": {"厚度": 2.17}}, ensure_ascii=False),
            encoding="utf-8",
        )
        rt = root / "交接" / f"红队_问题{q}.json"
        rt.write_text(
            json.dumps(
                {"问题编号": q, "结论": "对齐", "机械复核": {"通过": True}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        solver = root / "求解" / f"问题{q}" / f"求解_问题{q}.py"
        solver.parent.mkdir(parents=True, exist_ok=True)
        solver.write_text("print(1)", encoding="utf-8")


@pytest.mark.asyncio
async def test_s2_reexecuted_upstream_cascade_invalidates_downstream_checkpoints(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """B14: 问题1 重算 → 下游 2/3/4 的 checkpoint 必须级联失效并重算，
    即使它们自身的 G2 仍然通过。"""
    import mmagent.mm.pipeline.s2_model as s2
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj-cascade", name="s2-cascade", profile="快速")
    try:
        root = handle.workspace.root
        plan = {
            "问题清单": [
                {"编号": 1, "依赖问题": [], "主方法": "A"},
                {"编号": 2, "依赖问题": [1], "主方法": "B"},
                {"编号": 3, "依赖问题": [2], "主方法": "C"},
                {"编号": 4, "依赖问题": [1], "主方法": "D"},
            ]
        }
        plan_path = root / "交接" / "计划.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        policy = PathPolicy(root)
        _seed_g2_artifacts(root, [1, 2, 3, 4])

        executed: list[int] = []

        async def fake_attempt(db, provider, registry, policy_, run_id_, q, **kwargs):
            executed.append(q)
            return True, []

        monkeypatch.setattr(s2, "_normal_attempt", fake_attempt)

        first = await run_s2(
            handle.workspace.db, None, None,  # type: ignore[arg-type]
            policy, run_id, plan_path,
        )
        assert executed == [1, 2, 4, 3]
        assert first["gates"]["问1"]["pass"] is True

        # Corrupt ONLY question 1's own artifacts; downstream artifacts stay
        # G2-valid.  Without the cascade, only q1 would re-execute.
        (root / "交接" / "结果声明_问题1.json").write_text(
            json.dumps({"问题编号": 1, "核心指标": {}}, ensure_ascii=False),
            encoding="utf-8",
        )
        executed.clear()
        second = await run_s2(
            handle.workspace.db, None, None,  # type: ignore[arg-type]
            policy, run_id, plan_path,
        )
        assert executed == [1, 2, 4, 3], second
        cascades = events.query_events(
            handle.workspace.db, run_id=run_id,
            type="pipeline.s2_downstream_invalidated",
        )
        assert len(cascades) == 1
        assert cascades[0].payload["question"] == 1
        assert sorted(cascades[0].payload["downstream"]) == [2, 3, 4]

        # Repair q1 and rerun: nothing is invalidated any more.
        _seed_g2_artifacts(root, [1])
        executed.clear()
        await run_s2(
            handle.workspace.db, None, None,  # type: ignore[arg-type]
            policy, run_id, plan_path,
        )
        assert executed == []
        reused = events.query_events(
            handle.workspace.db, run_id=run_id,
            type="pipeline.s2_question_reused",
        )
        assert len(reused) >= 4
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s2_resume_replays_downstream_invalidation_tombstone(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """B14 crash boundary: an invalidation event must suppress an older
    downstream checkpoint after restart, even when that downstream G2 still
    validates mechanically."""
    import mmagent.mm.pipeline.s2_model as s2
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj-cascade-resume", name="s2-cascade-resume", profile="快速")
    try:
        root = handle.workspace.root
        plan = {
            "问题清单": [
                {"编号": 1, "依赖问题": [], "主方法": "A"},
                {"编号": 2, "依赖问题": [1], "主方法": "B"},
            ]
        }
        plan_path = root / "交接" / "计划.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        _seed_g2_artifacts(root, [1, 2])

        for q in (1, 2):
            events.append_event(
                handle.workspace.db,
                "checkpoint.s2_question",
                {"question": q, "pass": True, "issues": [], "downgraded": False},
                run_id=run_id,
            )
        # Simulate a crash after q1 invalidated q2 in durable event truth but
        # before q2's replacement checkpoint was written.
        events.append_event(
            handle.workspace.db,
            "pipeline.s2_downstream_invalidated",
            {"question": 1, "downstream": [2]},
            run_id=run_id,
        )

        executed: list[int] = []

        async def fake_attempt(db, provider, registry, policy_, run_id_, q, **kwargs):
            executed.append(q)
            return True, []

        monkeypatch.setattr(s2, "_normal_attempt", fake_attempt)

        result = await run_s2(
            handle.workspace.db,
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            PathPolicy(root),
            run_id,
            plan_path,
        )

        assert result["gates"]["问1"]["pass"] is True
        assert executed == [2]
    finally:
        handle.workspace.db.close()
