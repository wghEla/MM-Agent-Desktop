"""Unified degraded-release contract (外审 round1 P1-4)。

S2 和 S5/G5 必须使用同一个 Pydantic schema 和 runtime-owned helper。
不允许 S2 直接手写另一套 JSON。
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class DegradedQuestionEntry(BaseModel):
    """S2 问题级降级条目。"""

    question: int = Field(ge=1)
    issues: list[str] = Field(default_factory=list)
    source_stage: str = "S2"
    reason: str = ""


class DegradedReviewIssueEntry(BaseModel):
    """S5/G5 review issue 级降级条目。"""

    id: str = Field(min_length=1)
    generation: int = Field(default=0, ge=0)
    severity: str = Field(default="正确性")
    source_stage: str = "S5"
    reason: str = ""
    evidence: str = ""


class DegradedReleaseCarrier(BaseModel):
    """交接/降级放行.json 唯一 schema。"""

    version: int = Field(default=1)
    questions: list[DegradedQuestionEntry] = Field(default_factory=list)
    review_issues: list[DegradedReviewIssueEntry] = Field(default_factory=list)


def write_degraded_release(
    root: Path,
    *,
    question_entries: list[DegradedQuestionEntry] | None = None,
    review_issue_entries: list[DegradedReviewIssueEntry] | None = None,
) -> Path:
    """Runtime-owned write helper。只有 Runtime 在 escalation 耗尽后才能调用。"""
    carrier = DegradedReleaseCarrier(
        version=1,
        questions=question_entries or [],
        review_issues=review_issue_entries or [],
    )
    path = root / "交接" / "降级放行.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(carrier.model_dump_json(indent=2), encoding="utf-8")
    return path


def read_degraded_release(root: Path) -> DegradedReleaseCarrier | None:
    """Runtime-owned read helper。非法格式 fail closed。"""
    path = root / "交接" / "降级放行.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # Legacy migration must also fail closed: malformed legacy payloads must
    # not escape validation or be silently rewritten into a valid carrier.
    try:
        # S2 old format {"问题": [{"问题编号": N, "issues": [...]}]}
        if "问题" in raw and "questions" not in raw:
            questions = []
            rows = raw.get("问题", [])
            if not isinstance(rows, list):
                return None
            for q in rows:
                if not isinstance(q, dict):
                    return None
                questions.append(DegradedQuestionEntry(
                    question=q.get("问题编号", 0),
                    issues=q.get("issues", []),
                    source_stage="S2",
                ))
            return DegradedReleaseCarrier(
                version=0, questions=questions, review_issues=[]
            )
        # G5 old format {"issue_ids": [...]}
        if "issue_ids" in raw and "review_issues" not in raw:
            ids = raw.get("issue_ids", [])
            if not isinstance(ids, list):
                return None
            entries = [
                DegradedReviewIssueEntry(
                    id=str(x.get("id")) if isinstance(x, dict) else str(x),
                    source_stage="S5",
                )
                for x in ids
            ]
            return DegradedReleaseCarrier(version=0, review_issues=entries)
    except Exception:
        return None
    # Current format
    try:
        return DegradedReleaseCarrier.model_validate(raw)
    except Exception:
        return None


def is_issue_degraded(root: Path, issue_id: str, generation: int) -> bool:
    """Check if a specific review issue is registered as degraded (id + generation match)."""
    carrier = read_degraded_release(root)
    if carrier is None:
        return False
    for entry in carrier.review_issues:
        if entry.id == issue_id and entry.generation == generation:
            return True
    return False



def is_question_degraded(root: Path, question: int) -> bool:
    """Check whether a question-level S2 degraded entry exists."""
    carrier = read_degraded_release(root)
    if carrier is None:
        return False
    return any(entry.question == int(question) for entry in carrier.questions)


def upsert_degraded_question(
    root: Path,
    *,
    question: int,
    issues: list[str],
    reason: str = "",
    source_stage: str = "S2",
) -> Path:
    """Runtime-owned update preserving unrelated question/review entries."""
    path = root / "交接" / "降级放行.json"
    current = read_degraded_release(root)
    if path.is_file() and current is None:
        raise ValueError("existing degraded-release carrier is malformed")
    carrier = current or DegradedReleaseCarrier()
    questions = [entry for entry in carrier.questions if entry.question != int(question)]
    questions.append(DegradedQuestionEntry(
        question=int(question),
        issues=[str(x) for x in issues],
        source_stage=source_stage,
        reason=reason,
    ))
    return write_degraded_release(
        root,
        question_entries=questions,
        review_issue_entries=list(carrier.review_issues),
    )


def upsert_degraded_review_issue(
    root: Path,
    *,
    issue_id: str,
    generation: int,
    severity: str,
    reason: str,
    evidence: str = "",
    source_stage: str = "S5",
) -> Path:
    """Runtime-owned update preserving question entries and other generations."""
    path = root / "交接" / "降级放行.json"
    current = read_degraded_release(root)
    if path.is_file() and current is None:
        raise ValueError("existing degraded-release carrier is malformed")
    carrier = current or DegradedReleaseCarrier()
    review = [
        entry for entry in carrier.review_issues
        if not (entry.id == issue_id and entry.generation == int(generation))
    ]
    review.append(DegradedReviewIssueEntry(
        id=issue_id,
        generation=int(generation),
        severity=severity,
        source_stage=source_stage,
        reason=reason,
        evidence=evidence,
    ))
    return write_degraded_release(
        root,
        question_entries=list(carrier.questions),
        review_issue_entries=review,
    )
