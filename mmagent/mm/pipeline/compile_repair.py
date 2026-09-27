"""Bounded compile-repair protocol (fidelity E8).

Upstream semantics: a failed XeLaTeX compile is not an immediate abort —
the Runtime hands the log errors to a writer leg (which may only edit
论文/*.tex), requires a repair receipt, recompiles, and only after the
bounded attempts are exhausted does the stage fail closed.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from mmagent.mm.pipeline.compile_runtime import run_compile
from mmagent.mm.pipeline.guarded_repair import guarded_text_repair
from mmagent.providers.base import BaseProvider
from mmagent.state import events
from mmagent.state.db import Database
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy

CompileFn = Callable[..., dict[str, Any]]

_MAX_ERROR_LINES = 20


def _failed(result: dict[str, Any]) -> bool:
    return result.get("rc") not in (0, None) or bool(result.get("errors"))


async def run_compile_repair(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    compiler: CompileFn,
    *,
    stage_key: str = "S4",
    max_attempts: int = 2,
    cancel=None,
) -> dict[str, Any]:
    """Compile with a bounded writer-repair loop.

    Each attempt: writer leg receives the failing log lines and MUST write a
    repair receipt (artifact gate), then the paper is recompiled.  A failed
    leg ends the loop immediately — the last compile result is returned and
    the caller fails closed as before.
    """
    result = await run_compile(compiler, policy.root, cancel=cancel)
    for attempt in range(1, max_attempts + 1):
        if not _failed(result):
            return result
        errors = [str(x) for x in (result.get("errors") or [])][:_MAX_ERROR_LINES]
        safe_stage = "".join(ch if ch.isalnum() else "_" for ch in stage_key)
        receipt_rel = f"审稿/回执_编译修复_{safe_stage}_{attempt}.json"
        status, guard_issues = await guarded_text_repair(
            db, provider, registry, policy, run_id,
            stage_key=stage_key,
            node_key=f"{stage_key}:编译修复{attempt}",
            instructions=(
                f"编译失败（第{attempt}次修复机会）。根据以下 XeLaTeX 错误修复 论文/*.tex，"
                "不许删除 \\cite，不许整章移附录，不许改动求解事实：\n"
                + json.dumps(errors, ensure_ascii=False)
                + f"\n完成后写 {receipt_rel} 说明改动。"
            ),
            receipt_rel=receipt_rel,
            cancel=cancel,
        )
        events.append_event(
            db,
            "compile.repair_attempt",
            {
                "attempt": attempt,
                "stage": stage_key,
                "status": status,
                "errors": errors[:5],
                "guard_issues": guard_issues,
            },
            run_id=run_id,
        )
        if status != "SUCCEEDED":
            break
        result = await run_compile(compiler, policy.root, cancel=cancel)
    return result
