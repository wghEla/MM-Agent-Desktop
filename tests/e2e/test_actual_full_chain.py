from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.api.projects import create_project
from mmagent.mm.pipeline.s0_s1 import run_s0
from mmagent.mm.pipeline.topology import PIPELINE_SEQUENCE
from mmagent.orchestration.engine import PaperFoundryEngine, PipelineHooks
from mmagent.orchestration.role_leg import run_role_leg
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.state import events, repositories
from mmagent.state.models import RunStatus, TaskStatus
from mmagent.tools.filesystem import FsReadTool, FsWriteTool
from mmagent.tools.python import PythonRunTool
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy


def _write(call_id: str, path: str, payload) -> list[MockTurn]:
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return [
        MockTurn(tool_calls=[(call_id, "fs.write", {"path": path, "content": content})]),
        MockTurn(text="完成"),
    ]


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(FsReadTool())
    reg.register(FsWriteTool())
    reg.register(PythonRunTool())
    return reg


def _provider_script() -> MockScript:
    turns: list[MockTurn] = []

    # S0 reader + answer predictor
    contract = {
        "赛题": "SYN",
        "标题": "合成单问数模题",
        "问题": [{
            "编号": 1,
            "原文摘录": "根据给定数据估计参数并验证结果。",
            "解读": "需要得到一个可复核数值结果",
            "需求条目": [{"需求号": "1-1", "内容": "给出参数估计", "评分点推测": "数值与验证"}],
        }],
        "硬约束清单": [],
        "歧义裁定": [],
        "附件清单": [],
    }
    turns += [
        MockTurn(tool_calls=[
            ("s0c", "fs.write", {"path": "交接/题面契约.json", "content": json.dumps(contract, ensure_ascii=False)}),
            ("s0d", "fs.write", {"path": "交接/数据档案.json", "content": '{"条目":[]}'}),
        ]),
        MockTurn(text="读题完成"),
    ]
    turns += _write("s0p", "交接/典型答卷预测.md", "普通答卷会直接给数字，缺少独立验证与图证。")

    # S1 scout -> two real prototype scripts -> final plan
    scout = {
        "问题清单": [{
            "编号": 1,
            "路线": [
                {"路线名": "路线A", "方法": "解析估计", "方法理由": "简单可核验"},
                {"路线名": "路线B", "方法": "数值估计", "方法理由": "作为对照"},
            ],
        }],
        "最难问题编号": 1,
    }
    turns += _write("s1s", "交接/路线侦察.json", scout)
    turns += _write("s1a", "求解/问题1/原型_1.py", "print('route A diagnostic=0.95')\n")
    turns += _write("s1b", "求解/问题1/原型_2.py", "print('route B diagnostic=0.90')\n")
    plan = {
        "问题清单": [{
            "编号": 1,
            "主方法": "解析估计",
            "依赖问题": [],
            "锦标赛": {
                "参赛路线": ["路线A", "路线B"],
                "优胜": "路线A",
                "依据": "两条原型均真实执行，A 的诊断更稳定",
            },
        }],
        "叙事主线": "先比较路线，再正式建模并独立复算",
    }
    turns += _write("s1f", "交接/计划.json", plan)

    # S2 model script -> interpreter declaration -> red-team script/report
    solver = (
        "from pathlib import Path\nimport json\n"
        "p=Path('求解/问题1/结果'); p.mkdir(parents=True, exist_ok=True)\n"
        "(p/'结果.json').write_text(json.dumps({'参数':2.17}), encoding='utf-8')\n"
    )
    turns += _write("s2m", "求解/问题1/求解_问题1.py", solver)
    turns += [
        MockTurn(tool_calls=[
            ("s2i1", "fs.write", {
                "path": "交接/结果声明_问题1.json",
                "content": json.dumps({"问题编号": 1, "核心指标": {"参数": 2.17}}, ensure_ascii=False),
            }),
            ("s2i2", "fs.write", {"path": "交接/结果解读_问题1.md", "content": "参数估计为 2.17。"}),
        ]),
        MockTurn(text="结果解读完成"),
    ]
    red_script = (
        "from pathlib import Path\nimport json\n"
        "p=Path('求解/问题1/红队结果'); p.mkdir(parents=True, exist_ok=True)\n"
        "(p/'复算.json').write_text(json.dumps({'参数':2.17}), encoding='utf-8')\n"
    )
    turns += _write("s2r1", "求解/问题1/复算.py", red_script)
    turns += _write("s2r2", "交接/红队_问题1.json", {
        "问题编号": 1,
        "复算方式": "独立解析复算",
        "复算指标": [{"键": "参数", "声明值": 2.17, "复算值": 2.17}],
        "结论": "对齐",
        "分歧明细": [],
    })

    # S3 plotter writes scripts/caption. Runtime executes all plot scripts.
    plot_calls = []
    plot_dir_script = (
        "from pathlib import Path\n"
        "p=Path('求解/问题1/图片'); p.mkdir(parents=True, exist_ok=True)\n"
        "[ (p/f'fig_{i:02d}.png').write_bytes(b'PNG') for i in range(16) ]\n"
    )
    plot_calls.append(("s3p0", "fs.write", {"path": "求解/问题1/绘图_00.py", "content": "# FancyArrowPatch\n" + plot_dir_script}))
    markers = [
        "FancyBboxPatch", "add_patch(", "ax.plot(", "ax.plot(", "ax.bar(",
        "ax.barh(", "ax.scatter(", "ax.scatter(", "ax.imshow(", "ax.pcolormesh(",
        "ax.boxplot(", "ax.boxplot(",
    ]
    for i, marker in enumerate(markers, 1):
        plot_calls.append((f"s3p{i}", "fs.write", {
            "path": f"求解/问题1/绘图_{i:02d}.py",
            "content": f"# {marker}\nprint('plot {i}')\n",
        }))
    plot_calls.append(("s3cap", "fs.write", {
        "path": "交接/图注素材_问题1.json",
        "content": json.dumps({"问题": 1, "图": [{"图号": i + 1} for i in range(16)]}, ensure_ascii=False),
    }))
    turns += [MockTurn(tool_calls=plot_calls), MockTurn(text="图证脚本完成")]
    # 16 figures are reviewed in two image batches (max 8 images per leg).
    turns += _write("s3rev1", "审稿/图评R1_问题1_B1.json", {"总分": 8.2, "问题": []})
    turns += _write("s3rev2", "审稿/图评R1_问题1_B2.json", {"总分": 8.4, "问题": []})

    # S4 narrative/draft + requirement coverage + reviews + 3 abstract candidates
    narrative = "## 问题1\n" + (
        "本问首先说明题目要求的参数估计目标和证据要求，然后解释解析估计路线为何适用于这组数据，"
        "再说明我们如何利用独立复算检查结果一致性，并通过多种图证展示结果稳定性和结论边界，"
        "最后明确给出评委可以直接核验的参数结果、验证证据和局限。"
    ) * 5
    turns += [
        MockTurn(tool_calls=[
            ("s4n1", "fs.write", {"path": "交接/叙事底稿.md", "content": narrative}),
            ("s4n2", "fs.write", {"path": "交接/论点脊柱.json", "content": '{"主线":"估计-复算-图证"}'}),
        ]),
        MockTurn(text="叙事完成"),
    ]
    turns += [
        MockTurn(tool_calls=[
            ("s4d", "fs.write", {
                "path": "论文/论文.tex",
                "content": "正文围绕参数估计、独立复算与图证展开。\n\n结论明确回答题目要求。",
            }),
            ("s4cov", "fs.write", {
                "path": "交接/需求覆盖.json",
                "content": json.dumps([{
                    "需求号": "1-1",
                    "章节": "问题一",
                    "证据": "参数估计与独立复算段",
                    "图表": "图1",
                    "关键数字": "2.17",
                }], ensure_ascii=False),
            }),
        ]),
        MockTurn(text="正文完成"),
    ]
    turns += _write("s4c", "审稿/章评R1.json", {"总分": 8.3, "问题": []})
    turns += _write("s4b", "审稿/读者R1.json", {"读者分": 8.1, "卡住": []})
    turns += _write("s4i", "审稿/统稿回执.json", {"修改": "仅语言层"})
    for index, score in enumerate((8.0, 9.2, 8.7), 1):
        turns += _write(
            f"s4a{index}", f"论文/摘要候选_{index}.tex",
            f"摘要候选{index}：对象、方法、结果2.17与独立验证均可复述。 % src: 交接/结果声明_问题1.json",
        )
        turns += _write(
            f"s4v{index}", f"审稿/摘要复述_{index}.json",
            {"通过": True, "分数": score},
        )

    # S5 four independent review legs: no blocking issues -> converged first round.
    turns += _write("s5a", "审稿/审稿意见_轮1A.json", {"意见": [], "裁定": []})
    turns += _write("s5b", "审稿/审稿意见_轮1B.json", {"意见": [], "裁定": []})
    turns += _write("s5h", "审稿/硬伤_轮1.json", {"意见": [], "裁定": []})
    turns += _write("s5j", "审稿/评委模拟_轮1.json", {"意见": [], "裁定": []})

    # S5a final abstract + restatement
    turns += _write("s5af", "论文/0.摘要.tex", "最终摘要可复述对象、方法、结果2.17和局限。 % src: 交接/结果声明_问题1.json")
    turns += _write("s5av", "审稿/摘要复述_定稿1.json", {"通过": True, "分数": 8.5})

    # S5b page review -> no changes
    turns += _write("s5beauty", "审稿/美1.json", {"页问题": [], "美观分": 9.0})

    # G5 final defect verification
    turns += _write("g5", "审稿/G5复核.json", {"通过": True, "依据版本": "当前PDF", "页码": [1]})

    # S6 final page review + retrospective
    turns += _write("s6f", "审稿/终审_1.json", {"页问题": [], "美观分": 9.1})
    turns += _write("s6r", "审稿/复盘报告.json", {
        "总评": "全链完成",
        "回流账": "见 审稿/回流账.json",
        "瓶颈环节": [],
        "规则库修改建议": [],
    })
    return MockScript(turns)


