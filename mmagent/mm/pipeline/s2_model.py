"""S2 modelling/verification pipeline with driver-executed solver and red-team scripts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmagent.mm.config.thresholds import DEFAULT_THRESHOLDS
from mmagent.mm.gates.g2 import check_g2, normalize_red_team_report
from mmagent.orchestration.dag import build_dependency_graph, topological_layers
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

_MAX_REWORK = DEFAULT_THRESHOLDS.gate_max_rework
_ESCALATION_VARIANTS = DEFAULT_THRESHOLDS.escalation_variants


async def _agent_leg(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    *,
    role_id: str,
    node_key: str,
    instructions: str,
    expected: list[ExpectedArtifact],
    question_num: int,
    cancel=None,
) -> str:
    return await run_role_leg(
        db, provider, registry, policy, run_id,
        stage_key="S2",
        role_id=role_id,
        node_key=node_key,
        instructions=instructions,
        expected_artifacts=expected,
        question_num=question_num,
        cancel=cancel,
    )

async def _run_script(
    registry: ToolRegistry,
    policy: PathPolicy,
    rel_path: str,
    *,
    cancel=None,
) -> tuple[bool, str]:
    """Execute an agent-authored script through a trusted driver boundary."""
    if not registry.has("python.run"):
        return False, "ToolRegistry 缺 python.run"
    perms = RolePermissions(
        role_id="s2_driver_executor",
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
    result = await registry.invoke("python.run", {"path": rel_path, "timeout_s": 1200}, ctx)
    return result.ok, result.error or result.content[-1000:]


async def _model_and_interpret(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    q: int,
    *,
    attempt_key: str,
    rework: bool = False,
    cancel=None,
) -> tuple[bool, str]:
    solver = f"求解/问题{q}/求解_问题{q}.py"
    model_status = await _agent_leg(
        db, provider, registry, policy, run_id,
        role_id="modeler",
        node_key=f"S2:问{q}:{'返工建模' if rework else '建模'}:{attempt_key}",
        question_num=q,
        instructions=(
            f"{'按返工证据修正方法或实现；' if rework else ''}"
            f"只编写 {solver} 与必要的建模记录，不自行执行脚本。"
            "脚本必须把机器可读结果写入本问 求解/问题N/结果/ 下。"
        ),
        expected=[ExpectedArtifact(rel_path=solver, kind="text")],
        cancel=cancel,
    )
    if model_status != "SUCCEEDED":
        return False, "建模腿失败"
    ran, detail = await _run_script(registry, policy, solver, cancel=cancel)
    if not ran:
        return False, f"求解脚本执行失败: {detail}"

    interpretation = await _agent_leg(
        db, provider, registry, policy, run_id,
        role_id="interpreter",
        node_key=f"S2:问{q}:结果解读:{attempt_key}",
        question_num=q,
        instructions=(
            f"读取问题{q}真实求解结果，写 交接/结果声明_问题{q}.json 与 "
            f"交接/结果解读_问题{q}.md。结果声明的核心指标必须给出题目要求的最佳数值估计。"
        ),
        expected=[
            ExpectedArtifact(rel_path=f"交接/结果声明_问题{q}.json"),
            ExpectedArtifact(rel_path=f"交接/结果解读_问题{q}.md", kind="text"),
        ],
        cancel=cancel,
    )
    return (
        interpretation == "SUCCEEDED",
        "" if interpretation == "SUCCEEDED" else "解读腿失败",
    )


async def _red_team_cycle(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    q: int,
    *,
    cycle_key: str,
    cancel=None,
) -> tuple[bool, str]:
    script = f"求解/问题{q}/复算.py"
    author = await _agent_leg(
        db, provider, registry, policy, run_id,
        role_id="red_team",
        node_key=f"S2:问{q}:红队脚本:{cycle_key}",
        question_num=q,
        instructions=(
            f"独立为问题{q}编写 {script}；禁止读建模师代码/笔记/解读。"
            f"只写脚本，不自行执行；脚本把复算结果写入 求解/问题{q}/红队结果/。"
        ),
        expected=[ExpectedArtifact(rel_path=script, kind="text")],
        cancel=cancel,
    )
    if author != "SUCCEEDED":
        return False, "红队脚本腿失败"
    ran, detail = await _run_script(registry, policy, script, cancel=cancel)
    if not ran:
        return False, f"红队复算脚本执行失败: {detail}"

    report = await _agent_leg(
        db, provider, registry, policy, run_id,
        role_id="red_team",
        node_key=f"S2:问{q}:红队报告:{cycle_key}",
        question_num=q,
        instructions=(
            f"读取自己的复算结果与 交接/结果声明_问题{q}.json，先做口径对照再比较数值；"
            f"写 交接/红队_问题{q}.json，结论只能是 对齐 或 不齐。"
        ),
        expected=[ExpectedArtifact(rel_path=f"交接/红队_问题{q}.json")],
        cancel=cancel,
    )
    if report != "SUCCEEDED":
        return False, "红队报告腿失败"
    passed, mechanical_issues = normalize_red_team_report(policy.root, q)
    detail = "" if passed else "红队机械复核不齐"
    if mechanical_issues:
        detail += ": " + "; ".join(mechanical_issues)
    # A numeric mismatch is a valid red-team finding, not a leg execution failure.
    # Return success here so the caller can arbitrate based on normalized 结论.
    return True, detail


def _red_conclusion(policy: PathPolicy, q: int) -> str:
    try:
        data = json.loads(
            (policy.root / "交接" / f"红队_问题{q}.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("结论", "")) if isinstance(data, dict) else ""


async def _arbitrate(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    q: int,
    *,
    cycle_key: str,
    cancel=None,
) -> bool:
    status = await _agent_leg(
        db, provider, registry, policy, run_id,
        role_id="interpreter",
        node_key=f"S2:问{q}:仲裁:{cycle_key}",
        question_num=q,
        instructions=(
            f"红队结论不齐。先核对四类口径，再逐项定责；写 交接/仲裁_问题{q}.json。"
            "应改方=建模 的条目必须保持待处理，直到建模返工后有消解证据；纯口径差可已解释。"
        ),
        expected=[ExpectedArtifact(rel_path=f"交接/仲裁_问题{q}.json")],
        cancel=cancel,
    )
    return status == "SUCCEEDED"


async def _review_arbitration_after_rework(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    q: int,
    *,
    attempt_key: str,
    cancel=None,
) -> bool:
    """Re-adjudicate old model-side arbitration items after fresh recomputation.

    A previous arbitration carrier is part of G2 truth.  It must not stay
    permanently "待处理" after the model has been reworked and the red-team
    mechanical check has been refreshed.
    """
    arb = policy.root / "交接" / f"仲裁_问题{q}.json"
    if not arb.is_file():
        return True
    status = await _agent_leg(
        db, provider, registry, policy, run_id,
        role_id="interpreter",
        node_key=f"S2:问{q}:仲裁复核:{attempt_key}",
        question_num=q,
        instructions=(
            f"这是问题{q}返工后的仲裁复核。读取当前 交接/仲裁_问题{q}.json、"
            f"交接/结果声明_问题{q}.json 与 交接/红队_问题{q}.json。"
            "逐条复核旧仲裁项：只有有新证据的条目才能改为 已消解/已解释；"
            "没有证据的保持待处理。直接更新原仲裁文件，并为已消解项写复核证据。"
        ),
        expected=[ExpectedArtifact(rel_path=f"交接/仲裁_问题{q}.json")],
        cancel=cancel,
    )
    return status == "SUCCEEDED"


async def _normal_attempt(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    q: int,
    *,
    attempt_key: str,
    rework: bool = False,
    cancel=None,
) -> tuple[bool, list[str]]:
    ok, detail = await _model_and_interpret(
        db, provider, registry, policy, run_id, q,
        attempt_key=attempt_key, rework=rework, cancel=cancel
    )
    if not ok:
        return False, [detail]
    ok, detail = await _red_team_cycle(
        db, provider, registry, policy, run_id, q,
        cycle_key=attempt_key, cancel=cancel
    )
    if not ok:
        return False, [detail]
    if _red_conclusion(policy, q) == "不齐":
        if not await _arbitrate(
            db, provider, registry, policy, run_id, q,
            cycle_key=attempt_key, cancel=cancel
        ):
            return False, ["仲裁腿失败"]
    elif rework:
        if not await _review_arbitration_after_rework(
            db, provider, registry, policy, run_id, q,
            attempt_key=attempt_key, cancel=cancel
        ):
            return False, ["仲裁复核腿失败"]
    return check_g2(policy.root, q)


async def _run_escalation(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    q: int,
    *,
    cancel=None,
) -> tuple[bool, list[str]]:
    """Three independent alternative scripts -> adjudication -> red-team recheck."""
    variant_specs: list[tuple[int, str]] = []
    variant_jobs: list[WaveJob[str]] = []
    for idx in range(1, _ESCALATION_VARIANTS + 1):
        rel = f"求解/问题{q}/升格/变体{idx}/求解.py"
        variant_specs.append((idx, rel))

        async def write_variant(*, variant_idx=idx, rel_path=rel) -> str:
            return await _agent_leg(
                db, provider, registry, policy, run_id,
                role_id="modeler",
                node_key=f"S2:问{q}:升格变体{variant_idx}",
                question_num=q,
                instructions=(
                    f"使用与当前失败路线实质不同的方法，为问题{q}编写升格变体 "
                    f"{rel_path}；只写不跑。"
                    f"结果写到 求解/问题{q}/升格/变体{variant_idx}/结果/。"
                ),
                expected=[ExpectedArtifact(rel_path=rel_path, kind="text")],
                cancel=cancel,
            )

        variant_jobs.append(WaveJob(f"变体{idx}", write_variant))

    wave = await run_status_wave(
        db,
        run_id,
        variant_jobs,
        cancel=cancel,
        wave_key=f"S2:问{q}:升格变体",
        serial=provider.protocol == "mock",
    )
    variants: list[str] = []
    for idx, rel in variant_specs:
        if wave.results.get(f"变体{idx}") != "SUCCEEDED":
            continue
        ran, _ = await _run_script(registry, policy, rel, cancel=cancel)
        if ran:
            variants.append(rel)
    if not variants:
        return False, ["升格蜂群没有可执行变体"]

    adjudication = await _agent_leg(
        db, provider, registry, policy, run_id,
        role_id="interpreter",
        node_key=f"S2:问{q}:升格裁决",
        question_num=q,
        instructions=(
            f"比较问题{q}的升格变体真实结果 {json.dumps(variants, ensure_ascii=False)}，"
            f"选择证据最充分的方案并刷新 交接/结果声明_问题{q}.json；"
            f"写 交接/升格裁决_问题{q}.json。"
        ),
        expected=[
            ExpectedArtifact(rel_path=f"交接/结果声明_问题{q}.json"),
            ExpectedArtifact(rel_path=f"交接/升格裁决_问题{q}.json"),
        ],
        cancel=cancel,
    )
    if adjudication != "SUCCEEDED":
        return False, ["升格裁决失败"]
    ok, detail = await _red_team_cycle(
        db, provider, registry, policy, run_id, q,
        cycle_key="升格复核", cancel=cancel
    )
    if not ok:
        return False, [detail]
    if _red_conclusion(policy, q) == "不齐":
        await _arbitrate(
            db, provider, registry, policy, run_id, q,
            cycle_key="升格复核", cancel=cancel
        )
    return check_g2(policy.root, q)


def _record_degraded_release(policy: PathPolicy, q: int, issues: list[str]) -> None:
    path = policy.root / "交接" / "降级放行.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except json.JSONDecodeError:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    rows = raw.setdefault("问题", [])
    if not isinstance(rows, list):
        rows = []
        raw["问题"] = rows
    rows.append({"问题编号": q, "issues": issues})
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_s2(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    plan_path: Path,
    *,
    cancel=None,
) -> dict[str, Any]:
    """Execute S2 by topological question layers.

    Current implementation executes questions within a layer sequentially; the
    layer structure is preserved so a scheduler can parallelize it later without
    changing correctness semantics.
    """
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    problem_list = plan.get("问题清单", [])
    graph = build_dependency_graph(problem_list)
    layers = topological_layers(graph)
    results: dict[str, Any] = {"layers": layers, "gates": {}, "downgraded": []}

    for layer in layers:
        for q in layer:
            ok, issues = await _normal_attempt(
                db, provider, registry, policy, run_id, q,
                attempt_key="初验", cancel=cancel
            )
            if not ok:
                for rework_index in range(1, _MAX_REWORK + 1):
                    ok, issues = await _normal_attempt(
                        db, provider, registry, policy, run_id, q,
                        attempt_key=f"返工{rework_index}",
                        rework=True, cancel=cancel,
                    )
                    if ok:
                        break
            if not ok:
                ok, issues = await _run_escalation(
                    db, provider, registry, policy, run_id, q, cancel=cancel
                )
            if not ok:
                _record_degraded_release(policy, q, issues)
                results["downgraded"].append(q)
            results["gates"][f"问{q}"] = {
                "pass": ok,
                "issues": issues,
                "downgraded": not ok,
            }
    return results
