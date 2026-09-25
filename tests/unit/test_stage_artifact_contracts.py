from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from mmagent.agent.errors import ArtifactInvalid
from mmagent.mm.contracts.s3_contracts import FigureReview
from mmagent.mm.contracts.s4_contracts import (
    AbstractRestatementVerdict,
    BlindReaderReview,
    ChapterReview,
    RequirementCoverageDocument,
)
from mmagent.mm.contracts.s5_contracts import ReviewArtifact
from mmagent.workspace.artifacts import ExpectedArtifact, verify_expected_artifacts


def test_requirement_coverage_is_enforced_at_artifact_acceptance(policy) -> None:
    path = policy.root / "交接" / "需求覆盖.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [{
                "需求号": "1-1",
                "章节": "问题一",
                "证据": "   ",
                "图表": "图1",
                "关键数字": "2.17",
            }],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ArtifactInvalid, match="schema 校验失败"):
        verify_expected_artifacts(
            policy,
            [ExpectedArtifact(
                rel_path="交接/需求覆盖.json",
                schema_model=RequirementCoverageDocument,
            )],
        )


def test_requirement_coverage_accepts_complete_consumer_fields(policy) -> None:
    path = policy.root / "交接" / "需求覆盖.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [{
                "需求号": "1-1",
                "章节": "问题一",
                "证据": "正文参数估计段",
                "图表": "图1",
                "关键数字": "2.17",
            }],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    checks = verify_expected_artifacts(
        policy,
        [ExpectedArtifact(
            rel_path="交接/需求覆盖.json",
            schema_model=RequirementCoverageDocument,
        )],
    )

    assert checks[0].schema_id == "RequirementCoverageDocument"


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (FigureReview, {"问题": []}),
        (ChapterReview, {"总分": 8.0, "相对判断": "明显更好"}),
        (BlindReaderReview, {"卡住": []}),
        (AbstractRestatementVerdict, {"通过": True}),
    ],
)
def test_consumer_required_review_fields_fail_closed(model, payload) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_review_contracts_accept_current_canonical_envelopes() -> None:
    assert FigureReview.model_validate({"总分": 8.2, "问题": []}).总分 == 8.2
    assert ChapterReview.model_validate(
        {"总分": 8.3, "相对判断": "持平", "问题": []}
    ).相对判断 == "持平"
    assert BlindReaderReview.model_validate(
        {"读者分": 8.1, "卡住": []}
    ).读者分 == 8.1
    assert AbstractRestatementVerdict.model_validate(
        {"通过": True, "分数": 9.0}
    ).通过 is True



def test_s5_review_artifact_keeps_supported_envelope_aliases() -> None:
    payload = {
        "最高优先级修改": [{
            "级别": "正确性",
            "目标": "文",
            "定位": "问题1",
            "问题": "结论缺验证",
            "指令": "补最小验证说明",
            "验收": "出现可复核证据",
        }],
        "逐条裁定": [{
            "id": "审-1-01",
            "generation": 0,
            "裁定": "未消解",
            "理由": "页图范围内无法核实全文事实",
        }],
        "相对判断": "持平",
    }

    parsed = ReviewArtifact.model_validate(payload)

    assert parsed.root.相对判断 == "持平"
    assert parsed.root.逐条裁定[0].裁定 == "未消解"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "意见": [{
                "级别": "一般问题",
                "目标": "文",
                "定位": "问题1",
                "问题": "x",
                "指令": "y",
                "验收": "z",
            }]
        },
        {
            "意见": [{
                "级别": "正确性",
                "目标": "表格",
                "定位": "问题1",
                "问题": "x",
                "指令": "y",
                "验收": "z",
            }]
        },
        {
            "裁定": [{
                "id": "审-1-01",
                "裁定": "已消解",
            }]
        },
        {"完全未知字段": []},
    ],
)
def test_s5_review_artifact_rejects_consumer_ambiguous_payloads(payload) -> None:
    with pytest.raises(ValidationError):
        ReviewArtifact.model_validate(payload)