def _compile(root: Path) -> dict:
    paper_dir = root / "论文"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "论文.log").write_text(
        "Output written on 论文.pdf (10 pages).", encoding="utf-8"
    )
    (paper_dir / "论文.pdf").write_bytes(b"%PDF-synthetic-e2e")
    return {"rc": 0, "errors": [], "pages": 10}


def _render(root: Path) -> list[Path]:
    page_dir = root / "论文" / "页"
    page_dir.mkdir(parents=True, exist_ok=True)
    page = page_dir / "page-001.png"
    page.write_bytes(b"PNG")
    return [page]


@pytest.mark.asyncio
async def test_actual_engine_full_chain_to_delivery_pdf(tmp_path: Path) -> None:
    """Real stage modules S0→S6 with mock LLM output but real Python tool execution."""
    handle = create_project(tmp_path / "proj", name="full-chain", profile="快速")
    try:
        root = handle.workspace.root
        (root / "输入" / "题目" / "题.pdf").write_bytes(b"%PDF-synthetic")
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        handle.workspace.acquire_run_lock(run_id)

        engine = PaperFoundryEngine(
            handle.workspace,
            MockProvider(_provider_script()),
            _registry(),
            run_id,
            hooks=PipelineHooks(compile_paper=_compile, render_pages=_render),
        )
        result = await engine.run(resume=True)

        row = handle.workspace.db.query_one(
            "SELECT status FROM runs WHERE id = ?", (run_id,)
        )
        assert row["status"] == RunStatus.SUCCEEDED.value
        assert result.degraded_questions == ()
        assert (root / "交付" / "论文.pdf").is_file()
        assert (root / "审稿" / "复盘报告.json").is_file()
        assert (root / "求解" / "问题1" / "结果" / "结果.json").is_file()
        assert (root / "求解" / "问题1" / "红队结果" / "复算.json").is_file()

        checkpoints = {
            str(e.payload.get("key"))
            for e in events.query_events(
                handle.workspace.db, run_id=run_id, type="checkpoint.stage", limit=1000
            )
        }
        assert checkpoints == set(PIPELINE_SEQUENCE)
    finally:
        handle.workspace.db.close()



