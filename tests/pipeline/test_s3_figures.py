from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.mm.pipeline.s3_figures import run_s3
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.state import repositories
from mmagent.tools.filesystem import FsReadTool, FsWriteTool
from mmagent.tools.python import PythonRunTool
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.path_policy import PathPolicy


def _seed_figure_scripts(root: Path) -> None:
    q = root / "求解" / "问题1"
    (q / "图片").mkdir(parents=True)
    patterns = [
        "FancyArrowPatch", "FancyBboxPatch", "add_patch(",
        "ax.plot(", "ax.plot(", "ax.bar(", "ax.barh(",
        "ax.scatter(", "ax.scatter(", "ax.imshow(", "ax.pcolormesh(",
        "ax.boxplot(", "ax.boxplot(",
    ]
    for i, marker in enumerate(patterns):
        (q / f"绘图_{i:02d}.py").write_text(
            f"# {marker}\\nprint(\'ok\')\\n", encoding="utf-8"
        )
    for i in range(16):
        (q / "图片" / f"fig_{i:02d}.png").write_bytes(b"PNG")


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(FsReadTool())
    reg.register(FsWriteTool())
    reg.register(PythonRunTool())
    return reg


@pytest.mark.asyncio
async def test_s3_plot_execute_review_and_g3(tmp_path: Path) -> None:
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj", name="s3", profile="标准")
    try:
        root = handle.workspace.root
        _seed_figure_scripts(root)
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="标准"
        )
        script = MockScript([
            MockTurn(tool_calls=[
                ("p1", "fs.write", {
                    "path": "交接/图注素材_问题1.json",
                    "content": json.dumps({"问题": 1, "图": []}, ensure_ascii=False),
                }),
            ]),
            MockTurn(text="绘图材料完成"),
            MockTurn(tool_calls=[
                ("r1", "fs.write", {
                    "path": "审稿/图评R1_问题1.json",
                    "content": json.dumps({"总分": 8.2, "问题": []}, ensure_ascii=False),
                }),
            ]),
            MockTurn(text="图评完成"),
        ])
        result = await run_s3(
            handle.workspace.db, MockProvider(script), _registry(),
            PathPolicy(root), run_id, problem_numbers=[1], profile="标准"
        )
        assert result["g3_pass"], result["g3_issues"]
        assert result["reviews"] == [{"question": 1, "round": 1, "score": 8.2}]
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s3_low_score_triggers_targeted_revision(tmp_path: Path) -> None:
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj", name="s3-revision", profile="标准")
    try:
        root = handle.workspace.root
        _seed_figure_scripts(root)
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="标准"
        )
        caption = json.dumps({"问题": 1}, ensure_ascii=False)
        script = MockScript([
            MockTurn(tool_calls=[("p1", "fs.write", {"path": "交接/图注素材_问题1.json", "content": caption})]),
            MockTurn(text="绘图完成"),
            MockTurn(tool_calls=[("r1", "fs.write", {"path": "审稿/图评R1_问题1.json", "content": '{"总分": 6.5}'})]),
            MockTurn(text="首轮图评"),
            MockTurn(tool_calls=[("p2", "fs.write", {"path": "交接/图注素材_问题1.json", "content": caption})]),
            MockTurn(text="定向修图完成"),
            MockTurn(tool_calls=[("r2", "fs.write", {"path": "审稿/图评R2_问题1.json", "content": '{"总分": 7.5}'})]),
            MockTurn(text="二轮图评"),
        ])
        result = await run_s3(
            handle.workspace.db, MockProvider(script), _registry(),
            PathPolicy(root), run_id, problem_numbers=[1], profile="标准"
        )
        assert result["g3_pass"], result["g3_issues"]
        assert [r["score"] for r in result["reviews"]] == [6.5, 7.5]
    finally:
        handle.workspace.db.close()
