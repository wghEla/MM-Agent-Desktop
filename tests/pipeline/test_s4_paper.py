from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.mm.pipeline.s4_paper import run_s4
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


def _turn_write(call_id: str, path: str, content: str) -> list[MockTurn]:
    return [
        MockTurn(tool_calls=[(call_id, "fs.write", {"path": path, "content": content})]),
        MockTurn(text="完成"),
    ]


def _script() -> MockScript:
    narrative = "## 问题1\n" + (
        "本问先说明题目给出的对象与目标，再解释主要困难和信息之间的联系，随后说明我们准备如何建立模型、"
        "怎样利用已有结果检查合理性，以及最终需要交付哪些能够让评委直接核验的结论。"
    ) * 5
    turns: list[MockTurn] = []
    turns += [
        MockTurn(tool_calls=[
            ("n1", "fs.write", {"path": "交接/叙事底稿.md", "content": narrative}),
            ("n2", "fs.write", {"path": "交接/论点脊柱.json", "content": '{"主线":"证据驱动"}'}),
        ]),
        MockTurn(text="叙事完成"),
    ]
    turns += [
        MockTurn(tool_calls=[
            ("d1", "fs.write", {"path": "论文/论文.tex", "content": "正文以问题为主线组织，方法与结论逐段对应。"}),
            ("d2", "fs.write", {"path": "交接/需求覆盖.json", "content": json.dumps([{
                "需求号": "一", "章节": "问题一", "证据": "正文对应段", "图表": "", "关键数字": ""
            }], ensure_ascii=False)}),
        ]),
        MockTurn(text="正文与覆盖表完成"),
    ]
    turns += _turn_write("c1", "审稿/章评R1.json", '{"总分":8.3,"问题":[]}')
    turns += _turn_write("b1", "审稿/读者R1.json", '{"读者分":8.1,"卡住":[]}')
    turns += _turn_write("i1", "审稿/统稿回执.json", '{"修改":"仅语言层"}')

    names = ["甲", "乙", "丙"]
    scores = [8.0, 9.1, 8.7]
    for index, (name, score) in enumerate(zip(names, scores, strict=True), 1):
        turns += _turn_write(
            f"a{index}", f"论文/摘要候选_{index}.tex",
            f"摘要候选{name}，能够复述对象、方法、结果与局限。"
        )
        verdict = json.dumps({"通过": True, "分数": score}, ensure_ascii=False)
        turns += _turn_write(f"v{index}", f"审稿/摘要复述_{index}.json", verdict)
    return MockScript(turns)


def _fake_compile(root: Path) -> dict:
    (root / "论文" / "论文.log").write_text(
        "Output written on 论文.pdf (10 pages).", encoding="utf-8"
    )
    return {"rc": 0, "errors": [], "pages": 10}


@pytest.mark.asyncio
async def test_s4_multi_role_swarm_selects_best_abstract_and_passes_g4(tmp_path: Path) -> None:
    from mmagent.api.projects import create_project

    handle = create_project(tmp_path / "proj", name="s4", profile="快速")
    try:
        root = handle.workspace.root
        (root / "交接" / "需求追踪矩阵.json").write_text(
            json.dumps([{"需求号": "一", "状态": "已销号"}], ensure_ascii=False),
            encoding="utf-8",
        )
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        result = await run_s4(
            handle.workspace.db,
            MockProvider(_script()),
            _registry(),
            PathPolicy(root),
            run_id,
            problem_numbers=[1],
            profile="快速",
            compile_paper=_fake_compile,
        )
        assert result["g4_pass"], result["g4_issues"]
        assert result["selected_abstract"] == 2
        assert (root / "论文" / "0.摘要.tex").read_text(encoding="utf-8").startswith("摘要候选乙")
        assert result["reviews"][0]["chapter_score"] == 8.3
        assert result["reviews"][0]["reader_score"] == 8.1
    finally:
        handle.workspace.db.close()
