

import pytest

# ==================== fs.read robustness (real-provider gate defect) ====================

@pytest.mark.asyncio
async def test_fs_read_directory_returns_tool_error_not_internal(tmp_path):
    """A model reading a DIRECTORY (common path guess) must get a clean
    tool-error result it can self-correct from — on Windows read_bytes(dir)
    raises PermissionError(13) which previously escaped as an unhandled
    internal error and killed the whole leg."""
    from mmagent.runtime.cancellation import CancellationToken
    from mmagent.tools.filesystem import FsReadTool
    from mmagent.tools.tool_protocol import ToolContext
    from mmagent.workspace.path_policy import PathPolicy
    from mmagent.workspace.permissions import PermissionChecker, RolePermissions

    policy = PathPolicy(tmp_path)
    (tmp_path / "输入" / "题目").mkdir(parents=True, exist_ok=True)
    ctx = ToolContext(
        policy=policy,
        permission=PermissionChecker(
            RolePermissions(role_id="t", read_scopes=("**",), write_scopes=()),
            policy,
        ),
        cancel=CancellationToken(),
    )
    result = await FsReadTool().execute({"path": "输入/题目"}, ctx)
    assert result.ok is False
    assert "无法读取" in result.error
