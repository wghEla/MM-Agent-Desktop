from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.mm.pipeline.s6_finalize import run_s6
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
    page = page_dir / "page-001.png"
    page.write_bytes(b"PNG")
    return [page]


def _seed_terminal_gate(root: Path) -> None:
    (root / "论文").mkdir(parents=True, exist_ok=True)
    (root / "交接").mkdir(parents=True, exist_ok=True)
    (root / "台账").mkdir(parents=True, exist_ok=True)
    (root / "论文" / "0.摘要.tex").write_text("摘要。", encoding="utf-8")
    (root / "交接" / "需求追踪矩阵.json").write_text(
        json.dumps([{"需求号": "1-1", "状态": "已销号"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "台账" / "审稿台账.json").write_text("[]", encoding="utf-8")


@pytest.mark.asyncio
async def test_s6_final_review_harvest_and_retrospective(tmp_path: Path) -> None:
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj", name="s6", profile="快速")
    try:
        root = handle.workspace.root
        (root / "论文" / "论文.tex").write_text("最终正文", encoding="utf-8")
        _seed_terminal_gate(root)
        (root / "求解" / "问题1").mkdir(parents=True, exist_ok=True)
        (root / "求解" / "问题1" / "求解_问题1.py").write_text("print(1)", encoding="utf-8")
        (root / "交接" / "结果声明_问题1.json").write_text("{}", encoding="utf-8")
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        script = MockScript(
            _write("f", "审稿/终审_1.json", {"页问题": [], "美观分": 9.0})
            + _write("t", "审稿/S6终审复核.json", {"通过": True, "依据版本": "当前PDF"})
            + _write("r", "审稿/复盘报告.json", {"总评": "完成", "回流账": "见回流账.json"})
        )
        result = await run_s6(
            handle.workspace.db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            compile_paper=_compile, render_pages=_render, beauty_baseline_pages=10,
        )
        assert result["pass"] is True, result["issues"]
        assert (root / "交付" / "论文.pdf").is_file()
        assert (root / "交付" / "论文源码" / "论文.tex").is_file()
        assert (root / "交付" / "交接" / "结果声明_问题1.json").is_file()
        assert (root / "交付" / "审稿" / "回流账.json").is_file()
        assert (root / "交付" / "审稿" / "复盘报告.json").is_file()
        assert (root / "审稿" / "回流账.json").is_file()
        done = events.query_events(
            handle.workspace.db, run_id=run_id, type="checkpoint.s6_complete"
        )
        assert len(done) == 1
    finally:
        handle.workspace.db.close()



@pytest.mark.asyncio
async def test_s6_figure_fix_reruns_plot_script(tmp_path: Path) -> None:
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj-figure", name="s6-figure", profile="快速")
    try:
        root = handle.workspace.root
        (root / "论文" / "论文.tex").write_text("最终正文", encoding="utf-8")
        _seed_terminal_gate(root)
        (root / "求解" / "问题1" / "图片").mkdir(parents=True, exist_ok=True)
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        final_review = {
            "页问题": [{
                "页": 1,
                "目标": "图",
                "严重度": 1,
                "问题": "问题1 图例需要最终调整",
                "修改指令": "更新图例后重新成图",
            }]
        }
        plot_script = (
            "from pathlib import Path\n"
            "Path('求解/问题1/图片/s6-rerun.marker').write_text('rerun', encoding='utf-8')\n"
        )
        script = MockScript(
            _write("f", "审稿/终审_1.json", final_review)
            + [
                MockTurn(tool_calls=[
                    ("plot-script", "fs.write", {
                        "path": "求解/问题1/绘图_终审.py",
                        "content": plot_script,
                    }),
                    ("plot-receipt", "fs.write", {
                        "path": "审稿/回执_S6_图问1.json",
                        "content": json.dumps({"改动": "更新图例"}, ensure_ascii=False),
                    }),
                ]),
                MockTurn(text="终审改图完成"),
            ]
            + _write(
                "sync",
                "审稿/回执_S6_图同步问1.json",
                {"改动": "同步图题与正文引用", "证据": "论文/论文.tex"},
            )
            + _write("t", "审稿/S6终审复核.json", {"通过": True, "依据版本": "当前PDF"})
            + _write("r", "审稿/复盘报告.json", {
                "总评": "完成",
                "回流账": "见回流账.json",
            })
        )
        result = await run_s6(
            handle.workspace.db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            compile_paper=_compile, render_pages=_render, beauty_baseline_pages=10,
        )
        assert result["pass"] is True, result["issues"]
        assert (root / "求解" / "问题1" / "图片" / "s6-rerun.marker").read_text(
            encoding="utf-8"
        ) == "rerun"
        assert (root / "审稿" / "回执_S6_图同步问1.json").is_file()
        assert (root / "交付" / "交付报告.md").is_file()
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s6_terminal_defect_review_gates_harvest(tmp_path: Path) -> None:
    """P1-5: the fresh S6 terminal current-PDF defect review (unique node +
    artifact) must gate the harvest; a rejecting review blocks delivery."""
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj-treview", name="s6-treview", profile="快速")
    try:
        root = handle.workspace.root
        (root / "论文" / "论文.tex").write_text("最终正文", encoding="utf-8")
        _seed_terminal_gate(root)
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        script = MockScript(
            _write("f", "审稿/终审_1.json", {"页问题": [], "美观分": 9.0})
            + _write("t", "审稿/S6终审复核.json",
                     {"通过": False, "依据版本": "当前PDF", "页码": [3]})
        )
        result = await run_s6(
            handle.workspace.db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            compile_paper=_compile, render_pages=_render, beauty_baseline_pages=10,
        )
        assert result["pass"] is False
        assert any("出版终审" in x for x in result["issues"])
        # Harvest and the completion checkpoint must not have happened.
        assert not (root / "交付" / "论文.pdf").is_file()
        done = events.query_events(
            handle.workspace.db, run_id=run_id, type="checkpoint.s6_complete"
        )
        assert not done
        failed = events.query_events(
            handle.workspace.db, run_id=run_id, type="s6.terminal_review_failed"
        )
        assert len(failed) == 1
    finally:
        handle.workspace.db.close()



@pytest.mark.asyncio
async def test_s6_figure_sync_failure_blocks_harvest(tmp_path: Path) -> None:
    """A final figure mutation is not complete until dependent text sync passes."""
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj-figure-syncfail", name="s6-figure-syncfail", profile="快速")
    try:
        root = handle.workspace.root
        (root / "论文" / "论文.tex").write_text("最终正文", encoding="utf-8")
        _seed_terminal_gate(root)
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        final_review = {
            "页问题": [{
                "页": 1,
                "目标": "图",
                "严重度": 1,
                "问题": "问题1 图例需要最终调整",
                "修改指令": "更新图例并同步正文",
            }]
        }
        plot_script = (
            "from pathlib import Path\n"
            "Path('求解/问题1/图片').mkdir(parents=True, exist_ok=True)\n"
            "Path('求解/问题1/图片/s6-syncfail.marker').write_text('rerun', encoding='utf-8')\n"
        )
        script = MockScript(
            _write("f", "审稿/终审_1.json", final_review)
            + [
                MockTurn(tool_calls=[
                    ("plot-script", "fs.write", {
                        "path": "求解/问题1/绘图_终审.py",
                        "content": plot_script,
                    }),
                    ("plot-receipt", "fs.write", {
                        "path": "审稿/回执_S6_图问1.json",
                        "content": json.dumps({"改动": "更新图例"}, ensure_ascii=False),
                    }),
                ]),
                MockTurn(text="终审改图完成"),
            ]
            + [MockTurn(text="不同步正文"), MockTurn(text="仍不同步正文")]
        )
        result = await run_s6(
            handle.workspace.db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            compile_paper=_compile, render_pages=_render, beauty_baseline_pages=10,
        )
        assert result["pass"] is False
        assert any("正文同步失败" in x for x in result["issues"])
        assert not (root / "交付" / "论文.pdf").exists()
        assert not events.query_events(
            handle.workspace.db, run_id=run_id, type="checkpoint.s6_complete"
        )
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s6_delivery_report_discloses_degraded_state(tmp_path: Path) -> None:
    """Delivery must surface known degraded/unresolved state in a human-readable Runtime report."""
    from mmagent.api.projects import create_project
    from mmagent.mm.contracts.degraded_release import upsert_degraded_review_issue

    handle = create_project(tmp_path / "proj-delivery-report", name="s6-report", profile="快速")
    try:
        root = handle.workspace.root
        (root / "论文" / "论文.tex").write_text("最终正文", encoding="utf-8")
        _seed_terminal_gate(root)
        (root / "台账" / "审稿台账.json").write_text(
            json.dumps([{
                "id": "审-9-01",
                "generation": 2,
                "级别": "正确性",
                "目标": "文",
                "状态": "搁置",
                "尝试次数": 2,
                "问题": "已披露的残余限制",
                "搁置原因": "升级已耗尽",
                "历史": [],
                "回执": [],
            }], ensure_ascii=False),
            encoding="utf-8",
        )
        upsert_degraded_review_issue(
            root,
            issue_id="审-9-01",
            generation=2,
            severity="正确性",
            reason="升级已耗尽，公开降级放行",
        )
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        script = MockScript(
            _write("f", "审稿/终审_1.json", {"页问题": [], "美观分": 9.0})
            + _write("t", "审稿/S6终审复核.json", {"通过": True, "依据版本": "当前PDF"})
            + _write("r", "审稿/复盘报告.json", {"总评": "完成"})
        )
        result = await run_s6(
            handle.workspace.db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            compile_paper=_compile, render_pages=_render, beauty_baseline_pages=10,
        )
        assert result["pass"] is True
        report = (root / "交付" / "交付报告.md").read_text(encoding="utf-8")
        assert "审-9-01" in report
        assert "generation=2" in report
        assert "升级已耗尽" in report
        assert result["delivery_report"] == "交付报告.md"
    finally:
        handle.workspace.db.close()
