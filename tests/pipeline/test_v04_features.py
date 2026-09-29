"""S1 原型执行 + 三档 profiles + Dashboard API 测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmagent.api.dashboard import dashboard, list_projects, list_runs, record_gate_result
from mmagent.mm.config.profiles import get_profile
from mmagent.mm.pipeline.s0_s1 import check_g1


class TestProfiles:
    def test_three_tiers(self):
        from mmagent.mm.config.profiles import all_profiles
        assert set(all_profiles().keys()) == {"深度", "标准", "快速"}

    def test_deep_profile(self):
        p = get_profile("深度")
        assert p.每问路线数 == 3
        assert p.摘要变体数 == 5
        assert p.审稿轮数 == 4
        assert p.max_hours == 40.0
        assert not p.角色分档

    def test_standard_profile(self):
        p = get_profile("标准")
        assert p.摘要变体数 == 3
        assert p.审稿轮数 == 3
        assert p.max_hours == 30.0
        assert p.角色分档  # 标准档启用角色分档

    def test_quick_profile(self):
        p = get_profile("快速")
        assert not p.全问开锦标赛
        assert p.每问路线数 == 2
        assert p.审稿轮数 == 2
        assert p.max_hours == 20.0

    def test_unknown_tier(self):
        with pytest.raises(ValueError, match="未知档位"):
            get_profile("超级")


class TestDashboard:
    def test_list_projects(self, ws):
        result = list_projects(ws.workspace.db)
        assert len(result) >= 1
        assert result[0]["name"] == "测试项目"

    def test_list_runs(self, ws, run_id):
        result = list_runs(ws.workspace.db, ws.project_id)
        assert len(result) >= 1
        assert result[0]["id"] == run_id

    def test_dashboard_shape(self, ws, db, run_id):
        from mmagent.state import repositories
        from mmagent.state.models import TaskStatus

        t = repositories.create_task(db, run_id=run_id, stage_key="S0", node_key="S0.2", role_id="reader")
        repositories.transition_task(db, t.id, TaskStatus.READY)
        record_gate_result(db, run_id, "G0", True, [])
        d = dashboard(ws.workspace, run_id)
        assert d["run_id"] == run_id
        assert d["tasks"][0]["node"] == "S0.2"
        assert d["gates"][0]["gate"] == "G0"
        assert d["gates"][0]["pass"] is True

    def test_dashboard_nonexistent_run(self, ws):
        with pytest.raises(LookupError):
            dashboard(ws.workspace, "run_nonexistent")


class TestS1Prototype:
    """S1 原型路线执行测试（真实 python.run 执行小样）。"""

    def test_g1_with_prototype_evidence(self, tmp_path: Path):
        """G1 检查原型脚本存在（证据文件）。"""
        root = tmp_path / "proj"
        (root / "交接").mkdir(parents=True)
        (root / "求解" / "问题1").mkdir(parents=True)
        plan = {
            "问题清单": [
                {"编号": 1, "主方法": "最小二乘", "依赖问题": [],
                 "锦标赛": {"参赛路线": ["最小二乘", "稳健拟合", "岭回归"], "优胜": "最小二乘", "依据": "test"}},
            ],
            "叙事主线": "test",
        }
        (root / "交接" / "路线侦察.json").write_text(
            json.dumps({"问题清单": [{"编号": 1, "路线": [
                {"路线名": "最小二乘", "方法": "最小二乘"},
                {"路线名": "稳健拟合", "方法": "稳健拟合"},
                {"路线名": "岭回归", "方法": "岭回归"},
            ]}]}),
            encoding="utf-8",
        )
        (root / "交接" / "原型结果.json").write_text(
            json.dumps({"条目": [
                {"问题编号": 1, "路线名": "最小二乘", "脚本": "求解/问题1/原型_1.py", "rc": 0},
                {"问题编号": 1, "路线名": "稳健拟合", "脚本": "求解/问题1/原型_2.py", "rc": 0},
                {"问题编号": 1, "路线名": "岭回归", "脚本": "求解/问题1/原型_3.py", "rc": 0},
            ]}),
            encoding="utf-8",
        )
        (root / "交接" / "计划.json").write_text(json.dumps(plan), encoding="utf-8")
        ok, issues = check_g1(root)
        assert ok, issues


# ==================== v0.6.0 XeLaTeX/MATLAB 工具测试 ====================
class TestLatexTool:
    def test_page_count_from_log(self, tmp_path: Path):
        from mmagent.tools.latex import LatexTool
        log = tmp_path / "论文.log"
        log.write_text("Output written on 论文.pdf (18 pages).", encoding="utf-8")
        assert LatexTool.count_pages_text(log.read_text()) == 18

    def test_errors_from_log(self, tmp_path: Path):
        from mmagent.tools.latex import LatexTool
        log = tmp_path / "test.log"
        log.write_text("! Undefined control sequence.\nl.5 \badcmd\n", encoding="utf-8")
        errors = LatexTool.inspect_log_text(log.read_text())
        assert len(errors) >= 1
        assert any("Undefined" in e for e in errors)

    def test_real_xelatex_discovery(self):
        from mmagent.runtime.environment import discover_xelatex
        cap = discover_xelatex()
        if cap.ok:
            assert "xelatex" in (cap.path or "").lower()


class TestMatlabTool:
    def test_real_matlab_discovery(self):
        from mmagent.runtime.environment import discover_matlab
        cap = discover_matlab()
        if cap.ok:
            assert "matlab" in (cap.path or "").lower()
            import pathlib
            assert pathlib.Path(cap.path).is_file()

    def test_run_script_missing(self, tmp_path: Path):
        from mmagent.runtime.environment import discover_matlab
        from mmagent.tools.matlab import MatlabTool
        cap = discover_matlab()
        if not cap.ok:
            pytest.skip("MATLAB not available")
        tool = MatlabTool(tmp_path, matlab_path=cap.path)
        result = tool.run_script("nonexistent.m")
        assert result["rc"] == -1


# ==================== v0.7.0 守卫测试 ====================
class TestChangeGuard:
    def test_small_change_passes(self):
        from mmagent.mm.guards.guards import change_guard
        old = "这是第一句。这是第二句。这是第三句。"
        new = "这是第一句。这是修改后的第二句。这是第三句。"
        ok, ratio, detail = change_guard(old, new, [])
        assert ok

    def test_wholesale_rewrite_blocked(self):
        from mmagent.mm.guards.guards import change_guard
        old = "完全不同的第一段内容。" * 20
        new = "彻底重写的全新段落。" * 20
        ok, ratio, _ = change_guard(old, new, [])
        assert not ok

    def test_named_changes_exempt(self):
        from mmagent.mm.guards.guards import change_guard
        old = "这段关于公式一。这段关于公式二。这段关于公式三。"
        new = "公式一已更新。这段关于公式二。这段关于公式三。"
        items = [{"问题": "修改\u201c公式一\u201d那段", "指令": "更新公式一"}]
        ok, ratio, _ = change_guard(old, new, items)
        assert ok  # 点名处改动不计入


class TestStructureGuard:
    def test_input_removed_blocked(self):
        from mmagent.mm.guards.guards import structure_guard
        old = {"main.tex": "\\input{ch1}\n\\input{ch2}"}
        new = {"main.tex": r"\input{ch1}"}
        ok, issues = structure_guard(old, new)
        assert not ok
        assert any("ch2" in i for i in issues)

    def test_empty_file_blocked(self):
        from mmagent.mm.guards.guards import structure_guard
        old = {"ch1.tex": "\\section{引言}\n内容"}
        new = {"ch1.tex": ""}
        ok, issues = structure_guard(old, new)
        assert not ok


class TestPageGuard:
    def test_normal_growth_ok(self):
        from mmagent.mm.guards.guards import page_guard
        ok, _ = page_guard(20, 22)
        assert ok

    def test_excessive_growth_blocked(self):
        from mmagent.mm.guards.guards import page_guard
        ok, _ = page_guard(20, 30)
        assert not ok

    def test_sudden_drop_warned(self):
        from mmagent.mm.guards.guards import page_guard
        ok, _ = page_guard(20, 10)
        assert not ok  # 骤降告警


# ==================== v0.7.0 Repair receipt schemas ====================
class TestRepairReceiptSchemas:
    def test_repair_receipt_valid(self):
        from mmagent.mm.contracts.repair_receipts import RepairReceipt
        r = RepairReceipt(id="审-1-01", 改动="修复了数值", 证据="论文/ch3.tex:15", receipt_id="r1")
        assert r.id == "审-1-01"
        assert r.generation == 0

    def test_repair_receipt_empty_change_rejected(self):
        from pydantic import ValidationError

        from mmagent.mm.contracts.repair_receipts import RepairReceipt
        with pytest.raises(ValidationError):
            RepairReceipt(id="审-1-01", 改动="")

    def test_beauty_receipt_target(self):
        from mmagent.mm.contracts.repair_receipts import BeautyReceipt
        r = BeautyReceipt(id="美-1-01", 目标="图", 改动="重绘图3")
        assert r.目标 == "图"

    def test_g5_repair_receipt(self):
        from mmagent.mm.contracts.repair_receipts import G5RepairReceipt
        r = G5RepairReceipt(id="G5-1", 目标="算", 改动="重算")
        assert r.目标 == "算"

    def test_s6_terminal_receipt_page(self):
        from mmagent.mm.contracts.repair_receipts import S6TerminalReceipt
        r = S6TerminalReceipt(id="S6-1", 页码=3, 改动="排版修复")
        assert r.页码 == 3

    def test_generation_defaults_zero(self):
        from mmagent.mm.contracts.repair_receipts import RepairReceipt
        r = RepairReceipt(id="x", 改动="y")
        assert r.generation == 0


# ==================== G5 Rework R49-R52 tests ====================
class TestG5Rework:
    def test_g5_rework_import(self):
        from mmagent.mm.pipeline.s5_finalize import run_g5_rework
        assert callable(run_g5_rework)

    @pytest.mark.asyncio
    async def test_g5_rework_no_blocking_passes(self, tmp_path: Path):
        """No blocking issues → G5 passes on first check, no rework needed."""
        from mmagent.api.projects import create_project
        from mmagent.mm.pipeline.s5_finalize import run_g5_rework
        from mmagent.providers.mock import MockProvider, MockScript, MockTurn
        from mmagent.state import repositories
        from mmagent.tools.filesystem import FsReadTool, FsWriteTool
        from mmagent.tools.registry import ToolRegistry
        from mmagent.workspace.path_policy import PathPolicy

        reg = ToolRegistry()
        reg.register(FsReadTool())
        reg.register(FsWriteTool())

        root = tmp_path / "g5r"
        handle = create_project(root, name="t")
        db = handle.workspace.db
        policy = PathPolicy(root)
        run_id = repositories.create_run(db, project_id=handle.project_id, profile="标准")
        (root / "论文").mkdir(exist_ok=True)
        (root / "论文" / "论文.tex").write_text(r"\documentclass{article}", encoding="utf-8")

        provider = MockProvider(MockScript([MockTurn(text="done")]))
        result = await run_g5_rework(
            db, provider, reg, policy, run_id,
            beauty_baseline_pages=10, cancel=None,
        )
        assert "rework_rounds" in result
        db.close()

    @pytest.mark.asyncio
    async def test_g5_rework_calc_shelved(self, tmp_path: Path):
        """R50: 算类阻塞在 G5 被搁置（不重算）。"""
        from mmagent.mm.ledger.issue_ledger import IssueLedger
        ledger = IssueLedger(前缀="审")
        ledger.并入([{"问题": "需要重算", "级别": "正确性", "目标": "算"}], 轮次=1)
        assert not ledger.收敛()[0]  # blocked
        # G5: shelve 算条
        for x in ledger.待改条目(级别们=["正确性"]):
            if x.目标 == "算":
                ledger.搁置条目(x.id, "G5 无算路")
        # 搁置后阻塞级仍算 blocked
        ok, _ = ledger.收敛()
        assert not ok  # 搁置的正确性仍不算收敛（G5 降级放行）


# ==================== S6 Retrospective schemas ====================
class TestRetrospectiveSchemas:
    def test_retrospective_report_valid(self):
        from mmagent.mm.contracts.s6_contracts import RetrospectiveReport
        r = RetrospectiveReport(
            总评="整体质量良好",
            瓶颈环节=[{"环节": "S2 红队", "次数": 3, "耗时占比": 0.3}],
            回流账={"仲裁": 3, "编译失败": 2},
            质量指标={"章评均分": 7.5},
        )
        assert r.总评 == "整体质量良好"

    def test_run_metrics_valid(self):
        from mmagent.mm.contracts.s6_contracts import RunMetrics
        m = RunMetrics(total_legs=100, gates_passed=5, gates_failed=1)
        assert m.total_legs == 100

    def test_run_metrics_negative_rejected(self):
        from pydantic import ValidationError

        from mmagent.mm.contracts.s6_contracts import RunMetrics
        with pytest.raises(ValidationError):
            RunMetrics(total_legs=-1)

    def test_bottleneck_duration_range(self):
        from pydantic import ValidationError

        from mmagent.mm.contracts.s6_contracts import RetrospectiveBottleneck
        with pytest.raises(ValidationError):
            RetrospectiveBottleneck(环节="S3", 次数=1, 耗时占比=1.5)


class TestG4AbstractPage:
    def test_abstract_page_check_in_g4(self, tmp_path: Path):
        """G4 检查摘要恰好 1 页（aux abstract:end 标签）。"""
        from mmagent.mm.gates.g4 import check_g4
        root = tmp_path / "g4abs"
        (root / "论文").mkdir(parents=True)
        (root / "论文" / "论文.tex").write_text(r"\documentclass{article}", encoding="utf-8")
        (root / "论文" / "0.摘要.tex").write_text("摘要内容", encoding="utf-8")
        (root / "论文" / "论文.log").write_text(
            "Output written on 论文.pdf (18 pages).", encoding="utf-8")
        (root / "论文" / "论文.aux").write_text(
            "\newlabel{abstract:end}{{}{1}}", encoding="utf-8")
        (root / "审稿").mkdir(exist_ok=True)
        (root / "审稿" / "审计报告.json").write_text("{}", encoding="utf-8")
        (root / "交接").mkdir(exist_ok=True)
        (root / "交接" / "需求追踪矩阵.json").write_text("[]", encoding="utf-8")
        ok, issues = check_g4(root)
        # Abstract page 1 is OK, other issues may exist
        assert not any("摘要" in i for i in issues), issues

    def test_abstract_page_2_fails(self, tmp_path: Path):
        from mmagent.mm.gates.g4 import check_g4
        root = tmp_path / "g4abs2"
        (root / "论文").mkdir(parents=True)
        (root / "论文" / "论文.tex").write_text(r"\documentclass{article}", encoding="utf-8")
        (root / "论文" / "0.摘要.tex").write_text("摘要内容", encoding="utf-8")
        (root / "论文" / "论文.log").write_text(
            "Output written on 论文.pdf (18 pages).", encoding="utf-8")
        (root / "论文" / "论文.aux").write_text(
            "\newlabel{abstract:end}{{}{2}}", encoding="utf-8")
        (root / "审稿").mkdir(exist_ok=True)
        (root / "审稿" / "审计报告.json").write_text("{}", encoding="utf-8")
        (root / "交接").mkdir(exist_ok=True)
        (root / "交接" / "需求追踪矩阵.json").write_text("[]", encoding="utf-8")
        ok, issues = check_g4(root)
        assert any("摘要不是恰好 1 页" in i for i in issues), issues
