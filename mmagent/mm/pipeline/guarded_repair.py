"""R38 守卫回退协议：改前快照 → 修改腿 → 结构守卫 → 违规整份回退。

Upstream semantics (施工日志 R38/R68): repair legs on the paper get a
before-snapshot; after the leg the structure guard runs.  Any violation
(\\input 集减少、空章、附录源码清单减少、正文插图减少) rolls the whole
paper back to the snapshot, keeps the rejected draft under
审稿/回退稿/<node>/, and fails the leg so no repair receipt is honored.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mmagent.mm.guards.guards import change_guard, structure_guard
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


def _guard_snapshot_path(root: Path, node_key: str) -> Path:
    digest = hashlib.sha256(node_key.encode("utf-8")).hexdigest()[:20]
    return root / ".mmagent" / "guard_snapshots" / f"{digest}.json"


def _load_or_create_guard_snapshot(root: Path, node_key: str) -> tuple[Path, dict[str, str]]:
    """Persist the pre-repair baseline so a crash cannot erase guard truth."""
    path = _guard_snapshot_path(root, node_key)
    if path.is_file():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, dict)
            or raw.get("node_key") != node_key
            or not isinstance(raw.get("files"), dict)
            or not all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in raw["files"].items()
            )
        ):
            raise RuntimeError(f"invalid guard snapshot for {node_key}")
        return path, dict(raw["files"])

    files = _snapshot_tex(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"node_key": node_key, "files": files}, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)
    return path, files


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
    receipt_schema=None,
    role_id: str = "writer",
    review_items: list[dict] | None = None,
    change_limit: float = 0.45,
    question_num: int | None = None,
    附录集: set[str] | None = None,
    cancel=None,
) -> tuple[str, list[str]]:
    """Run a paper-repair leg behind the R38 structure-guard rollback.

    Returns (status, guard_issues).  status "REVERTED" means the leg claimed
    success but the guard rolled the paper back; callers must treat it as a
    failed repair and must not accept its receipts.
    """
    snapshot_path, before = _load_or_create_guard_snapshot(policy.root, node_key)
    status = await run_role_leg(
        db, provider, registry, policy, run_id,
        stage_key=stage_key,
        role_id=role_id,
        node_key=node_key,
        question_num=question_num,
        instructions=instructions,
        expected_artifacts=[
            ExpectedArtifact(rel_path=receipt_rel, schema_model=receipt_schema)
        ],
        cancel=cancel,
    )
    after = _snapshot_tex(policy.root)
    _, structure_issues = structure_guard(before, after, 附录集=附录集)

    def body_text(files: dict[str, str]) -> str:
        chunks: list[str] = []
        for rel, content in sorted(files.items()):
            if any(key in rel for key in ("源码", "代码", "摘要候选_")):
                continue
            chunks.append(content)
        return "\n".join(chunks)

    change_ok, change_ratio, change_detail = change_guard(
        body_text(before),
        body_text(after),
        list(review_items or []),
        上限=change_limit,
    )
    guard_issues = list(structure_issues)
    if not change_ok:
        guard_issues.append(
            f"Change Guard 超限: ratio={change_ratio:.3f} > {change_limit:.3f}; "
            f"detail={json.dumps(change_detail, ensure_ascii=False)}"
        )

    # A failed agent leg is not allowed to leave partial file mutations behind,
    # even if those mutations happen to satisfy the structural guard.
    must_revert = status != "SUCCEEDED" or bool(guard_issues)
    if must_revert:
        backup_dir = policy.root / "审稿" / "回退稿" / node_key.replace(":", "_")
        backup_dir.mkdir(parents=True, exist_ok=True)
        for rel, content in after.items():
            target = backup_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        _restore_tex(policy.root, before)

        # A reverted/failed repair must never leave a receipt behind.
        # Otherwise a later retry could satisfy artifact verification with
        # stale evidence from the rejected attempt.
        (policy.root / receipt_rel).unlink(missing_ok=True)
        if status == "SUCCEEDED":
            status = "REVERTED"

        events.append_event(
            db,
            "guard.repair_revert",
            {
                "node": node_key,
                "issues": guard_issues,
                "leg_status": status,
                "change_limit": change_limit,
                "kept_files": sorted(after),
            },
            run_id=run_id,
        )

    snapshot_path.unlink(missing_ok=True)
    return status, guard_issues
