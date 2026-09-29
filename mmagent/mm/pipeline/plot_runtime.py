"""Trusted execution boundary for agent-authored plotting scripts."""
from __future__ import annotations

from mmagent.runtime.cancellation import CancellationToken
from mmagent.tools.registry import ToolRegistry
from mmagent.tools.tool_protocol import ToolContext
from mmagent.workspace.path_policy import PathPolicy
from mmagent.workspace.permissions import PermissionChecker, RolePermissions


async def run_question_plot_scripts(
    registry: ToolRegistry,
    policy: PathPolicy,
    question_num: int,
    *,
    cancel=None,
    timeout_s: int = 600,
) -> list[str]:
    """Run every 绘图_*.py for one question through the trusted Runtime.

    Plotter agents never receive host-code capability. They only author scripts;
    this function is the driver-owned execution boundary used by S3/S5b/S6.
    """
    scripts = sorted(policy.root.glob(f"求解/问题{question_num}/绘图_*.py"))
    if not scripts:
        return [f"问{question_num} 没有绘图脚本"]
    if not registry.has("python.run"):
        return ["ToolRegistry 缺 python.run，无法重新生成图片"]

    permissions = RolePermissions(
        role_id="plot_driver_executor",
        read_scopes=("求解/**", "输入/**", "交接/**"),
        write_scopes=("求解/**",),
        allowed_tools=frozenset({"python.run"}),
        host_code=True,
    )
    ctx = ToolContext(
        policy=policy,
        permission=PermissionChecker(permissions, policy),
        cancel=cancel or CancellationToken(),
    )

    issues: list[str] = []
    for script in scripts:
        rel = script.relative_to(policy.root).as_posix()
        result = await registry.invoke(
            "python.run", {"path": rel, "timeout_s": timeout_s}, ctx
        )
        if not result.ok:
            issues.append(f"{rel} 执行失败: {result.error}")
    return issues
