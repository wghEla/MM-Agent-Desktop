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
                 "锦标赛": {"参赛路线": ["最小二乘"], "优胜": "最小二乘", "依据": "test"}},
            ],
            "叙事主线": "test",
        }
        (root / "交接" / "计划.json").write_text(json.dumps(plan), encoding="utf-8")
        # 原型脚本存在
        (root / "求解" / "问题1" / "原型_最小二乘.py").write_text("print(1)", encoding="utf-8")
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
