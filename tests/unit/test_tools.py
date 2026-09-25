"""工具注册表与文件工具单测。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from mmagent.runtime.cancellation import CancellationToken
from mmagent.runtime.environment import managed_python
from mmagent.tools.filesystem import FsListTool, FsReadTool, FsWriteTool
from mmagent.tools.latex import LatexTool, render_pdf_pages
from mmagent.tools.matlab import MatlabTool
from mmagent.tools.python import PythonRunTool
from mmagent.tools.registry import ToolRegistry
from mmagent.tools.tool_protocol import ToolContext


def _ctx(policy, checker) -> ToolContext:
    return ToolContext(policy=policy, permission=checker, cancel=CancellationToken())


def _checker(policy, scopes=("**",), tools=("fs.read", "fs.write", "fs.list")):
    from mmagent.workspace.permissions import PermissionChecker, RolePermissions

    perms = RolePermissions(
        role_id="t",
        read_scopes=tuple(scopes),
        write_scopes=tuple(scopes),
        allowed_tools=frozenset(tools),
    )
    return PermissionChecker(perms, policy)


def _registry() -> ToolRegistry:
    r = ToolRegistry()
    for t in (FsReadTool(), FsWriteTool(), FsListTool()):
        r.register(t)
    return r


def test_fs_list_root_and_subdir(policy, ws):
    (ws.workspace.root / "求解" / "问题1").mkdir(parents=True, exist_ok=True)
    (ws.workspace.root / "求解" / "问题1" / "s.py").write_text("print(1)", encoding="utf-8")
    checker = _checker(policy)
    reg = _registry()
    res = asyncio.run(reg.invoke("fs.list", {}, _ctx(policy, checker)))
    assert res.ok and res.meta["count"] >= 1
    res2 = asyncio.run(reg.invoke("fs.list", {"path": "求解"}, _ctx(policy, checker)))
    assert res2.ok
    entries = json.loads(res2.content)
    assert any(e["path"] == "求解/问题1" for e in entries)


def test_unknown_tool_denied(policy):
    checker = _checker(policy)
    result = asyncio.run(_registry().invoke("nope.tool", {}, _ctx(policy, checker)))
    assert result.ok is False and result.meta.get("denied")


def test_duplicate_registration_rejected(policy):
    reg = _registry()
    with pytest.raises(ValueError):
        reg.register(FsReadTool())


def test_fs_write_then_read_roundtrip(policy):
    checker = _checker(policy)
    reg = _registry()
    w = asyncio.run(reg.invoke("fs.write", {"path": "交接/a.json", "content": "{\"k\":1}"}, _ctx(policy, checker)))
    assert w.ok
    r = asyncio.run(reg.invoke("fs.read", {"path": "交接/a.json"}, _ctx(policy, checker)))
    assert r.ok and json.loads(r.content) == {"k": 1}



def test_latex_missing_executable_returns_structured_failure(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    paper = root / "论文"
    paper.mkdir(parents=True)
    (paper / "论文.tex").write_text("\\documentclass{article}", encoding="utf-8")

    result = LatexTool(root, xelatex_path=str(root / "missing-xelatex")).compile()

    assert result["rc"] == -1
    assert result["pages"] == 0
    assert any("启动失败" in item for item in result["errors"])


def test_matlab_missing_executable_returns_structured_failure(tmp_path: Path) -> None:
    result = MatlabTool(
        tmp_path, matlab_path=str(tmp_path / "missing-matlab")
    ).run_batch("disp(1)")

    assert result["rc"] == -1
    assert result["stdout"] == ""
    assert result["stderr"]


def test_corrupt_pdf_render_fails_with_runtime_error(tmp_path: Path) -> None:
    paper = tmp_path / "论文"
    paper.mkdir(parents=True)
    (paper / "论文.pdf").write_bytes(b"not-a-pdf")

    with pytest.raises(RuntimeError, match="PDF 页渲染失败"):
        render_pdf_pages(tmp_path)



def test_python_tool_prefers_explicit_managed_runtime(monkeypatch, tmp_path: Path) -> None:
    managed = tmp_path / ("python.exe" if __import__("os").name == "nt" else "python")
    managed.write_bytes(b"placeholder")
    monkeypatch.setenv("MMAGENT_PYTHON", str(managed))

    tool = PythonRunTool()

    assert tool.interpreter == str(managed)


def test_environment_reports_missing_configured_managed_runtime(
    monkeypatch, tmp_path: Path
) -> None:
    missing = tmp_path / "missing-python.exe"
    monkeypatch.setenv("MMAGENT_PYTHON", str(missing))

    capability = managed_python()

    assert capability.ok is False
    assert capability.path == str(missing)
    assert "不存在" in capability.detail
