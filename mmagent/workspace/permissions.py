"""角色权限：Default deny + read/write scopes + allowed tools + host_code 高权限位。

核心承诺（总方案 §21/§34；v0.1.0 外审 P0-3/P1-8/P2-6 修复后强化）：
- 红队禁读建模代码必须在权限层拒绝，而不是提示词里写"不要看"；
- `python.run` 这类**等价于宿主任意代码执行**的工具被标记 requires_host_code：
  角色必须显式声明 host_code=True 才能获得；声明即视为接受
  "该角色可访问宿主进程可及的文件/网络/环境/子进程"（真实 OS 级沙箱在 v0.2 Job Object）；
- scope 模板变量（`{question}`）必须校验：只允许安全字面段，禁止 glob 元字符
  （变量不得改变权限规则本身，外审 P1-8）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from mmagent.agent.errors import PermissionDenied
from mmagent.workspace.path_policy import PathPolicy, normalize_rel

# 模板变量合法值：安全字面段（数字/中文/字母/下划线/连字符），不含 glob 元字符与分隔符
_VAR_VALUE_RE = re.compile(r"^[\w\u4e00-\u9fff\-]+$", re.UNICODE)


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """支持 `**`（跨段）、`*`（单段内）、`?`（单字符）的工作区 glob。"""
    pat = pattern.replace("\\", "/")
    out: list[str] = []
    i = 0
    while i < len(pat):
        c = pat[i]
        if c == "*":
            if pat[i : i + 3] == "**/":
                out.append("(?:[^/]+/)*")
                i += 3
            elif pat[i : i + 2] == "**":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


@dataclass(frozen=True)
class RolePermissions:
    """角色权限声明。scopes 支持 `{question}` 等模板变量，由 with_vars() 解析。

    host_code=True 表示该角色允许运行"等价于宿主任意代码执行"的工具
    （见 ToolSpec.requires_host_code）。默认 False：默认 deny。
    """

    role_id: str
    read_scopes: tuple[str, ...] = ()
    write_scopes: tuple[str, ...] = ()
    allowed_tools: frozenset[str] = field(default_factory=frozenset)
    network: bool = False
    shell: bool = False
    host_code: bool = False

    def with_vars(self, **vars: str) -> RolePermissions:
        """解析 scope 模板变量。变量值必须是安全字面段，否则拒绝（glob injection 防线）。"""
        for k, v in vars.items():
            if not v or not _VAR_VALUE_RE.match(v):
                raise ValueError(
                    f"scope 模板变量 {k}={v!r} 非法：变量必须是不含 glob 元字符/分隔符的字面段"
                )

        def sub(patterns: tuple[str, ...]) -> tuple[str, ...]:
            out = []
            for p in patterns:
                s = p
                for k, v in vars.items():
                    s = s.replace("{" + k + "}", v)
                out.append(s)
            return tuple(out)

        return RolePermissions(
            role_id=self.role_id,
            read_scopes=sub(self.read_scopes),
            write_scopes=sub(self.write_scopes),
            allowed_tools=self.allowed_tools,
            network=self.network,
            shell=self.shell,
            host_code=self.host_code,
        )


class PermissionChecker:
    """绑定角色权限与路径策略的检查器；默认 deny。"""

    def __init__(self, perms: RolePermissions, policy: PathPolicy):
        self.perms = perms
        self.policy = policy
        self._read_res = [_glob_to_regex(p) for p in perms.read_scopes]
        self._write_res = [_glob_to_regex(p) for p in perms.write_scopes]

    # ------------------------------------------------------------- 内部
    def _match(self, regexes: list[re.Pattern[str]], rel: str) -> bool:
        reln = normalize_rel(rel)
        return any(r.match(reln) for r in regexes)

    # ------------------------------------------------------------- 检查
    def check_read(self, rel: str) -> None:
        if not self._match(self._read_res, rel):
            raise PermissionDenied(
                f"角色 {self.perms.role_id} 无读取权限: {rel}",
                detail={"scope_kind": "read", "path": rel},
            )
        self._resolve_if_concrete(rel)

    def check_write(self, rel: str) -> None:
        if not self._match(self._write_res, rel):
            raise PermissionDenied(
                f"角色 {self.perms.role_id} 无写入权限: {rel}",
                detail={"scope_kind": "write", "path": rel},
            )
        self._resolve_if_concrete(rel)

    def _resolve_if_concrete(self, rel: str) -> None:
        """scope 匹配后，仅对**具体路径**（无 glob 元字符）做边界解析；
        含 * / ? 的匹配串是模式不是路径，不进入 PathPolicy。"""
        if "*" in rel or "?" in rel:
            return
        self.policy.resolve(rel, must_exist=False)

    def check_tool(self, tool_name: str, *, requires_host_code: bool = False) -> None:
        if tool_name not in self.perms.allowed_tools:
            raise PermissionDenied(
                f"角色 {self.perms.role_id} 无工具权限: {tool_name}",
                detail={"tool": tool_name},
            )
        if requires_host_code and not self.perms.host_code:
            raise PermissionDenied(
                f"工具 {tool_name} 等价于宿主任意代码执行，"
                f"角色 {self.perms.role_id} 未显式声明 host_code 能力",
                detail={"tool": tool_name, "host_code": False},
            )

    def can_read(self, rel: str) -> bool:
        """完整 boolean 语义：任何 policy 拒绝（含 PathEscape）都返回 False（外审 P2-6）。"""
        try:
            self.check_read(rel)
            return True
        except Exception:
            return False
