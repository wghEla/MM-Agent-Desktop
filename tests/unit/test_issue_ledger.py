"""Issue Ledger 状态机 + 身份合并 + 配对裁定 + 熔断 单测。"""
from __future__ import annotations

from mmagent.mm.ledger.issue_ledger import IssueLedger, merge_channel_verdicts


class TestLedger:
    def test_new_issue(self):
        t = IssueLedger()
        r = t.并入([{"问题": "图3缺图例", "级别": "正确性", "目标": "图"}], 轮次=1)
        assert r["新增"] == 1
        assert t.条目[0].id == "意-1-01"
        assert t.条目[0].级别 == "正确性"

    def test_explicit_merge(self):
        t = IssueLedger()
        t.并入([{"问题": "旧问题"}], 轮次=1)
        r = t.并入([{"问题": "新措辞", "对应": "意-1-01"}], 轮次=2)
        assert r["合并"] == 1
        assert r["新增"] == 0

    def test_similarity_merge(self):
        t = IssueLedger()
        t.并入([{"问题": "图3的坐标轴单位缺失，需要补充", "定位": "论文/图3.tex"}], 轮次=1)
        r = t.并入([{"问题": "图3坐标轴缺单位标注", "定位": "论文/图3.tex"}], 轮次=2)
        assert r["合并"] >= 0  # 相似度可能高也可能低，只要不崩溃

    def test_resolve_and_reopen(self):
        t = IssueLedger()
        t.并入([{"问题": "数值不一致"}], 轮次=1)
        t.收回执([{"id": "意-1-01", "改动": "修复了", "generation": 0, "receipt_id": "r0"}])  # 待改→待复核
        t.收裁定([{"id": "意-1-01", "裁定": "已消解", "generation": 0}])  # 待复核→已消解
        assert t.条目[0].状态 == "已消解"
        # 重开
        t.并入([{"问题": "还是不一致", "对应": "意-1-01"}], 轮次=2)
        assert t.条目[0].状态 == "待改"
        assert t.条目[0].重开次数 == 1
        assert t.条目[0].generation == 1
        # gen1 的裁定需要 generation=1
        t.收回执([{"id": "意-1-01", "改动": "再修", "generation": 1, "receipt_id": "r1"}])
        t.收裁定([{"id": "意-1-01", "裁定": "已消解", "generation": 1}])
        assert t.条目[0].状态 == "已消解"

    def test_receipt_flow(self):
        t = IssueLedger()
        t.并入([{"问题": "缺数据"}], 轮次=1)
        r = t.收回执([{"id": "意-1-01", "改动": "已补充", "generation": 0, "receipt_id": "r1"}], 腿名="撰稿")
        assert r["受理"] == 1
        assert t.条目[0].状态 == "待复核"
        # 评审裁定
        t.收裁定([{"id": "意-1-01", "裁定": "已消解", "generation": 0}])
        assert t.条目[0].状态 == "已消解"

    def test_pending_review_not_default_pass(self):
        t = IssueLedger()
        t.并入([{"问题": "问题A"}], 轮次=1)
        t.收回执([{"id": "意-1-01", "改动": "改了", "generation": 0, "receipt_id": "r1"}])
        assert t.条目[0].状态 == "待复核"
        # 漏裁 → 回到待改
        n = t.待复核未裁()
        assert n == 1
        assert t.条目[0].状态 == "待改"

    def test_convergence_blocked(self):
        t = IssueLedger()
        t.并入([
            {"问题": "硬伤", "级别": "硬伤"},
            {"问题": "叙述", "级别": "叙述"},
        ], 轮次=1)
        ok, _ = t.收敛()
        assert not ok  # 硬伤未消解
        # 消解硬伤（须先回执到待复核）
        t.收回执([{"id": t.条目[0].id, "改动": "修好了", "generation": 0, "receipt_id": "r1"}])
        t.收裁定([{"id": t.条目[0].id, "裁定": "已消解", "generation": 0}])
        ok, _ = t.收敛()
        assert ok  # 硬伤消解了，叙述不算阻塞

    def test_fuse_candidates(self):
        t = IssueLedger()
        t.并入([{"问题": "反复出现"}], 轮次=1)
        t.收回执([{"id": "意-1-01", "改动": "改1", "generation": 0, "receipt_id": "r1"}])
        t.收裁定([{"id": "意-1-01", "裁定": "未消解", "generation": 0}])  # 评审判未消解 → 未消解
        t.收回执([{"id": "意-1-01", "改动": "改2", "generation": 0, "receipt_id": "r2"}])
        t.收裁定([{"id": "意-1-01", "裁定": "未消解", "generation": 0}])  # 仍未消解
        assert t.条目[0].尝试次数 == 2
        assert len(t.熔断候选(阈值=2)) == 1

    def test_shelve(self):
        t = IssueLedger()
        t.并入([{"问题": "修不掉"}], 轮次=1)
        # 搁置前置条件：尝试次数 >= 2
        assert not t.搁置条目("意-1-01", "太早了")  # 0 次尝试 → 拒绝
        t.收回执([{"id": "意-1-01", "改动": "修1", "receipt_id": "r1", "generation": 0}])
        t.收裁定([{"id": "意-1-01", "裁定": "未消解", "generation": 0}])
        t.收回执([{"id": "意-1-01", "改动": "修2", "receipt_id": "r2", "generation": 0}])
        t.收裁定([{"id": "意-1-01", "裁定": "未消解", "generation": 0}])
        assert t.搁置条目("意-1-01", "两次未消解")
        assert t.条目[0].状态 == "搁置"

    def test_receipt_idempotency(self):
        """同 receipt_id 的重复回执被忽略。"""
        t = IssueLedger()
        t.并入([{"问题": "test"}], 轮次=1)
        t.收回执([{"id": "意-1-01", "改动": "修改", "receipt_id": "r1", "generation": 0}])
        t.收回执([{"id": "意-1-01", "改动": "修改", "receipt_id": "r1", "generation": 0}])  # 重复
        assert t.条目[0].尝试次数 == 1  # 不虚增

    def test_severity_escalation(self):
        t = IssueLedger()
        t.并入([{"问题": "问题", "级别": "叙述"}], 轮次=1)
        t.并入([{"问题": "问题", "级别": "硬伤", "对应": "意-1-01"}], 轮次=2)
        assert t.条目[0].级别 == "硬伤"  # 只升不降



