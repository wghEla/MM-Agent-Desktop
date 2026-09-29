from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.mm.pipeline.s0_s1 import run_s1
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


def _script() -> MockScript:
    scout = json.dumps({
        "问题清单": [{
            "编号": 1,
            "路线": [
                {"路线名": "路线A", "方法": "最小二乘", "方法理由": "稳定"},
                {"路线名": "路线B", "方法": "鲁棒回归", "方法理由": "抗异常"},
            ],
        }],
        "最难问题编号": 1,
    }, ensure_ascii=False)
    plan = json.dumps({
        "问题清单": [{
            "编号": 1, "主方法": "最小二乘", "依赖问题": [],
            "锦标赛": {
                "参赛路线": ["路线A", "路线B"],
                "优胜": "路线A",
                "依据": "两条原型均真跑，A诊断更稳定",
            },
        }],
        "叙事主线": "先用原型比较路线，再进入正式建模",
    }, ensure_ascii=False)
    return MockScript([
        MockTurn(tool_calls=[
            ("s", "fs.write", {"path": "交接/路线侦察.json", "content": scout})
        ]),
        MockTurn(text="侦察完成"),
        MockTurn(tool_calls=[
            ("p1", "fs.write", {
                "path": "求解/问题1/原型_1.py",
                "content": "print('A score=0.9')\n",
            })
        ]),
        MockTurn(text="原型A完成"),
        MockTurn(tool_calls=[
            ("p2", "fs.write", {
                "path": "求解/问题1/原型_2.py",
                "content": "print('B score=0.8')\n",
            })
        ]),
        MockTurn(text="原型B完成"),
        MockTurn(tool_calls=[
            ("f", "fs.write", {"path": "交接/计划.json", "content": plan})
        ]),
        MockTurn(text="定稿完成"),
    ])


@pytest.mark.asyncio
async def test_s1_tournament_runs_real_prototypes_before_final_plan(tmp_path: Path) -> None:
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj", name="s1", profile="快速")
    try:
        root = handle.workspace.root
        (root / "交接" / "题面契约.json").write_text("{}", encoding="utf-8")
        (root / "交接" / "数据档案.json").write_text('{"条目":[]}', encoding="utf-8")
        (root / "交接" / "典型答卷预测.md").write_text("普通路线会撞车", encoding="utf-8")
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        result = await run_s1(
            handle.workspace.db, MockProvider(_script()), _registry(),
            PathPolicy(root), run_id, profile="快速"
        )
        assert result["g1_pass"], result["g1_issues"]
        evidence = json.loads(
            (root / "交接" / "原型结果.json").read_text(encoding="utf-8")
        )
        assert len(evidence["条目"]) == 2
        assert all(x["rc"] == 0 for x in evidence["条目"])
        assert "A score=0.9" in evidence["条目"][0]["stdout_tail"]
    finally:
        handle.workspace.db.close()
