from __future__ import annotations

import json
from pathlib import Path

from mmagent.mm.audit import audit_paper
from mmagent.mm.gates.g4 import check_g4, check_narrative


def test_narrative_gate_requires_plain_long_sections(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    (root / "交接").mkdir(parents=True)
    body = "这一段用白话解释题意、困难、建模思路、验证方式和预期交付，不包含公式或工程文件名。" * 8
    (root / "交接" / "叙事底稿.md").write_text(f"## 问题1\n{body}", encoding="utf-8")
    ok, issues = check_narrative(root, [1])
    assert ok, issues


def test_g4_passes_core_mechanical_evidence(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    (root / "论文").mkdir(parents=True)
    (root / "交接").mkdir(parents=True)
    (root / "论文" / "论文.tex").write_text("正文没有需要溯源的数字。", encoding="utf-8")
    (root / "论文" / "0.摘要.tex").write_text("摘要内容。", encoding="utf-8")
    (root / "论文" / "论文.log").write_text(
        "Output written on 论文.pdf (10 pages).", encoding="utf-8"
    )
    (root / "交接" / "需求追踪矩阵.json").write_text(
        json.dumps([{"需求号": "一", "状态": "已销号"}], ensure_ascii=False), encoding="utf-8"
    )
    audit_paper(root)
    ok, issues = check_g4(root)
    assert ok, issues


def test_g4_rejects_untraced_overprecise_number(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    (root / "论文").mkdir(parents=True)
    (root / "交接").mkdir(parents=True)
    (root / "论文" / "论文.tex").write_text("结果为 1.234567。", encoding="utf-8")
    (root / "论文" / "0.摘要.tex").write_text("摘要。", encoding="utf-8")
    (root / "论文" / "论文.log").write_text(
        "Output written on 论文.pdf (10 pages).", encoding="utf-8"
    )
    (root / "交接" / "需求追踪矩阵.json").write_text("[]", encoding="utf-8")
    audit_paper(root)
    ok, issues = check_g4(root)
    assert not ok
    assert any("有效数字过精" in x for x in issues)
    assert any("溯源" in x for x in issues)
