"""17 角色注册表完整性测试。"""
from __future__ import annotations

import pytest

from mmagent.mm.config.thresholds import ROLE_REASONING_TIERS
from mmagent.mm.roles.registry import all_roles, get_role, role_ids
from mmagent.workspace.permissions import PermissionChecker, RolePermissions


def test_seventeen_roles_exist():
    assert len(role_ids()) == 17
    expected = {
        "reader", "answer_predictor", "planner", "modeler", "red_team", "interpreter",
        "plotter", "figure_reviewer", "writer", "chapter_reviewer", "blind_reader",
        "integrator", "reviewer", "defect_hunter", "judge_simulator", "beautifier",
        "retrospector",
    }
    assert set(role_ids()) == expected


def test_all_roles_have_valid_tiers():
    for r in all_roles():
        assert r.reasoning in {"low", "medium", "high", "xhigh"}, r.role_id
        assert r.role_id in ROLE_REASONING_TIERS


def test_tier_assignment_matches_spec():
    assert get_role("modeler").reasoning == "xhigh"
    assert get_role("red_team").reasoning == "xhigh"
    assert get_role("writer").reasoning == "high"
    assert get_role("blind_reader").reasoning == "medium"
    assert get_role("retrospector").reasoning == "medium"


def test_red_team_isolation_shape():
    """红队 read_scopes 不含建模代码路径；modeler 有 host_code，红队没有。"""
    rt = get_role("red_team")
    assert not rt.host_code
    assert not any("建模笔记" in s or "结果解读" in s for s in rt.read_scopes)
    assert not any(s.startswith("求解/**") for s in rt.read_scopes)
    m = get_role("modeler")
    assert m.host_code
    assert "python.run" in m.allowed_tools
    assert "python.run" not in rt.allowed_tools


def test_role_permissions_integration(policy):
    """注册表权限走真实 PermissionChecker：红队读不到建模代码（端到端）。"""
    (policy.root / "求解" / "问题1").mkdir(parents=True, exist_ok=True)
    (policy.root / "求解" / "问题1" / "求解_问题1.py").write_text("x=1", encoding="utf-8")
    (policy.root / "输入" / "题目").mkdir(parents=True, exist_ok=True)
    (policy.root / "输入" / "题目" / "题.pdf").write_bytes(b"%PDF")
    rt = get_role("red_team").permissions(question="1")
    checker = PermissionChecker(rt, policy)
    from mmagent.agent.errors import PermissionDenied

    with pytest.raises(PermissionDenied):
        checker.check_read("求解/问题1/求解_问题1.py")
    checker.check_read("输入/题目/题.pdf")
    checker.check_write("求解/问题1/复算.py")
    # host_code 门：同角色但未声明 host_code 的变体，即使工具在白名单也被拒
    nohc = RolePermissions(
        role_id="modeler_nohc",
        read_scopes=("**",),
        write_scopes=("**",),
        allowed_tools=frozenset({"python.run"}),
        host_code=False,
    )
    mchecker = PermissionChecker(nohc, policy)
    with pytest.raises(PermissionDenied, match="host_code"):
        mchecker.check_tool("python.run", requires_host_code=True)