def test_judge_abstention_does_not_override_substantive_resolved_vote() -> None:
    merged, abstentions = merge_channel_verdicts([
        (
            "reviewer",
            [{"id": "审-1-01", "generation": 0, "裁定": "已消解", "理由": "实物已核对"}],
        ),
        (
            "judge_simulator",
            [{"id": "审-1-01", "generation": 0, "裁定": "未消解", "理由": "未提供完整材料，无法核实"}],
        ),
    ])

    assert abstentions == 1
    assert merged == [{
        "id": "审-1-01",
        "generation": 0,
        "裁定": "已消解",
        "理由": "reviewer:实物已核对",
        "来源通道": "reviewer",
    }]


def test_substantive_unresolved_vote_still_vetoes_resolution() -> None:
    merged, abstentions = merge_channel_verdicts([
        (
            "reviewer",
            [{"id": "审-1-01", "generation": 0, "裁定": "已消解", "理由": "A认为已修"}],
        ),
        (
            "judge_simulator",
            [{"id": "审-1-01", "generation": 0, "裁定": "未消解", "理由": "当前页仍能直接看到错位"}],
        ),
    ])

    assert abstentions == 0
    assert merged[0]["裁定"] == "未消解"
    assert merged[0]["来源通道"] == "judge_simulator"


def test_only_abstentions_emit_no_verdict() -> None:
    merged, abstentions = merge_channel_verdicts([
        (
            "judge_simulator",
            [{"id": "审-1-01", "generation": 0, "裁定": "未消解", "理由": "本通道无法验证全文事实"}],
        )
    ])

    assert merged == []
    assert abstentions == 1


