"""工具协议：ToolSpec / ToolResult / ToolContext。"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from mmagent.runtime.cancellation import CancellationToken
from mmagent.workspace.path_policy import PathPolicy
from mmagent.workspace.permissions import PermissionChecker


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    # 等价于宿主任意代码执行的工具必须置 True（外审 P0-3）：
    # 只有显式声明 host_code=True 的角色可用；声明即接受宿主级文件/网络/环境/子进程暴露。
    requires_host_code: bool = False


@dataclass
class ToolResult:
    ok: bool
    content: str = ""
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolContext:
    """一次工具执行的上下文：绑定工作区、当前角色权限、取消令牌。"""

    policy: PathPolicy
    permission: PermissionChecker
    cancel: CancellationToken
    task_id: str | None = None
    invocation_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Tool(abc.ABC):
    spec: ToolSpec

    @abc.abstractmethod
    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...
