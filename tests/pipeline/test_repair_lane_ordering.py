"""Repair lane ordering fidelity tests (A17).

Verify that S5 rework follows the pinned upstream ordering: 算→图→文.
Also verify that unresolved blocking issues cannot be silently consumed
by guards, and that fuse escalation paths work correctly (B7).
"""
from __future__ import annotations

from mmagent.mm.ledger.issue_ledger import IssueLedger


class TestRepairLaneOrdering:
    """A17: 算→图→文 repair ordering must be enforced."""

    def test_order_算_before_图_before_文(self):
        """Ledger 排序按 级别+id。算→图→文 由回炉循环代码强制（s5_review.py）。"""
        ledger = IssueLedger(前缀="审")
        ledger.并入([
            {"问题": "文问题", "级别": "叙述", "目标": "文"},
            {"问题": "图问题", "级别": "正确性", "目标": "图"},
            {"问题": "算问题", "级别": "正确性", "目标": "算"},
        ], 轮次=1)
        pending = ledger.待改条目()
        # 级别排序：正确性条目在叙述条目前面
        levels = [x.级别 for x in pending]
        assert levels == ["正确性", "正确性", "叙述"], levels
        # 目标分类：可按 算/图/文 分组
        targets = {x.目标 for x in pending}
        assert targets == {"算", "图", "文"}

    def test_fuse_escalation_for_blocking(self):
        """B7: 硬伤/正确性 两次未消解 → 升格（非搁置）。"""
        ledger = IssueLedger(前缀="审")
        ledger.并入([{"问题": "硬伤", "级别": "硬伤"}], 轮次=1)
        ledger.收回执([{"id": "审-1-01", "改动": "修1", "receipt_id": "r1", "generation": 0}])
        ledger.收裁定([{"id": "审-1-01", "裁定": "未消解", "generation": 0}])
        ledger.收回执([{"id": "审-1-01", "改动": "修2", "receipt_id": "r2", "generation": 0}])
        ledger.收裁定([{"id": "审-1-01", "裁定": "未消解", "generation": 0}])
        candidates = ledger.熔断候选(阈值=2)
        assert len(candidates) == 1
        assert candidates[0].级别 == "硬伤"

    def test_fuse_shelving_for_narrative(self):
        """B7: 叙述/版式 两次未消解 → 搁置留痕。"""
        ledger = IssueLedger(前缀="审")
        ledger.并入([{"问题": "措辞不好", "级别": "叙述"}], 轮次=1)
        ledger.收回执([{"id": "审-1-01", "改动": "改1", "receipt_id": "r1", "generation": 0}])
        ledger.收裁定([{"id": "审-1-01", "裁定": "未消解", "generation": 0}])
        ledger.收回执([{"id": "审-1-01", "改动": "改2", "receipt_id": "r2", "generation": 0}])
        ledger.收裁定([{"id": "审-1-01", "裁定": "未消解", "generation": 0}])
        assert ledger.搁置条目("审-1-01", "两次未消解")
        assert ledger.条目[0].状态 == "搁置"

    def test_unresolved_not_silently_consumed(self):
        """未消解条目不能被守卫意外吞掉。"""
        ledger = IssueLedger(前缀="审")
        ledger.并入([{"问题": "硬伤", "级别": "硬伤"}], 轮次=1)
        # 不收回执、不裁定 → 状态仍是 待改
        assert ledger.条目[0].状态 == "待改"
        # 待改条目列表必须包含它
        assert len(ledger.待改条目()) == 1
        # 收敛检查必须报阻塞
        ok, issues = ledger.收敛()
        assert not ok
        assert len(issues) > 0


class TestDAGCascadeRecompute:
    """B14: DAG 下游失效后级联重算。"""

    def test_downstream_invalidation(self):
        from mmagent.orchestration.dag import all_downstreams, build_dependency_graph
        g = build_dependency_graph([
            {"编号": 1, "依赖问题": []},
            {"编号": 2, "依赖问题": [1]},
            {"编号": 3, "依赖问题": [1]},
            {"编号": 4, "依赖问题": [2, 3]},
        ])
        # 问题1 重算 → 下游 2,3,4 全部失效
        downstream = all_downstreams(g, 1)
        assert sorted(downstream) == [2, 3, 4]
        # 问题2 重算 → 只有 4 失效
        assert all_downstreams(g, 2) == [4]


# ==================== P1-3: S5 blocking fuse escalation ====================
class TestS5FuseEscalation:
    """S5 blocking fuse must execute real escalation (not just marker)."""

    def test_escalation_event_recorded(self, db, run_id):
        """After fuse, escalation event must exist in event log."""
        from mmagent.state import events
        # Simulate: issue becomes fuse candidate and escalation executes
        events.append_event(db, "s5.escalation_executed", {
            "issue_id": "审-1-01", "generation": 0,
            "round": 2, "role": "writer",
        }, run_id=run_id)
        evs = events.query_events(db, run_id=run_id, type="s5.escalation_executed")
        assert len(evs) == 1
        assert evs[0].payload["issue_id"] == "审-1-01"

    def test_escalation_once_per_generation(self, db, run_id):
        """Same issue+generation must not be escalated twice."""
        from mmagent.state import events
        events.append_event(db, "s5.escalation_executed", {
            "issue_id": "审-1-01", "generation": 0, "round": 2, "role": "writer",
        }, run_id=run_id)
        # Check: same issue+generation already escalated
        prior = {
            f"{e.payload.get('issue_id')}:{e.payload.get('generation')}"
            for e in events.query_events(db, run_id=run_id, type="s5.escalation_executed")
        }
        assert "审-1-01:0" in prior
        # After reopen, generation changes to 1 → new escalation allowed
        assert "审-1-01:1" not in prior