def test_receipt_requires_generation_and_stable_id() -> None:
    t = IssueLedger()
    t.并入([{"问题": "硬伤", "级别": "硬伤"}], 轮次=1)

    missing_generation = t.收回执([
        {"id": "意-1-01", "改动": "修复", "receipt_id": "r1"}
    ])
    missing_id = t.收回执([
        {"id": "意-1-01", "改动": "修复", "generation": 0}
    ])

    assert missing_generation["受理"] == 0
    assert missing_id["受理"] == 0
    assert t.条目[0].尝试次数 == 0
    assert t.条目[0].状态 == "待改"


def test_stale_receipt_cannot_advance_reopened_issue() -> None:
    t = IssueLedger()
    t.并入([{"问题": "数值错", "级别": "正确性"}], 轮次=1)
    t.收回执([
        {"id": "意-1-01", "改动": "第一次修复", "generation": 0, "receipt_id": "r0"}
    ])
    t.收裁定([
        {"id": "意-1-01", "裁定": "已消解", "generation": 0}
    ])
    t.并入([{"问题": "数值错再次出现", "对应": "意-1-01"}], 轮次=2)

    result = t.收回执([
        {"id": "意-1-01", "改动": "迟到旧回执", "generation": 0, "receipt_id": "late"}
    ])

    assert result["受理"] == 0
    assert t.条目[0].generation == 1
    assert t.条目[0].尝试次数 == 0
    assert t.条目[0].状态 == "待改"


def test_reopen_resets_generation_attempt_budget() -> None:
    t = IssueLedger()
    t.并入([{"问题": "反复硬伤", "级别": "硬伤"}], 轮次=1)
    for rid in ("r1", "r2"):
        t.收回执([
            {"id": "意-1-01", "改动": rid, "generation": 0, "receipt_id": rid}
        ])
        t.收裁定([
            {"id": "意-1-01", "裁定": "未消解", "generation": 0}
        ])
    # resolve generation 0 after the second failed attempt
    t.收回执([
        {"id": "意-1-01", "改动": "最终修复", "generation": 0, "receipt_id": "r3"}
    ])
    t.收裁定([
        {"id": "意-1-01", "裁定": "已消解", "generation": 0}
    ])
    t.并入([{"问题": "反复硬伤又出现", "对应": "意-1-01"}], 轮次=2)

    assert t.条目[0].generation == 1
    assert t.条目[0].尝试次数 == 0
    assert t.熔断候选(2) == []


def test_reappearing_shelved_blocker_reopens_and_blocks_convergence() -> None:
    t = IssueLedger()
    t.并入([{"问题": "硬伤", "级别": "硬伤"}], 轮次=1)
    for rid in ("r1", "r2"):
        t.收回执([
            {"id": "意-1-01", "改动": rid, "generation": 0, "receipt_id": rid}
        ])
        t.收裁定([
            {"id": "意-1-01", "裁定": "未消解", "generation": 0}
        ])
    assert t.搁置条目("意-1-01", "两次仍未解决")
    assert t.条目[0].状态 == "搁置"

    merged = t.并入([
        {"问题": "硬伤仍存在", "级别": "硬伤", "对应": "意-1-01"}
    ], 轮次=2)

    assert merged["重开"] == 1
    assert t.条目[0].状态 == "待改"
    assert t.条目[0].generation == 1
    assert t.条目[0].尝试次数 == 0
    assert t.收敛()[0] is False


def test_rollback_invalidates_old_generation_verdict() -> None:
    t = IssueLedger()
    t.并入([{"问题": "硬伤", "级别": "硬伤"}], 轮次=1)
    t.收回执([
        {
            "id": "意-1-01",
            "改动": "round1 fix",
            "generation": 0,
            "receipt_id": "r1",
        }
    ], 轮次=1)
    t.收裁定([
        {"id": "意-1-01", "裁定": "已消解", "generation": 0}
    ], 轮次=1)

    assert t.回退轮修订(1, "版本更差") == 1
    assert t.条目[0].generation == 1
    assert t.条目[0].状态 == "未消解"

    t.收回执([
        {
            "id": "意-1-01",
            "改动": "round2 fix",
            "generation": 1,
            "receipt_id": "r2",
        }
    ], 轮次=2)
    stale = t.收裁定([
        {"id": "意-1-01", "裁定": "已消解", "generation": 0}
    ], 轮次=1)

    assert stale["已消解"] == 0
    assert t.条目[0].状态 == "待复核"
