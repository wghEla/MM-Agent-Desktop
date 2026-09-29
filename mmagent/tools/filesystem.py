"""文件系统工具：fs.read / fs.write / fs.list。

所有路径先过角色权限（read/write scopes），再过 PathPolicy（工作区边界 + reparse 防护）。
"""
from __future__ import annotations

import json
from typing import Any

from mmagent.agent.errors import MMAgentError
from mmagent.tools.tool_protocol import Tool, ToolContext, ToolResult, ToolSpec
from mmagent.workspace.path_policy import join_posix

MAX_READ_BYTES = 256 * 1024


class FsReadTool(Tool):
    spec = ToolSpec(
        name="fs.read",
        description="读取工作区内文件内容（utf-8 文本）。超长截断。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "工作区相对路径"},
                "max_bytes": {"type": "integer", "minimum": 1, "maximum": MAX_READ_BYTES},
            },
            "required": ["path"],
        },
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        rel = str(args.get("path", ""))
        try:
            ctx.permission.check_read(rel)
            p = ctx.policy.resolve(rel, must_exist=True)
        except FileNotFoundError as e:
            return ToolResult(ok=False, error=str(e))
        except MMAgentError as e:
            return ToolResult(ok=False, error=str(e), meta={"denied": True})
        max_bytes = int(args.get("max_bytes") or MAX_READ_BYTES)
        try:
            data = p.read_bytes()[:max_bytes]
        except OSError as e:
            # 模型常把目录当文件读（Windows 上 read_bytes(目录) 抛
            # PermissionError(13)）；这必须是可回传给模型的工具错误，
            # 不能变成未捕获 internal 崩掉整条腿。
            return ToolResult(
                ok=False,
                error=f"无法读取（可能是目录或无权限）: {rel}: {e}",
                meta={"path": rel, "errno": e.errno},
            )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return ToolResult(
                ok=True,
                content=f"<binary {len(data)} bytes, 截断={len(data) == max_bytes}>",
                meta={"binary": True},
            )
        meta = {"truncated": p.stat().st_size > len(data)}
        return ToolResult(ok=True, content=text, meta=meta)


class FsWriteTool(Tool):
    spec = ToolSpec(
        name="fs.write",
        description="把 utf-8 文本写入工作区内文件（父目录自动创建；覆盖写）。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "工作区相对路径"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        rel = str(args.get("path", ""))
        content = str(args.get("content", ""))
        try:
            ctx.permission.check_write(rel)
            ctx.policy.ensure_parent(rel)
            p = ctx.policy.resolve(rel)
            p.write_text(content, encoding="utf-8", newline="\n")
        except MMAgentError as e:
            return ToolResult(ok=False, error=str(e), meta={"denied": True})
        except OSError as e:
            return ToolResult(ok=False, error=f"写入失败: {e}")
        return ToolResult(ok=True, content=f"已写入 {rel}（{len(content.encode('utf-8'))} bytes）")


class FsListTool(Tool):
    spec = ToolSpec(
        name="fs.list",
        description="列出工作区目录下的条目（相对路径，含类型与大小）。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "工作区相对目录，默认 ."},
            },
        },
    )

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        rel = str(args.get("path") or ".").strip()
        try:
            if rel in ("", "."):
                ctx.permission.check_read("**")
                d = ctx.policy.root
            else:
                ctx.permission.check_read(join_posix(rel, "**"))
                d = ctx.policy.resolve(rel, must_exist=True)
                if not d.is_dir():
                    return ToolResult(ok=False, error=f"不是目录: {rel}")
        except (MMAgentError, FileNotFoundError) as e:
            return ToolResult(ok=False, error=str(e), meta={"denied": isinstance(e, MMAgentError)})
        entries = []
        for child in sorted(d.iterdir()):
            crel = child.relative_to(ctx.policy.root).as_posix()
            kind = "dir" if child.is_dir() else "file"
            size = child.stat().st_size if child.is_file() else 0
            entries.append({"path": crel, "kind": kind, "size": size})
        return ToolResult(ok=True, content=json.dumps(entries, ensure_ascii=False, indent=1), meta={"count": len(entries)})
