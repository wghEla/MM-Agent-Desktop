"""Degraded-release unified contract tests (外审 round1 P1-4)。"""
from __future__ import annotations

import json
from pathlib import Path

from mmagent.mm.contracts.degraded_release import (
    DegradedQuestionEntry,
    DegradedReviewIssueEntry,
    is_issue_degraded,
    is_question_degraded,
    read_degraded_release,
    upsert_degraded_question,
    upsert_degraded_review_issue,
    write_degraded_release,
)


class TestDegradedReleaseContract:
    def test_write_and_read_roundtrip(self, tmp_path: Path):
        write_degraded_release(
            tmp_path,
            question_entries=[DegradedQuestionEntry(question=1, issues=["算力不足"], reason="escalation exhausted")],
            review_issue_entries=[DegradedReviewIssueEntry(id="审-1-01", generation=1, severity="正确性", reason="fuse")],
        )
        carrier = read_degraded_release(tmp_path)
        assert carrier is not None
        assert carrier.version == 1
        assert len(carrier.questions) == 1
        assert carrier.questions[0].question == 1
        assert len(carrier.review_issues) == 1
        assert carrier.review_issues[0].id == "审-1-01"
        assert carrier.review_issues[0].generation == 1

    def test_legacy_s2_format_migrates(self, tmp_path: Path):
        legacy = {"问题": [{"问题编号": 1, "issues": ["降级"]}]}
        (tmp_path / "交接").mkdir(parents=True)
        (tmp_path / "交接" / "降级放行.json").write_text(json.dumps(legacy), encoding="utf-8")
        carrier = read_degraded_release(tmp_path)
        assert carrier is not None
        assert carrier.version == 0
        assert len(carrier.questions) == 1
        assert carrier.questions[0].question == 1

    def test_legacy_g5_format_migrates(self, tmp_path: Path):
        legacy = {"issue_ids": [{"id": "审-1-01"}, "审-1-02"]}
        (tmp_path / "交接").mkdir(parents=True)
        (tmp_path / "交接" / "降级放行.json").write_text(json.dumps(legacy), encoding="utf-8")
        carrier = read_degraded_release(tmp_path)
        assert carrier is not None
        assert len(carrier.review_issues) == 2

    def test_malformed_fails_closed(self, tmp_path: Path):
        (tmp_path / "交接").mkdir(parents=True)
        (tmp_path / "交接" / "降级放行.json").write_text("{invalid", encoding="utf-8")
        assert read_degraded_release(tmp_path) is None

    def test_missing_file_returns_none(self, tmp_path: Path):
        assert read_degraded_release(tmp_path) is None

    def test_issue_degraded_match_by_id_and_generation(self, tmp_path: Path):
        write_degraded_release(
            tmp_path,
            review_issue_entries=[
                DegradedReviewIssueEntry(id="审-1-01", generation=1),
                DegradedReviewIssueEntry(id="审-1-02", generation=0),
            ],
        )
        assert is_issue_degraded(tmp_path, "审-1-01", 1)
        assert not is_issue_degraded(tmp_path, "审-1-01", 0)  # wrong generation
        assert is_issue_degraded(tmp_path, "审-1-02", 0)
        assert not is_issue_degraded(tmp_path, "审-1-03", 0)  # not present

    def test_s2_question_survives_s5_update(self, tmp_path: Path):
        """S2 question entry must not be lost when S5 adds review issue entries."""
        write_degraded_release(tmp_path, question_entries=[
            DegradedQuestionEntry(question=1, issues=["esc exhausted"])
        ])
        # S5 adds review issue
        carrier = read_degraded_release(tmp_path)
        carrier.review_issues.append(DegradedReviewIssueEntry(id="审-2-01", generation=1))
        write_path = write_degraded_release(
            tmp_path,
            question_entries=carrier.questions,
            review_issue_entries=carrier.review_issues,
        )
        final = read_degraded_release(tmp_path)
        assert len(final.questions) == 1  # S2 entry preserved
        assert len(final.review_issues) == 1  # S5 entry added


    def test_runtime_upserts_preserve_both_namespaces(self, tmp_path: Path):
        upsert_degraded_question(
            tmp_path,
            question=1,
            issues=["escalation exhausted"],
            reason="S2 exhausted",
        )
        upsert_degraded_review_issue(
            tmp_path,
            issue_id="审-2-01",
            generation=3,
            severity="正确性",
            reason="S5 exhausted",
        )

        carrier = read_degraded_release(tmp_path)
        assert carrier is not None
        assert is_question_degraded(tmp_path, 1)
        assert is_issue_degraded(tmp_path, "审-2-01", 3)
        assert not is_issue_degraded(tmp_path, "审-2-01", 2)
        assert len(carrier.questions) == 1
        assert len(carrier.review_issues) == 1

    def test_malformed_legacy_question_fails_closed(self, tmp_path: Path):
        (tmp_path / "交接").mkdir(parents=True)
        (tmp_path / "交接" / "降级放行.json").write_text(
            json.dumps({"问题": [{"issues": ["missing question id"]}]}),
            encoding="utf-8",
        )
        assert read_degraded_release(tmp_path) is None

    def test_upsert_refuses_to_overwrite_malformed_existing_carrier(self, tmp_path: Path):
        import pytest

        (tmp_path / "交接").mkdir(parents=True)
        (tmp_path / "交接" / "降级放行.json").write_text("{bad", encoding="utf-8")
        with pytest.raises(ValueError):
            upsert_degraded_question(
                tmp_path,
                question=1,
                issues=["must not erase malformed evidence"],
            )
