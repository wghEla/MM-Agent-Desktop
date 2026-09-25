"""Shared best-retention primitives for review loops.

The pinned upstream paper foundry keeps a pre-review snapshot for each round and
rolls back a revision when paired review says it is worse.  If no relative
judgment is available, a score drop greater than 0.5 is treated as regression.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from mmagent.workspace.path_policy import PathPolicy


def retention_decision(
    relative_judgment: str | None,
    old_score: float | None,
    new_score: float | None,
    *,
    noise_band: float = 0.5,
) -> tuple[str, str]:
    """Return 接受/回退 using the pinned paired-review rule."""
    if relative_judgment == "更差":
        return "回退", "配对评审判定更差"
    if relative_judgment == "更好":
        return "接受", "配对评审判定更好"
    if (
        old_score is not None
        and new_score is not None
        and new_score < old_score - noise_band
    ):
        return (
            "回退",
            f"评分 {old_score:.2f}->{new_score:.2f} 跌破 {noise_band:.2f} 噪声带",
        )
    return "接受", "持平/无相对判断，且评分未跌破噪声带"


def snapshot_dir(policy: PathPolicy, stage: str, round_num: int) -> Path:
    safe_stage = str(stage).strip().lower()
    if not safe_stage or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
                             for ch in safe_stage):
        raise ValueError(f"invalid snapshot stage: {stage!r}")
    return (
        policy.root
        / ".mmagent"
        / "checkpoints"
        / safe_stage
        / f"round_{round_num:03d}"
    )


def ensure_paper_snapshot(
    policy: PathPolicy,
    stage: str,
    round_num: int,
) -> int:
    """Persist the pre-review TeX snapshot once; never overwrite it on resume."""
    final = snapshot_dir(policy, stage, round_num)
    marker = final / ".complete"
    if marker.is_file():
        return len(list((final / "paper").rglob("*.tex")))

    base = final.parent
    base.mkdir(parents=True, exist_ok=True)
    temp = base / f".round_{round_num:03d}.tmp"
    shutil.rmtree(temp, ignore_errors=True)
    paper_snapshot = temp / "paper"
    paper_snapshot.mkdir(parents=True, exist_ok=True)

    source = policy.root / "论文"
    count = 0
    if source.is_dir():
        for src in sorted(source.rglob("*.tex")):
            rel = src.relative_to(source)
            dest = paper_snapshot / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            count += 1

    (temp / ".complete").write_text(str(count), encoding="utf-8")
    shutil.rmtree(final, ignore_errors=True)
    temp.replace(final)
    return count


def restore_paper_snapshot(
    policy: PathPolicy,
    stage: str,
    round_num: int,
) -> int:
    """Restore all TeX carriers from a previously completed snapshot."""
    snapshot = snapshot_dir(policy, stage, round_num)
    if not (snapshot / ".complete").is_file():
        return 0

    paper_snapshot = snapshot / "paper"
    target = policy.root / "论文"
    restored = 0
    for src in sorted(paper_snapshot.rglob("*.tex")):
        rel = src.relative_to(paper_snapshot)
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        restored += 1
    return restored
