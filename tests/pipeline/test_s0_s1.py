"""S0/S1 流水线 + G0/G1 门检（mock provider 级集成测试）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.agent.errors import ArtifactInvalid
from mmagent.mm.contracts.s0_contracts import (
    DATA_ARCHIVE_REQUIRED_TOP_LEVEL_KEYS,
    PROBLEM_CONTRACT_REQUIRED_TOP_LEVEL_KEYS,
    DataArchive,
    ProblemContract,
)
from mmagent.mm.pipeline.s0_s1 import _s0_specs, check_g1, run_s0
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.state import repositories
from mmagent.tools.filesystem import FsReadTool, FsWriteTool
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import verify_expected_artifacts
from mmagent.workspace.permissions import PermissionChecker, RolePermissions


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(FsReadTool())
    reg.register(FsWriteTool())
    return reg


def _perms(policy) -> PermissionChecker:
    # 全角色测试权限（读/写全工作区 + fs 工具；不需要 host_code）
    perms = RolePermissions(
        role_id="test", read_scopes=("**",), write_scopes=("交接/**",),
        allowed_tools=frozenset({"fs.read", "fs.write"}),
    )
    return PermissionChecker(perms, policy)


CONTRACT_JSON = json.dumps({
    "赛题": "B", "标题": "测试题",
    "问题": [
        {"编号": 1, "原文摘录": "问题1", "解读": "解读1",
         "需求条目": [{"需求号": "1-1", "内容": "建模", "评分点推测": "推导"}]},
    ],
    "硬约束清单": [{"约束号": "C1", "内容": "约束"}],
    "歧义裁定": [],
    "附件清单": [],
}, ensure_ascii=False)

ARCHIVE_JSON = json.dumps({"条目": []}, ensure_ascii=False)

PREDICTION_MD = "# 典型答卷预测\n\n## 必然撞车的方法\n- 线性回归\n"

PLAN_JSON = json.dumps({
    "问题清单": [
        {"编号": 1, "主方法": "最小二乘拟合", "依赖问题": [], "标题": "问题一",
         "锦标赛": {"参赛路线": ["路线A", "路线B"], "优胜": "路线A", "依据": "两条原型 rc=0"}},
    ],
    "叙事主线": "从数据到厚度",
}, ensure_ascii=False)


def _mock_script_s0() -> MockScript:
    """四回合：读题官两回合（工具调用+终文本）、预测官两回合（工具调用+终文本）。"""
    return MockScript([
        # 读题官：写两个文件
        MockTurn(tool_calls=[
            ("c1", "fs.write", {"path": "交接/题面契约.json", "content": CONTRACT_JSON}),
            ("c2", "fs.write", {"path": "交接/数据档案.json", "content": ARCHIVE_JSON}),
        ]),
        # 读题官：终文本
        MockTurn(text="读题完成"),
        # 答卷预测官：写预测文件
        MockTurn(tool_calls=[
            ("c3", "fs.write", {"path": "交接/典型答卷预测.md", "content": PREDICTION_MD}),
        ]),
        # 答卷预测官：终文本
        MockTurn(text="预测完成"),
    ])


@pytest.fixture
def ws_full(tmp_path: Path):
    from mmagent.api.projects import create_project

    root = tmp_path / "proj"
    handle = create_project(root, name="test", profile="standard")
    # 预置输入文件
    (root / "输入" / "题目").mkdir(parents=True, exist_ok=True)
    (root / "输入" / "题目" / "题.pdf").write_bytes(b"%PDF")
    (root / "输入" / "数据").mkdir(parents=True, exist_ok=True)
    yield handle
    handle.workspace.db.close()


def test_s0_reader_enforces_canonical_contracts_before_g0(ws_full):
    """Wrong synonym/English-style keys fail at Reader artifact acceptance, not only G0."""
    root = ws_full.workspace.root
    specs = _s0_specs()
    role_id, node_key, instructions, expected = specs[0]

    assert role_id == "reader"
    assert node_key == "S0.2:读题"
    assert "canonical JSON Schema=" in instructions
    assert "“赛题”" in instructions
    assert expected[0].schema_model is ProblemContract
    assert expected[1].schema_model is DataArchive
    assert expected[0].required_json_keys == PROBLEM_CONTRACT_REQUIRED_TOP_LEVEL_KEYS
    assert expected[1].required_json_keys == DATA_ARCHIVE_REQUIRED_TOP_LEVEL_KEYS

    # This mimics the real-provider drift seen in the first Groq gate: a semantic
    # synonym is used instead of the canonical Chinese contract field.
    wrong_contract = {
        "题目": "B",
        "标题": "测试题",
        "问题": [{
            "编号": 1,
            "原文摘录": "问题1",
            "解读": "解读1",
            "需求条目": [{"需求号": "1-1", "内容": "建模"}],
        }],
        "硬约束清单": [],
        "歧义裁定": [],
        "附件清单": [],
    }
    (root / "交接" / "题面契约.json").write_text(
        json.dumps(wrong_contract, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "交接" / "数据档案.json").write_text(
        ARCHIVE_JSON,
        encoding="utf-8",
    )

    from mmagent.workspace.path_policy import PathPolicy

    with pytest.raises(ArtifactInvalid, match="题面契约.json"):
        verify_expected_artifacts(PathPolicy(root), expected)

    # The archive envelope is also explicit: an empty JSON object must not silently
    # acquire the Pydantic default and seal as a valid producer artifact.
    (root / "交接" / "题面契约.json").write_text(
        CONTRACT_JSON,
        encoding="utf-8",
    )
    (root / "交接" / "数据档案.json").write_text(
        "{}",
        encoding="utf-8",
    )
    with pytest.raises(ArtifactInvalid, match="数据档案.json"):
        verify_expected_artifacts(PathPolicy(root), expected)


@pytest.mark.asyncio
async def test_s0_pipeline_with_g0(ws_full):
    """S0 mock 流 → G0 通过。"""
    ws, db = ws_full, ws_full.workspace.db
    run_id = repositories.create_run(db, project_id=ws.project_id, profile="standard")
    from mmagent.workspace.path_policy import PathPolicy
    policy = PathPolicy(ws.workspace.root)
    provider = MockProvider(_mock_script_s0())
    result = await run_s0(db, provider, _registry(), policy, run_id, cancel=None)
    assert result["g0_pass"], result["g0_issues"]
    # 产物存在
    assert (ws.workspace.root / "交接" / "题面契约.json").is_file()
    assert (ws.workspace.root / "交接" / "需求追踪矩阵.json").is_file()
    # 矩阵条目数 = 需求条目数
    matrix = json.loads((ws.workspace.root / "交接" / "需求追踪矩阵.json").read_text(encoding="utf-8"))
    assert len(matrix) == 1  # 只有 1-1


@pytest.mark.asyncio
async def test_g1_check(ws_full):
    """G1 门检：合法计划通过、缺叙事主线不通过。"""
    root = ws_full.workspace.root
    (root / "交接" / "路线侦察.json").write_text(
        json.dumps({"问题清单": [{"编号": 1, "路线": [
            {"路线名": "路线A", "方法": "最小二乘拟合"},
            {"路线名": "路线B", "方法": "稳健拟合"},
        ]}], "最难问题编号": 1}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "交接" / "原型结果.json").write_text(
        json.dumps({"条目": [
            {"问题编号": 1, "路线名": "路线A", "脚本": "求解/问题1/原型_1.py", "rc": 0},
            {"问题编号": 1, "路线名": "路线B", "脚本": "求解/问题1/原型_2.py", "rc": 0},
        ]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "交接" / "计划.json").write_text(PLAN_JSON, encoding="utf-8")
    ok, issues = check_g1(root, profile="快速")
    assert ok, issues
    # 缺叙事主线
    bad = json.loads(PLAN_JSON)
    del bad["叙事主线"]
    (root / "交接" / "计划.json").write_text(json.dumps(bad), encoding="utf-8")
    ok, issues = check_g1(root, profile="快速")
    assert not ok
    assert any("叙事主线" in i for i in issues)
    # 缺依赖问题
    bad2 = json.loads(PLAN_JSON)
    del bad2["问题清单"][0]["依赖问题"]
    (root / "交接" / "计划.json").write_text(json.dumps(bad2), encoding="utf-8")
    ok, issues = check_g1(root, profile="快速")
    assert not ok
    assert any("依赖" in i for i in issues)
