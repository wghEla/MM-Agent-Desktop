"""R38 守卫回退协议：改前快照 → 修改腿 → 结构守卫 → 违规整份回退。

Upstream semantics (施工日志 R38/R68): repair legs on the paper get a
before-snapshot; after the leg the structure guard runs.  Any violation
(\\input 集减少、空章、附录源码清单减少、正文插图减少) rolls the whole
paper back to the snapshot, keeps the rejected draft under
审稿/回退稿/<node>/, and fails the leg so no repair receipt is honored.
"""
from __future__ import annotations

from pathlib import Path

from mmagent.mm.guards.guards import structure_guard
from mmagent.orchestration.role_leg import run_role_leg
from mmagent.providers.base import BaseProvider
from mmagent.state import events
from mmagent.state.db import Database
from mmagent.tools.registry import ToolRegistry
from mmagent.workspace.artifacts import ExpectedArtifact
from mmagent.workspace.path_policy import PathPolicy


def _snapshot_tex(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for p in sorted(root.glob("论文/**/*.tex")):
        rel = p.relative_to(root).as_posix()
        try:
            files[rel] = p.read_text(encoding="utf-8")
        except OSError:
            continue
    return files


def _restore_tex(root: Path, files: dict[str, str]) -> None:
    current = {p.relative_to(root).as_posix() for p in root.glob("论文/**/*.tex")}
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    for rel in current - set(files):
        (root / rel).unlink(missing_ok=True)


async def guarded_text_repair(
    db: Database,
    provider: BaseProvider,
    registry: ToolRegistry,
    policy: PathPolicy,
    run_id: str,
    *,
    stage_key: str,
    node_key: str,
    instructions: str,
    receipt_rel: str,
    question_num: int | None = None,
    附录集: set[str] | None = None,
    cancel=None,
) -> tuple[str, list[str]]:
    """Run a paper-repair leg behind the R38 structure-guard rollback.

    Returns (status, guard_issues).  status "REVERTED" means the leg claimed
    success but the guard rolled the paper back; callers must treat it as a
    failed repair and must not accept its receipts.
    """
    before = _snapshot_tex(policy.root)
    status = await run_role_leg(
        db, provider, registry, policy, run_id,
        stage_key=stage_key,
        role_id="writer",
        node_key=node_key,
        question_num=question_num,
        instructions=instructions,
        expected_artifacts=[ExpectedArtifact(rel_path=receipt_rel)],
        cancel=cancel,
    )
    guard_issues: list[str] = []
    if status == "SUCCEEDED":
        after = _snapshot_tex(policy.root)
        _, guard_issues = structure_guard(before, after, 附录集=附录集)
        if guard_issues:
            backup_dir = policy.root / "审稿" / "回退稿" / node_key.replace(":", "_")
            backup_dir.mkdir(parents=True, exist_ok=True)
            for rel, content in after.items():
                target = backup_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                (backup_dir / rel).write_text(content, encoding="utf-8")
            _restore_tex(policy.root, before)
            events.append_event(
                db,
                "guard.structure_revert",
                {"node": node_key, "issues": guard_issues,
                 "kept_files": sorted(after)},
                run_id=run_id,
            )
            status = "REVERTED"
    return status, guard_issues
