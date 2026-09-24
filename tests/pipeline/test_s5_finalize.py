from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.mm.gates.g5 import check_g5
from mmagent.mm.guards.guards import stale_value_guard
from mmagent.mm.pipeline.s5_finalize import run_g5, run_s5a, run_s5b
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.state import repositories
from mmagent.tools.filesystem import FsReadTool, FsWriteTool
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.path_policy import PathPolicy


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(FsReadTool())
    reg.register(FsWriteTool())
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
            + _write("v", "审稿/摘要复述_定稿1.json", {"通过": True})
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
            + _write("p", "审稿/回执_美化R1_图问1.json", {"改动": "放大图例"})
        )
        result = await run_s5b(
            handle.workspace.db, MockProvider(script), _registry(), PathPolicy(root), run_id,
            profile="快速", compile_paper=_compile, render_pages=_render,
        )
        assert result["pass"] is True
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
        {"id": "审-1-01", "级别": "正确性", "状态": "搁置"}
    ], ensure_ascii=False), encoding="utf-8")
    ok, issues = check_g5(root, beauty_baseline_pages=10, current_pages=10)
    assert not ok
    assert any("降级放行" in x for x in issues)


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
