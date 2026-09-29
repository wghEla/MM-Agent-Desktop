"""S0/G0/S1 流水线节点执行器（编排层，mock provider 级）。

S0 流程：Reader(读题官) → AnswerPredictor(答卷预测官) → 机械生成需求追踪矩阵 → G0 门检。
S1 流程：Planner(规划师) → G1 门检（计划完整性机械判据）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmagent.mm.contracts.s0_contracts import DataArchive, ProblemContract
from mmagent.orchestration.role_leg import run_role_leg
from mmagent.providers.base import BaseProvider
from mmagent.state.db import Database
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy


async def run_s0(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    *,
    cancel=None,
) -> dict[str, Any]:
    """执行 S0：读题官 → 答卷预测官 → 机械生成需求追踪矩阵。

    返回 {"g0_pass": bool, "g0_issues": [...], "tasks": [...]}。
    """
    tasks: list[dict] = []
    for role_id, node_key, instructions, expected in _s0_specs():
        status = await run_role_leg(
            db, provider, registry, policy, run_id,
            stage_key="S0",
            role_id=role_id,
            node_key=node_key,
            instructions=instructions,
            expected_artifacts=expected,
            cancel=cancel,
        )
        tasks.append({"node": node_key, "status": status, "error": None})
        if status != "SUCCEEDED":
            return {
                "g0_pass": False,
                "g0_issues": [f"{node_key} 未成功"],
                "tasks": tasks,
            }

    # 机械生成需求追踪矩阵
    await _generate_requirement_matrix(db, policy, run_id, registry, cancel)
    tasks.append({"node": "S0.4:矩阵", "status": "SUCCEEDED"})

    # G0 门检
    from mmagent.mm.gates.g0 import check_g0
    ok, issues = check_g0(policy.root)
    return {"g0_pass": ok, "g0_issues": issues, "tasks": tasks}


def _canonical_json_schema_instruction(
    rel_path: str,
    model: type[ProblemContract] | type[DataArchive],
) -> str:
    """Render the contract authority into the model instruction without copying a schema.

    The Pydantic contract remains the single source of truth; this is only a prompt-time
    projection of that same object so real providers see the exact Chinese field names
    before artifact verification.
    """
    schema = json.dumps(
        model.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"\n{rel_path} 必须写成纯 JSON（不要 Markdown 代码围栏），字段名必须严格遵循"
        f" Runtime 合同；canonical JSON Schema={schema}"
    )


def _s0_specs() -> list[tuple[str, str, str, list[ExpectedArtifact]]]:
    reader_instructions = (
        "读取 输入/题目/ 下的题目文件与 输入/数据/ 下的附件清单。"
        "产出 交接/题面契约.json 和 交接/数据档案.json。"
        "不得把中文合同字段翻译成英文，也不得自造同义顶层键；"
        "例如题面契约的赛题字段必须写作“赛题”，不是“题目”或 contest。"
        + _canonical_json_schema_instruction("交接/题面契约.json", ProblemContract)
        + _canonical_json_schema_instruction("交接/数据档案.json", DataArchive)
    )
    return [
        (
            "reader",
            "S0.2:读题",
            reader_instructions,
            [
                ExpectedArtifact(
                    rel_path="交接/题面契约.json",
                    schema_model=ProblemContract,
                ),
                ExpectedArtifact(
                    rel_path="交接/数据档案.json",
                    schema_model=DataArchive,
                ),
            ],
        ),
        (
            "answer_predictor",
            "S0.3:预测",
            "读取 交接/题面契约.json 和 交接/数据档案.json。"
            "产出 交接/典型答卷预测.md。",
            [ExpectedArtifact(rel_path="交接/典型答卷预测.md", kind="text")],
        ),
    ]


async def _generate_requirement_matrix(
    db: Database, policy: PathPolicy, run_id: str, registry: ToolRegistry, cancel=None
) -> None:
    """机械生成需求追踪矩阵（从题面契约提取，不由模型生成）。"""
    contract_path = policy.root / "交接" / "题面契约.json"
    if not contract_path.is_file():
        return
    raw = json.loads(contract_path.read_text(encoding="utf-8"))
    matrix: list[dict[str, Any]] = []
    for prob in raw.get("问题", []):
        num = prob.get("编号", 0)
        for req in prob.get("需求条目", []):
            matrix.append({
                "需求号": req.get("需求号", ""),
                "问题编号": num,
                "内容": req.get("内容", ""),
                "状态": "未落位",
                "章节": "",
                "图表": "",
                "关键数字": "",
            })
    matrix_path = policy.root / "交接" / "需求追踪矩阵.json"
    matrix_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- G1 compatibility wrappers
def check_g1(workspace_root: Path, *, profile: str = "标准") -> tuple[bool, list[str]]:
    from mmagent.mm.gates.g1 import check_g1 as _check
    return _check(workspace_root, profile=profile)


async def run_s1(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    *,
    profile: str = "标准",
    cancel=None,
) -> dict[str, Any]:
    from mmagent.mm.pipeline.s1_tournament import run_s1 as _run
    return await _run(
        db, provider, registry, policy, run_id, profile=profile, cancel=cancel
    )
