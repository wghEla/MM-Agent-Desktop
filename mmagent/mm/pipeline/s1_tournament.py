"""S1 strategic tournament: scout -> real prototypes -> evidence -> final plan."""
from __future__ import annotations

from typing import Any

from mmagent.mm.config.profiles import get_profile
from mmagent.mm.contracts.s1_contracts import PrototypeResults, RouteScout
from mmagent.mm.gates.g1 import check_g1
from mmagent.orchestration.role_leg import run_role_leg
from mmagent.orchestration.wave import WaveJob, run_status_wave
from mmagent.providers.base import BaseProvider
from mmagent.runtime.cancellation import CancellationToken
from mmagent.state.db import Database
from mmagent.tools.registry import ToolRegistry
from mmagent.tools.tool_protocol import ToolContext
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy
from mmagent.workspace.permissions import PermissionChecker, RolePermissions


async def _leg(
    db, provider, registry, policy, run_id, *,
    role_id, node, instructions, expected, question=None, cancel=None,
):
    return await run_role_leg(
        db, provider, registry, policy, run_id,
        stage_key="S1",
        role_id=role_id,
        node_key=node,
        instructions=instructions,
        expected_artifacts=expected,
        question_num=question,
        cancel=cancel,
    )


async def _execute(registry: ToolRegistry, policy: PathPolicy, rel: str, *, cancel=None):
    if not registry.has("python.run"):
        return {"rc": -1, "stdout_tail": "", "stderr_tail": "python.run missing"}
    perms = RolePermissions(
        role_id="s1_prototype_executor",
        read_scopes=("求解/**", "输入/**", "交接/**"),
        write_scopes=("求解/**",),
        allowed_tools=frozenset({"python.run"}),
        host_code=True,
    )
    ctx = ToolContext(
        policy=policy,
        permission=PermissionChecker(perms, policy),
        cancel=cancel or CancellationToken(),
    )
    result = await registry.invoke(
        "python.run", {"path": rel, "timeout_s": 600}, ctx
    )
    return {
        "rc": int(
            result.meta.get("rc")
            if result.meta.get("rc") is not None
            else (-1 if not result.ok else 0)
        ),
        "stdout_tail": str(result.meta.get("stdout_tail", "")),
        "stderr_tail": str(result.meta.get("stderr_tail", result.error or "")),
    }


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
    cfg = get_profile(profile)
    scout_status = await _leg(
        db, provider, registry, policy, run_id,
        role_id="planner", node="S1:路线侦察",
        instructions=(
            f"读取题面契约、数据档案和典型答卷预测，写 交接/路线侦察.json。"
            f"每个参加锦标赛的问题提出 {cfg.每问路线数} 条可真跑小样的候选路线；"
            "顶层写 最难问题编号；快速档只让该问题跑完整锦标赛，其余问题至少给一条基准路线。"
            "格式为 问题清单:[{编号, 路线:[{路线名,方法,方法理由,原型目标}]}]。"
        ),
        expected=[ExpectedArtifact(rel_path="交接/路线侦察.json")],
        cancel=cancel,
    )
    if scout_status != "SUCCEEDED":
        return {"g1_pass": False, "g1_issues": ["路线侦察腿失败"]}
    try:
        scout = RouteScout.model_validate_json(
            (policy.root / "交接" / "路线侦察.json").read_text(encoding="utf-8")
        )
    except Exception as exc:
        return {"g1_pass": False, "g1_issues": [f"路线侦察 schema 错误: {exc}"]}

    evidence: list[dict[str, Any]] = []
    questions = scout.问题清单
    if not cfg.全问开锦标赛 and questions:
        hardest = scout.最难问题编号
        if hardest is None or hardest not in {q.编号 for q in questions}:
            hardest = max(questions, key=lambda x: len(x.路线)).编号
        tournament_ids = {hardest}
    else:
        tournament_ids = {x.编号 for x in questions}

    prototype_specs: list[dict[str, Any]] = []
    prototype_jobs: list[WaveJob[str]] = []
    for question in questions:
        routes = question.路线[: cfg.每问路线数]
        if question.编号 not in tournament_ids:
            routes = routes[:1]
        for index, route in enumerate(routes, 1):
            rel = f"求解/问题{question.编号}/原型_{index}.py"
            name = f"问{question.编号}:原型{index}"
            prototype_specs.append({
                "name": name,
                "question": question.编号,
                "route_name": route.路线名,
                "method": route.方法,
                "rel": rel,
                "index": index,
            })

            async def write_prototype(
                *,
                question_num=question.编号,
                route_name=route.路线名,
                method=route.方法,
                rel_path=rel,
                prototype_index=index,
            ) -> str:
                return await _leg(
                    db, provider, registry, policy, run_id,
                    role_id="modeler",
                    node=f"S1:问{question_num}:原型{prototype_index}",
                    question=question_num,
                    instructions=(
                        f"为候选路线 {route_name}（{method}）只编写小样原型 "
                        f"{rel_path}，不自行执行。"
                        "原型应快速验证方法可行性并打印关键诊断，不写最终大求解。"
                    ),
                    expected=[ExpectedArtifact(rel_path=rel_path, kind="text")],
                    cancel=cancel,
                )

            prototype_jobs.append(WaveJob(name, write_prototype))

    prototype_wave = await run_status_wave(
        db,
        run_id,
        prototype_jobs,
        cancel=cancel,
        wave_key="S1:原型编写",
        serial=provider.protocol == "mock",
    )
    for spec in prototype_specs:
        status = prototype_wave.results.get(spec["name"], "FAILED")
        if status != "SUCCEEDED":
            evidence.append({
                "问题编号": spec["question"],
                "路线名": spec["route_name"],
                "脚本": spec["rel"],
                "rc": -1,
            })
            continue
        result = await _execute(registry, policy, spec["rel"], cancel=cancel)
        evidence.append({
            "问题编号": spec["question"],
            "路线名": spec["route_name"],
            "脚本": spec["rel"],
            "rc": result["rc"],
            "stdout_tail": result["stdout_tail"],
            "stderr_tail": result["stderr_tail"],
        })

    proto = PrototypeResults.model_validate({"条目": evidence})
    (policy.root / "交接" / "原型结果.json").write_text(
        proto.model_dump_json(indent=2), encoding="utf-8"
    )

    final_status = await _leg(
        db, provider, registry, policy, run_id,
        role_id="planner", node="S1:裁决定稿",
        instructions=(
            "读取 交接/路线侦察.json 与 交接/原型结果.json；只基于实际原型证据裁决路线，"
            "写 交接/计划.json。每问的 锦标赛 必须含 参赛路线、优胜、依据，"
            "优胜名称必须对应路线名。"
        ),
        expected=[ExpectedArtifact(rel_path="交接/计划.json")],
        cancel=cancel,
    )
    if final_status != "SUCCEEDED":
        return {
            "g1_pass": False,
            "g1_issues": ["规划裁决定稿失败"],
            "prototype_results": evidence,
        }
    ok, issues = check_g1(policy.root, profile=profile)
    return {"g1_pass": ok, "g1_issues": issues, "prototype_results": evidence}
