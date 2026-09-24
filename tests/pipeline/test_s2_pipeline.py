from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.mm.pipeline.s2_model import run_s2
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.state import repositories
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
