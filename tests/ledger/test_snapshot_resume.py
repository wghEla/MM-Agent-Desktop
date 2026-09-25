from __future__ import annotations

from mmagent.mm.ledger.issue_ledger import IssueLedger


def test_issue_ledger_snapshot_roundtrip_preserves_state_and_id_sequence() -> None:
    ledger = IssueLedger(前缀="审")
    ledger.并入([
        {
            "级别": "正确性",
            "目标": "算",
            "定位": "问题1",
            "问题": "数字不一致",
            "指令": "重算",
            "验收": "对齐",
            "来源": "审A",
        },
        {
            "级别": "叙述",
            "目标": "文",
            "定位": "摘要",
            "问题": "表述不清",
            "指令": "改写",
            "验收": "可复述",
            "来源": "审B",
        },
    ], 轮次=2)
    first = ledger.条目[0]
    ledger.收回执([
        {
            "id": first.id,
            "generation": first.generation,
            "receipt_id": "r1",
            "改动": "已重算",
            "证据": "结果.json",
        }
    ], 腿名="回炉算")

    restored = IssueLedger.从快照(ledger.快照(), 前缀="审")
    assert restored.快照() == ledger.快照()
    assert restored.轮次 == 2

    restored.并入([
        {
            "级别": "版式",
            "目标": "文",
            "定位": "结论",
            "问题": "新问题且与旧问题完全不同",
            "指令": "修复",
            "验收": "通过",
            "来源": "审C",
        }
    ], 轮次=3)
    assert restored.条目[-1].id.endswith("-03")
