"""工具注册表：权限检查点统一在这里，任何绕过注册表的工具调用都是实现错误。"""
from __future__ import annotations

import json
from typing import Any

from mmagent.agent.errors import PermissionDenied
from mmagent.providers.normalized import NormalizedTool
from mmagent.tools.tool_protocol import Tool, ToolContext, ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.spec.name in self._tools:
            raise ValueError(f"工具重复注册: {tool.spec.name}")
        self._tools[tool.spec.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def normalized_tools(self, allowed: frozenset[str] | None = None) -> list[NormalizedTool]:
        """导出为 provider 协议工具定义；allowed 限定可见集（角色工具白名单）。"""
        out = []
        for name, t in self._tools.items():
            if allowed is not None and name not in allowed:
                continue
            out.append(
                NormalizedTool(name=name, description=t.spec.description, parameters=t.spec.parameters)
            )
        return out

    async def invoke(self, name: str, args: dict[str, Any] | str, ctx: ToolContext) -> ToolResult:
        # 1) 角色工具白名单（default deny）+ host_code 高权限检查
        try:
            tool_spec = self._tools.get(name)
            ctx.permission.check_tool(
                name, requires_host_code=bool(tool_spec and tool_spec.spec.requires_host_code)
            )
        except PermissionDenied as e:
            return ToolResult(ok=False, error=str(e), meta={"denied": True})
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, error=f"未知工具: {name}", meta={"denied": True})
        # 2) 参数 JSON 解析失败也要返回结构化错误（模型可在下一轮修复，而不是崩掉整个任务）
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError as e:
                return ToolResult(ok=False, error=f"工具参数不是合法 JSON: {e}")
        if not isinstance(args, dict):
            return ToolResult(ok=False, error="工具参数必须是 JSON 对象")
        ctx.cancel.check()
        # 3) 执行（工具内部再做路径/范围级权限检查）
        return await tool.execute(args, ctx)
