"""pytest 公共夹具。

Windows 注意：Database 必须在 tmp_path 清理前 close（WAL 文件锁），fixture 负责收尾。
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from mmagent.api import projects
from mmagent.api.projects import ProjectHandle


@pytest.fixture
def ws(tmp_path: Path) -> Iterator[ProjectHandle]:
    handle = projects.create_project(tmp_path / "proj", name="测试项目", profile="standard")
    yield handle
    handle.workspace.db.close()


@pytest.fixture
def db(ws: ProjectHandle):
    return ws.workspace.db


@pytest.fixture
def run_id(ws: ProjectHandle) -> str:
    from mmagent.state import repositories

    return repositories.create_run(ws.workspace.db, project_id=ws.project_id, profile="standard")


@pytest.fixture
def policy(ws: ProjectHandle):
    from mmagent.workspace.path_policy import PathPolicy

    return PathPolicy(ws.workspace.root)
