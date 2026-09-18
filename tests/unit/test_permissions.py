"""路径策略与权限单测：逃逸拒绝 + 红队硬隔离（权限层，不是提示词）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from mmagent.agent.errors import PathEscape, PermissionDenied
from mmagent.workspace.path_policy import PathPolicy, normalize_rel
from mmagent.workspace.permissions import PermissionChecker, RolePermissions


@pytest.fixture
def policy(tmp_path: Path) -> PathPolicy:
    root = tmp_path / "ws"
    (root / "求解" / "问题1").mkdir(parents=True)
    (root / "交接").mkdir()
    (root / "求解" / "问题1" / "求解_问题1.py").write_text("print('secret')", encoding="utf-8")
    (root / "交接" / "题面契约.json").write_text("{}", encoding="utf-8")
    return PathPolicy(root)


class TestNormalize:
    def test_reject_dotdot(self):
        with pytest.raises(PathEscape):
            normalize_rel("求解/../../etc/passwd")

    def test_reject_absolute(self):
        with pytest.raises(PathEscape):
            normalize_rel("C:/Windows/system32/config")

    def test_reject_leading_slash(self):
        with pytest.raises(PathEscape):
            normalize_rel("/etc/passwd")

    def test_reject_backslash_dotdot(self):
        with pytest.raises(PathEscape):
            normalize_rel("求解\\..\\..\\x")

    def test_plain_ok(self):
        assert normalize_rel("交接/题面契约.json") == "交接/题面契约.json"


class TestPolicy:
    def test_resolve_within(self, policy: PathPolicy):
        p = policy.resolve("交接/题面契约.json", must_exist=True)
        assert p.is_file()

    def test_resolve_missing(self, policy: PathPolicy):
        with pytest.raises(FileNotFoundError):
            policy.resolve("交接/没有.json", must_exist=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows junction")
    def test_junction_escape_rejected(self, policy: PathPolicy, tmp_path: Path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("top secret", encoding="utf-8")
        junction = policy.root / "link"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            check=True, capture_output=True,
        )
        with pytest.raises(PathEscape):
            policy.resolve("link/secret.txt", must_exist=True)


class TestPermissions:
    def _checker(self, policy: PathPolicy, role: str = "red_team") -> PermissionChecker:
        # 复现上游红队的真实读权限：题面/数据/结果声明可见，建模代码/笔记不可见
        if role == "red_team":
            perms = RolePermissions(
                role_id="red_team",
                read_scopes=("输入/**", "交接/题面契约.json", "交接/数据档案.json", "交接/结果声明_问题{question}.json"),
                write_scopes=("求解/问题{question}/复算.py", "红队结果/**", "交接/红队_问题{question}.json"),
                allowed_tools=frozenset({"fs.read", "fs.write"}),
            )
        else:
            perms = RolePermissions(
                role_id="modeler",
                read_scopes=("输入/**", "交接/**"),
                write_scopes=("求解/**", "交接/**"),
                allowed_tools=frozenset({"fs.read", "fs.write", "python.run"}),
            )
        return PermissionChecker(perms.with_vars(question="1"), policy)

    def test_red_team_denied_solver(self, policy: PathPolicy):
        checker = self._checker(policy)
        with pytest.raises(PermissionDenied):
            checker.check_read("求解/问题1/求解_问题1.py")

    def test_red_team_allowed_contract(self, policy: PathPolicy):
        checker = self._checker(policy)
        checker.check_read("交接/题面契约.json")
        checker.check_read("交接/结果声明_问题1.json")

    def test_red_team_denied_write_outside_scope(self, policy: PathPolicy):
        checker = self._checker(policy)
        with pytest.raises(PermissionDenied):
            checker.check_write("求解/问题1/求解_问题1.py")

    def test_tool_whitelist_default_deny(self, policy: PathPolicy):
        checker = self._checker(policy)
        with pytest.raises(PermissionDenied):
            checker.check_tool("shell.exec")

    def test_double_star_scope(self, policy: PathPolicy):
        checker = self._checker(policy, role="modeler")
        checker.check_read("交接/题面契约.json")
        checker.check_read("输入/数据/附件.xlsx")  # 输入/** 允许（文件可以不存在，只查 scope）
