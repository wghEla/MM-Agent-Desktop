from __future__ import annotations

from pathlib import Path

from mmagent.api.projects import create_project
from mmagent.mm.ledger.issue_ledger import IssueLedger
from mmagent.mm.pipeline.s5_review import _restore_round_checkpoint
from mmagent.state import events, repositories


def test_s5_restores_only_post_rework_round_complete_snapshot(tmp_path: Path) -> None:
    handle = create_project(tmp_path / "proj", name="s5-resume", profile="标准")
    try:
        run_id = repositories.create_run(
            handle.workspace.db, project_id=handle.project_id, profile="标准"
        )
        ledger = IssueLedger(前缀="审")
        ledger.并入([
            {
                "级别": "正确性",
                "目标": "算",
                "定位": "问题1",
                "问题": "结果需重算",
                "指令": "重算",
                "验收": "红队对齐",
                "来源": "审A",
            }
        ], 轮次=1)
        item = ledger.条目[0]
        ledger.收回执([
            {
                "id": item.id,
                "generation": item.generation,
                "receipt_id": "receipt-1",
                "改动": "已重算",
                "证据": "结果.json",
            }
        ], 腿名="回炉算")

        # Old observation event must never be treated as a resume boundary.
        events.append_event(
            handle.workspace.db,
            "s5.round_reviewed",
            {"round": 2, "ledger": {}},
            run_id=run_id,
        )
        events.append_event(
            handle.workspace.db,
            "checkpoint.s5_round_complete",
            {
                "round": 1,
                "converged": False,
                "ledger": ledger.快照(),
                "round_info": {"round": 1, "rework": {"算": 1}},
                "needs_escalation": ["审-1-99"],
            },
            run_id=run_id,
        )

        restored, rounds, start_round, converged, escalation = _restore_round_checkpoint(
            handle.workspace.db, run_id
        )
        assert restored.快照() == ledger.快照()
        assert start_round == 2
        assert converged is False
        assert rounds == [{"round": 1, "rework": {"算": 1}}]
        assert escalation == ["审-1-99"]
    finally:
        handle.workspace.db.close()
