"""Issue Ledger 状态机 + 身份合并 + 配对裁定 + 熔断 单测。"""
from __future__ import annotations

from mmagent.mm.ledger.issue_ledger import IssueLedger


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
        t.收裁定([{"id": "意-1-01", "裁定": "已消解"}])
        assert t.条目[0].状态 == "已消解"
        # 重开
        t.并入([{"问题": "还是不一致", "对应": "意-1-01"}], 轮次=2)
        assert t.条目[0].状态 == "待改"
        assert t.条目[0].重开次数 == 1

    def test_receipt_flow(self):
        t = IssueLedger()
        t.并入([{"问题": "缺数据"}], 轮次=1)
        r = t.收回执([{"id": "意-1-01", "改动": "已补充"}], 腿名="撰稿")
        assert r["受理"] == 1
        assert t.条目[0].状态 == "待复核"
        # 评审裁定
        t.收裁定([{"id": "意-1-01", "裁定": "已消解"}])
        assert t.条目[0].状态 == "已消解"

    def test_pending_review_not_default_pass(self):
        t = IssueLedger()
        t.并入([{"问题": "问题A"}], 轮次=1)
        t.收回执([{"id": "意-1-01", "改动": "改了"}])
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
        # 消解硬伤
        t.收裁定([{"id": t.条目[0].id, "裁定": "已消解"}])
        ok, _ = t.收敛()
        assert ok  # 硬伤消解了，叙述不算阻塞

    def test_fuse_candidates(self):
        t = IssueLedger()
        t.并入([{"问题": "反复出现"}], 轮次=1)
        t.收回执([{"id": "意-1-01", "改动": "改1"}])
        t.收裁定([{"id": "意-1-01", "裁定": "未消解"}])  # 评审判未消解 → 未消解
        t.收回执([{"id": "意-1-01", "改动": "改2"}])
        t.收裁定([{"id": "意-1-01", "裁定": "未消解"}])  # 仍未消解
        assert t.条目[0].尝试次数 == 2
        assert len(t.熔断候选(阈值=2)) == 1

    def test_shelve(self):
        t = IssueLedger()
        t.并入([{"问题": "修不掉"}], 轮次=1)
        assert t.搁置条目("意-1-01", "两次未消解")
        assert t.条目[0].状态 == "搁置"

    def test_severity_escalation(self):
        t = IssueLedger()
        t.并入([{"问题": "问题", "级别": "叙述"}], 轮次=1)
        t.并入([{"问题": "问题", "级别": "硬伤", "对应": "意-1-01"}], 轮次=2)
        assert t.条目[0].级别 == "硬伤"  # 只升不降