@pytest.mark.asyncio
async def test_actual_engine_recovers_mid_s1_and_finishes_delivery(tmp_path: Path) -> None:
    """Crash in a real S1 node, then reuse sealed nodes and finish S0→S6.

    This is intentionally stronger than the controller fake-engine tests:
    S0 and the first S1 legs are real AgentLoop executions, an invocation is
    left RUNNING to model a hard process loss, and a fresh engine/provider
    instance resumes the same durable run.
    """
    handle = create_project(tmp_path / "proj-resume", name="resume-chain", profile="快速")
    try:
        root = handle.workspace.root
        (root / "输入" / "题目" / "题.pdf").write_bytes(b"%PDF-synthetic")
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="快速"
        )
        handle.workspace.acquire_run_lock(run_id)
        repositories.set_run_status(handle.workspace.db, run_id, RunStatus.RUNNING)

        full_script = _provider_script()
        partial_provider = MockProvider(MockScript(full_script.turns[:8]))
        registry = _registry()
        policy = PathPolicy(root)

        s0 = await run_s0(
            handle.workspace.db,
            partial_provider,
            registry,
            policy,
            run_id,
        )
        assert s0["g0_pass"] is True

        scout_status = await run_role_leg(
            handle.workspace.db,
            partial_provider,
            registry,
            policy,
            run_id,
            stage_key="S1",
            role_id="planner",
            node_key="S1:路线侦察",
            instructions="写 交接/路线侦察.json。",
            expected_artifacts=[ExpectedArtifact(rel_path="交接/路线侦察.json")],
        )
        assert scout_status == "SUCCEEDED"

        prototype_one = await run_role_leg(
            handle.workspace.db,
            partial_provider,
            registry,
            policy,
            run_id,
            stage_key="S1",
            role_id="modeler",
            node_key="S1:问1:原型1",
            question_num=1,
            instructions="写 求解/问题1/原型_1.py。",
            expected_artifacts=[
                ExpectedArtifact(rel_path="求解/问题1/原型_1.py", kind="text")
            ],
        )
        assert prototype_one == "SUCCEEDED"
        assert partial_provider.script.cursor == 8

        # Leave prototype 2 in a genuinely active invocation, as if the process
        # disappeared after acquiring the execution lease.
        interrupted = repositories.create_task(
            handle.workspace.db,
            run_id=run_id,
            stage_key="S1",
            node_key="S1:问1:原型2",
            role_id="modeler",
            expected_artifacts=[
                {"rel_path": "求解/问题1/原型_2.py", "kind": "text"}
            ],
            max_attempts=2,
        )
        repositories.transition_task(
            handle.workspace.db, interrupted.id, TaskStatus.READY
        )
        repositories.transition_task(
            handle.workspace.db, interrupted.id, TaskStatus.QUEUED
        )
        owner = repositories.new_owner_token()
        assert repositories.acquire_task_lease(
            handle.workspace.db, interrupted.id, owner
        )
        _, orphan_invocation = repositories.begin_task_attempt(
            handle.workspace.db,
            interrupted.id,
            owner,
            role_id="modeler",
            provider_profile="default",
            model="mock",
            reasoning="xhigh",
        )

        # Fresh engine + fresh provider instance.  The remaining scripted turns
        # begin exactly where the interrupted S1 node would have continued.
        resumed = PaperFoundryEngine(
            handle.workspace,
            MockProvider(MockScript(full_script.turns[8:])),
            registry,
            run_id,
            hooks=PipelineHooks(compile_paper=_compile, render_pages=_render),
        )
        result = await resumed.run(resume=True)

        status = handle.workspace.db.query_one(
            "SELECT status FROM runs WHERE id = ?", (run_id,)
        )
        assert status["status"] == RunStatus.SUCCEEDED.value
        assert result.degraded_questions == ()
        assert (root / "交付" / "论文.pdf").is_file()

        orphan = handle.workspace.db.query_one(
            "SELECT status, ended_at FROM agent_invocations WHERE id = ?",
            (orphan_invocation,),
        )
        assert orphan["status"] == "FAILED"
        assert orphan["ended_at"] is not None

        recovered = events.query_events(
            handle.workspace.db, run_id=run_id, type="pipeline.recovered"
        )
        assert recovered
        assert recovered[-1].payload["interrupted_tasks"] == 1

        reused_nodes = {
            event.payload.get("node")
            for event in events.query_events(
                handle.workspace.db,
                run_id=run_id,
                type="pipeline.node_reused",
                limit=1000,
            )
        }
        assert {
            "S0.2:读题",
            "S0.3:预测",
            "S1:路线侦察",
            "S1:问1:原型1",
        }.issubset(reused_nodes)

        retried = repositories.get_task(handle.workspace.db, interrupted.id)
        assert retried.status is TaskStatus.SUCCEEDED
        assert retried.attempt == 2
    finally:
        handle.workspace.release_run_lock()
        handle.workspace.db.close()
