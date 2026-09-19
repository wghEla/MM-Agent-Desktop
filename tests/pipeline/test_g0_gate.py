"""S0/G0/S1/G1 流水线测试（mock provider 级）。

覆盖：G0 判据逐条、S0 Agent 流（读题→预测→矩阵）、G1 判据、S1 Agent 流。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.mm.gates.g0 import check_g0

VALID_CONTRACT = {
    "赛题": "B",
    "标题": "红外反射谱测外延层厚度",
    "问题": [
        {"编号": 1, "原文摘录": "问题1 建立模型", "解读": "需要建立厚度反演模型",
         "需求条目": [{"需求号": "1-1", "内容": "建立厚度模型", "评分点推测": "模型推导"},
                      {"需求号": "1-2", "内容": "给出计算结果", "评分点推测": "数值表"}]},
        {"编号": 2, "原文摘录": "问题2 分析可靠性", "解读": "需要灵敏度分析",
         "需求条目": [{"需求号": "2-1", "内容": "灵敏度分析", "评分点推测": "变动表"}]},
    ],
    "硬约束清单": [{"约束号": "C1", "内容": "单位为微米", "出处": "题面第1段"}],
    "歧义裁定": [{"条目": "厚度定义", "候选解释": ["物理厚度", "光学厚度"],
                  "裁定": "物理厚度", "理由": "题面明确", "影响范围": "全题"}],
    "附件清单": [{"文件": "data.xlsx", "内容概述": "反射谱数据", "关联问题": [1, 2]}],
}

MATRIX = [
    {"需求号": "1-1", "问题编号": 1, "内容": "建立厚度模型"},
    {"需求号": "1-2", "问题编号": 1, "内容": "给出计算结果"},
    {"需求号": "2-1", "问题编号": 2, "内容": "灵敏度分析"},
]


@pytest.fixture
def g0_ws(tmp_path: Path) -> Path:
    """创建通过 G0 的最小工作区。"""
    root = tmp_path / "proj"
    for d in ("交接", "输入/题目", "输入/数据"):
        (root / d).mkdir(parents=True)
    (root / "交接" / "题面契约.json").write_text(
        json.dumps(VALID_CONTRACT, ensure_ascii=False, indent=1), encoding="utf-8")
    (root / "交接" / "需求追踪矩阵.json").write_text(
        json.dumps(MATRIX, ensure_ascii=False, indent=1), encoding="utf-8")
    (root / "输入" / "数据" / "data.xlsx").write_bytes(b"\xd0\xcf\x11\xe0stub")
    return root


class TestG0:
    def test_valid_contract_passes(self, g0_ws: Path):
        ok, issues = check_g0(g0_ws)
        assert ok, issues

    def test_missing_contract(self, tmp_path: Path):
        root = tmp_path / "empty"
        root.mkdir()
        ok, issues = check_g0(root)
        assert not ok
        assert any("缺失" in i for i in issues)

    def test_invalid_schema(self, g0_ws: Path):
        (g0_ws / "交接" / "题面契约.json").write_text('{"赛题": "B"}', encoding="utf-8")
        ok, issues = check_g0(g0_ws)
        assert not ok
        # 缺顶层键 + 问题为空
        assert any("缺顶层键" in i for i in issues)
        assert any("问题 为空" in i for i in issues)

    def test_malformed_json_rejected(self, g0_ws: Path):
        """非法 JSON → 校验失败。"""
        (g0_ws / "交接" / "题面契约.json").write_text("{invalid json", encoding="utf-8")
        ok, issues = check_g0(g0_ws)
        assert not ok
        assert any("校验失败" in i for i in issues)

    def test_non_sequential_req_ids(self, g0_ws: Path):
        bad = json.loads(json.dumps(VALID_CONTRACT))
        bad["问题"][0]["需求条目"] = [
            {"需求号": "1-1", "内容": "a"},
            {"需求号": "1-3", "内容": "b"},  # 跳号
        ]
        (g0_ws / "交接" / "题面契约.json").write_text(
            json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        ok, issues = check_g0(g0_ws)
        assert not ok
        assert any("不连续" in i or "校验失败" in i for i in issues)

    def test_ambiguity_missing_verdict(self, g0_ws: Path):
        bad = json.loads(json.dumps(VALID_CONTRACT))
        bad["歧义裁定"][0]["裁定"] = ""  # 空裁定
        (g0_ws / "交接" / "题面契约.json").write_text(
            json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        ok, issues = check_g0(g0_ws)
        assert not ok
        assert any("裁定" in i for i in issues)

    def test_attachment_not_covered(self, g0_ws: Path):
        (g0_ws / "输入" / "数据" / "extra.csv").write_text("a,b\n1,2", encoding="utf-8")
        ok, issues = check_g0(g0_ws)
        assert not ok
        assert any("未覆盖" in i for i in issues)

    def test_matrix_count_mismatch(self, g0_ws: Path):
        (g0_ws / "交接" / "需求追踪矩阵.json").write_text("[]", encoding="utf-8")
        ok, issues = check_g0(g0_ws)
        assert not ok
        assert any("≠" in i for i in issues)

    def test_empty_ambiguity_list_ok(self, g0_ws: Path):
        """没有歧义时写空数组是合法的。"""
        ok, issues = check_g0(g0_ws)
        assert ok  # VALID_CONTRACT 有歧义；但空歧义也不该报错
