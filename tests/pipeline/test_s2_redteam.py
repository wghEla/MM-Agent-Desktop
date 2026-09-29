"""S2 建模求解 + 红队独立复算 + G2 门检（mock provider 级测试）。

核心测试：红队硬隔离（权限层拒绝读建模代码）+ G2 判据 + DAG 分层执行。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.agent.errors import PermissionDenied
from mmagent.orchestration.dag import build_dependency_graph, topological_layers
from mmagent.workspace.permissions import PermissionChecker, RolePermissions


class TestRedTeamIsolation:
    """红队权限层硬隔离：必须 PermissionDenied，不是提示词约束。"""

    def _make_ws(self, tmp_path: Path) -> Path:
        root = tmp_path / "ws"
        (root / "求解" / "问题1").mkdir(parents=True)
        (root / "交接").mkdir()
        (root / "求解" / "问题1" / "求解_问题1.py").write_text("print('secret')", encoding="utf-8")
        (root / "交接" / "建模笔记_问题1.md").write_text("notes", encoding="utf-8")
        (root / "交接" / "题面契约.json").write_text("{}", encoding="utf-8")
        (root / "交接" / "结果声明_问题1.json").write_text("{}", encoding="utf-8")
        return root

    def _policy(self, root: Path):
        from mmagent.workspace.path_policy import PathPolicy
        return PathPolicy(root)

    def test_red_team_denied_solver(self, tmp_path: Path):
        root = self._make_ws(tmp_path)
        checker = self._checker(root)
        with pytest.raises(PermissionDenied):
            checker.check_read("求解/问题1/求解_问题1.py")

    def test_red_team_denied_notes(self, tmp_path: Path):
        root = self._make_ws(tmp_path)
        checker = self._checker(root)
        with pytest.raises(PermissionDenied):
            checker.check_read("交接/建模笔记_问题1.md")

    def test_red_team_allowed_contract(self, tmp_path: Path):
        root = self._make_ws(tmp_path)
        checker = self._checker(root)
        checker.check_read("交接/题面契约.json")
        checker.check_read("交接/结果声明_问题1.json")

    def test_red_team_allowed_write_scope(self, tmp_path: Path):
        root = self._make_ws(tmp_path)
        checker = self._checker(root)
        checker.check_write("求解/问题1/复算.py")
        checker.check_write("交接/红队_问题1.json")

    def _checker(self, root: Path) -> PermissionChecker:
        rt = RolePermissions(
            role_id="red_team",
            read_scopes=("输入/**", "交接/题面契约.json", "交接/数据档案.json",
                         "交接/结果声明_问题{question}.json"),
            write_scopes=("求解/问题{question}/复算.py", "求解/问题{question}/红队结果/**",
                          "交接/红队_问题{question}.json"),
            allowed_tools=frozenset({"fs.read", "fs.write"}),
        )
        return PermissionChecker(rt.with_vars(question="1"), self._policy(root))


class TestG2Gate:
    """G2 门检：核心指标非空 + 红队结论对齐 + 仲裁台账结清。"""

    def _make_result(self, tmp_path: Path, metrics: dict) -> Path:
        root = tmp_path / "ws"
        (root / "求解" / "问题1" / "结果").mkdir(parents=True, exist_ok=True)
        (root / "交接").mkdir(exist_ok=True)
        (root / "求解" / "问题1" / "结果" / "结果.json").write_text(
            json.dumps(metrics, ensure_ascii=False), encoding="utf-8")
        (root / "交接" / "结果声明_问题1.json").write_text(
            json.dumps({"问题编号": 1, "核心指标": metrics}, ensure_ascii=False), encoding="utf-8")
        return root

    def test_g2_pass_when_aligned(self, tmp_path: Path):
        root = self._make_result(tmp_path, {"厚度": 2.17})
        (root / "交接" / "红队_问题1.json").write_text(
            json.dumps({"问题编号": 1, "结论": "对齐", "分歧明细": []}, ensure_ascii=False),
            encoding="utf-8")
        ok, issues = self._g2(root)
        assert ok, issues

    def test_g2_fail_when_misaligned(self, tmp_path: Path):
        root = self._make_result(tmp_path, {"厚度": 2.17})
        (root / "交接" / "红队_问题1.json").write_text(
            json.dumps({"问题编号": 1, "结论": "不齐",
                        "分歧明细": [{"键": "厚度", "声明值": 2.17, "复算值": 2.50, "相对差": 0.15}]},
                       ensure_ascii=False), encoding="utf-8")
        ok, issues = self._g2(root)
        assert not ok

    def test_g2_fail_empty_metrics(self, tmp_path: Path):
        root = self._make_result(tmp_path, {})
        (root / "交接" / "红队_问题1.json").write_text(
            json.dumps({"问题编号": 1, "结论": "对齐"}, ensure_ascii=False), encoding="utf-8")
        ok, issues = self._g2(root)
        assert not ok
        assert any("核心指标" in i for i in issues)

    def _g2(self, root: Path) -> tuple[bool, list[str]]:
        """简化 G2 检查（完整版在 v0.5 后续实现）。"""
        issues: list[str] = []
        decl_path = root / "交接" / "结果声明_问题1.json"
        if not decl_path.is_file():
            return False, ["结果声明缺失"]
        decl = json.loads(decl_path.read_text(encoding="utf-8"))
        if not decl.get("核心指标"):
            issues.append("核心指标为空（答案门教训）")
        rt_path = root / "交接" / "红队_问题1.json"
        if rt_path.is_file():
            rt = json.loads(rt_path.read_text(encoding="utf-8"))
            if rt.get("结论") == "不齐":
                issues.append("红队结论不齐")
        return (len(issues) == 0), issues


class TestDAGLayers:
    def test_topological_parallel(self):
        g = build_dependency_graph([
            {"编号": 1, "依赖问题": []},
            {"编号": 2, "依赖问题": []},
            {"编号": 3, "依赖问题": [1, 2]},
        ])
        layers = topological_layers(g)
        assert layers[0] == [1, 2]  # 前两层可并行
        assert layers[1] == [3]


# ==================== G2 门检模块测试 ====================
class TestG2GateModule:
    """mmagent/mm/gates/g2.py 的门检模块。"""

    def _setup(self, tmp_path: Path, *, metrics=None, red_metrics=None, arb=None):
        from mmagent.mm.gates.g2 import normalize_red_team_report

        root = tmp_path / "g2"
        (root / "求解" / "问题1" / "红队结果").mkdir(parents=True)
        (root / "交接").mkdir()
        (root / "求解" / "问题1" / "求解_问题1.py").write_text(
            "print(1)", encoding="utf-8"
        )
        m = metrics if metrics is not None else {"厚度": 2.17}
        red = red_metrics if red_metrics is not None else dict(m)
        (root / "交接" / "结果声明_问题1.json").write_text(
            json.dumps({"问题编号": 1, "核心指标": m}), encoding="utf-8"
        )
        (root / "求解" / "问题1" / "红队结果" / "复算.json").write_text(
            json.dumps(red), encoding="utf-8"
        )
        # Deliberately let the model carrier claim alignment; Runtime owns the verdict.
        (root / "交接" / "红队_问题1.json").write_text(
            json.dumps({"问题编号": 1, "结论": "对齐", "分歧明细": []}),
            encoding="utf-8",
        )
        normalize_red_team_report(root, 1)
        if arb is not None:
            (root / "交接" / "仲裁_问题1.json").write_text(
                json.dumps(arb), encoding="utf-8"
            )
        return root

    def test_pass_aligned(self, tmp_path):
        from mmagent.mm.gates.g2 import check_g2
        root = self._setup(tmp_path)
        ok, issues = check_g2(root, 1)
        assert ok, issues

    def test_fail_empty_metrics(self, tmp_path):
        from mmagent.mm.gates.g2 import check_g2
        root = self._setup(tmp_path, metrics={})
        ok, issues = check_g2(root, 1)
        assert not ok
        assert any("核心指标" in i for i in issues)

    def test_fail_rt_misaligned(self, tmp_path):
        from mmagent.mm.gates.g2 import check_g2
        root = self._setup(tmp_path, red_metrics={"厚度": 2.50})
        ok, issues = check_g2(root, 1)
        assert not ok
        assert any("不齐" in i for i in issues)

    def test_fail_missing_solver(self, tmp_path):
        from mmagent.mm.gates.g2 import check_g2
        root = self._setup(tmp_path)
        (root / "求解" / "问题1" / "求解_问题1.py").unlink()
        ok, issues = check_g2(root, 1)
        assert not ok
        assert any("缺失" in i for i in issues)

    def test_arb_unresolved_blocked(self, tmp_path):
        from mmagent.mm.gates.g2 import check_g2
        arb = {"逐项": [{"条目": "口径X", "应改方": "建模", "消解状态": "待处理"}]}
        root = self._setup(tmp_path, arb=arb)
        ok, issues = check_g2(root, 1)
        assert not ok
        assert any("待处理" in i for i in issues)

    def test_arb_resolved_ok(self, tmp_path):
        from mmagent.mm.gates.g2 import check_g2
        arb = {"逐项": [{"条目": "口径X", "应改方": "建模", "消解状态": "已消解"}]}
        root = self._setup(tmp_path, arb=arb)
        ok, issues = check_g2(root, 1)
        assert ok, issues
