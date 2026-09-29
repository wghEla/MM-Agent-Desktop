"""Shared role-leg executor with node-level resume semantics."""
from __future__ import annotations

from mmagent.agent.loop import AgentLoop, AgentTask
from mmagent.mm.roles.prompts import get_system_prompt
from mmagent.mm.roles.registry import get_role
from mmagent.orchestration.budget import check_run_budget
from mmagent.orchestration.resume import prepare_node_task
from mmagent.orchestration.wave import WaveJob, run_status_wave, wave_active
from mmagent.providers.base import BaseProvider
from mmagent.state.db import Database
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy
from mmagent.workspace.permissions import PermissionChecker


async def _run_role_leg_once(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    *,
    stage_key: str,
    role_id: str,
    node_key: str,
    instructions: str,
    expected_artifacts: list[ExpectedArtifact],
    question_num: int | None = None,
    image_paths: list[str] | None = None,
    cancel=None,
) -> str:
    """Run or safely reuse one deterministic paper-foundry role node."""
    role = get_role(role_id)
    permission_vars = (
        {"question": str(question_num)} if question_num is not None else {}
    )
    checker = PermissionChecker(role.permissions(**permission_vars), policy)

    prepared = prepare_node_task(
        db,
        policy,
        run_id=run_id,
        stage_key=stage_key,
        node_key=node_key,
        role_id=role_id,
        expected_artifacts=expected_artifacts,
    )
    if prepared.reused:
        return "SUCCEEDED"

    # Budget applies only when this call will actually execute a new/retried leg;
    # reused sealed nodes consume no new model/tool budget.
    check_run_budget(db, run_id)

    loop = AgentLoop(db, provider, registry, checker, policy, cancel=cancel)
    outcome = await loop.run(
        AgentTask(
            task_id=prepared.task.id,
            node_key=node_key,
            role_id=role_id,
            system_prompt=get_system_prompt(role_id),
            instructions=instructions,
            model="mock",
            reasoning=role.reasoning,
            expected_artifacts=expected_artifacts,
            image_paths=list(image_paths or []),
        )
    )
    return outcome.status.value


async def run_role_leg(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    *,
    stage_key: str,
    role_id: str,
    node_key: str,
    instructions: str,
    expected_artifacts: list[ExpectedArtifact],
    question_num: int | None = None,
    image_paths: list[str] | None = None,
    cancel=None,
) -> str:
    """Run one role node with the pinned one-retry/adaptive-wave semantics.

    An outer multi-leg wave owns retry/concurrency when one is already active.
    Otherwise a direct role leg is treated as a one-job wave, so provider 429
    and ordinary leg failure receive the same single retry and durable 4→2
    concurrency feedback as batched lanes.
    """
    if wave_active():
        return await _run_role_leg_once(
            db,
            provider,
            registry,
            policy,
            run_id,
            stage_key=stage_key,
            role_id=role_id,
            node_key=node_key,
            instructions=instructions,
            expected_artifacts=expected_artifacts,
            question_num=question_num,
            image_paths=image_paths,
            cancel=cancel,
        )

    async def attempt() -> str:
        return await _run_role_leg_once(
            db,
            provider,
            registry,
            policy,
            run_id,
            stage_key=stage_key,
            role_id=role_id,
            node_key=node_key,
            instructions=instructions,
            expected_artifacts=expected_artifacts,
            question_num=question_num,
            image_paths=image_paths,
            cancel=cancel,
        )

    wave = await run_status_wave(
        db,
        run_id,
        [WaveJob(node_key, attempt)],
        cancel=cancel,
        wave_key=f"{stage_key}:{node_key}",
    )
    return wave.results.get(node_key, "FAILED")
