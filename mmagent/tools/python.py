"""Python 执行工具：受管解释器跑工作区内的脚本。

语义复现（原 Skill run_script / P8）：
- 只用受管解释器（venv），不接受模型指定解释器路径；
- cwd = 工作区根；env 注入 MPLCONFIGDIR/MPLBACKEND（收进工作区，防缓存串味）；
- 超时 / 取消 → 杀整棵进程树（v0.1 用 taskkill /T，v0.2 换 Windows Job Object）；
- 失败返回结构化结果（stdout/stderr/rc），由上层决定修复回路，工具本身不抛业务异常。
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from typing import Any

from mmagent.agent.errors import MMAgentError
from mmagent.tools.tool_protocol import Tool, ToolContext, ToolResult, ToolSpec

_ENV_ALLOWLIST = (
    # Windows 运行必需
    "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "WINDIR", "PROGRAMDATA",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "COMMONPROGRAMFILES", "APPDATA", "LOCALAPPDATA",
    # POSIX 基本项
    "HOME", "USER", "LANG", "LC_ALL", "TMPDIR",
    # 数学建模科学栈偶尔需要的运行库提示（显式列出而非整体继承）
    "PROJ_LIB", "GDAL_DATA", "GEOTIFF_CSV",
)


def _minimal_env(workspace_root) -> dict[str, str]:
    env: dict[str, str] = {}
    for k in _ENV_ALLOWLIST:
        v = os.environ.get(k)
        if v:
            env[k] = v
    env.setdefault("MPLBACKEND", "Agg")
    mpl_dir = workspace_root / ".cache" / "mpl"
    try:
        mpl_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        mpl_dir = workspace_root
    env["MPLCONFIGDIR"] = str(mpl_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PATH"] = os.environ.get("PATH", os.defpath)
    # PATH 中过滤掉任何包含敏感关键词的目录是做不到的——PATH 本身是运行必需，
    # 这里保留系统 PATH 但不继承其余变量（PYTHON* 全部不继承，防注入）。
    return env


def _kill_tree(pid: int) -> None:
    """Windows 下杀整棵进程树；POSIX 杀进程组。"""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
                check=False,
            )
        else:
            import signal as _signal

            os.killpg(pid, _signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass


class PythonRunTool(Tool):
    spec = ToolSpec(
        name="python.run",
        description=(
            "用受管 Python 解释器运行工作区内的 .py 脚本（cwd=工作区根）。"
            "返回 rc/stdout/stderr。禁止 pip install；依赖缺失要报告而不是自行安装。"
            "注意：运行 Python 等价于宿主任意代码执行（requires_host_code）。"
        ),
        requires_host_code=True,
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "工作区内脚本相对路径"},
                "timeout_s": {"type": "integer", "minimum": 1, "maximum": 3600, "default": 600},
            },
            "required": ["path"],
        },
    )

    def __init__(self, interpreter: str | None = None, process_manager=None):
        # 受管解释器：默认当前 venv 的 python（产品版由 Environment Manager 提供）
        self.interpreter = interpreter or sys.executable
        # v0.2：ProcessManager——提供时进程纳入 Windows Job Object（KILL_ON_JOB_CLOSE）
        self.process_manager = process_manager

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        rel = str(args.get("path", ""))
        timeout_s = float(args.get("timeout_s") or 600)
        try:
            ctx.permission.check_read(rel)
            script = ctx.policy.resolve(rel, must_exist=True)
        except FileNotFoundError as e:
            return ToolResult(ok=False, error=str(e))
        except MMAgentError as e:
            return ToolResult(ok=False, error=str(e), meta={"denied": True})
        if not str(script).lower().endswith(".py"):
            return ToolResult(ok=False, error=f"只允许运行 .py 文件: {rel}")

        # 最小环境白名单（外审 P0-3）：不继承完整 os.environ，
        # 只保留解释器与 Windows 运行必需项 + 科学栈必需项，防宿主密钥经环境泄漏。
        env = _minimal_env(ctx.policy.root)

        started = time.monotonic()
        if self.process_manager is not None:
            # v0.2 路径：Windows Job Object 管理（杀树 + KILL_ON_JOB_CLOSE 崩溃兜底）
            import uuid as _uuid

            mp = self.process_manager.spawn(
                f"py_{_uuid.uuid4().hex[:10]}",
                [self.interpreter, "-X", "utf8", str(script)],
                cwd=str(ctx.policy.root),
                env=env,
            )
            from mmagent.agent.errors import ToolTimeout

            try:
                rc, out_b, err_b, timed_out = await asyncio.to_thread(
                    self.process_manager.communicate, mp, timeout_s, ctx.cancel
                )
            except ToolTimeout as e:
                self.process_manager.recycle(mp.name)
                return ToolResult(
                    ok=False,
                    error=f"脚本超时（>{timeout_s:.0f}s），Job 树已终止：{e}",
                    meta={"rc": None, "timed_out": True, "rel_path": rel, "detail": str(e)},
                )
            except Exception:
                self.process_manager.recycle(mp.name)
                raise
            elapsed = time.monotonic() - started
            stdout = out_b.decode("utf-8", errors="replace")
            stderr = err_b.decode("utf-8", errors="replace")
            ok = (rc == 0) and not timed_out
            limit = 20_000
            self.process_manager.recycle(mp.name)
            meta: dict[str, Any] = {"rc": rc, "elapsed_s": round(elapsed, 1), "rel_path": rel,
                    "stdout_tail": stdout[-2000:], "stderr_tail": stderr[-2000:]}
            if timed_out:
                meta["timed_out"] = True
                return ToolResult(
                    ok=False,
                    error=f"脚本超时（>{timeout_s:.0f}s），已终止进程树",
                    meta=meta,
                )
            return ToolResult(
                ok=ok,
                content=(
                    f"rc={rc} elapsed={elapsed:.1f}s\n--- stdout ---\n{stdout[-limit:]}\n"
                    f"--- stderr ---\n{stderr[-limit:]}"
                ),
                error=None if ok else f"脚本退出码 {rc}",
                meta=meta,
            )
        proc = await asyncio.create_subprocess_exec(
            self.interpreter,
            "-X",
            "utf8",
            str(script),
            cwd=str(ctx.policy.root),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            # POSIX tree termination uses killpg(proc.pid); create a dedicated
            # session/process group so timeout/cancel cannot silently miss.
            start_new_session=(os.name != "nt"),
        )
        ctx.cancel.on_cancel(lambda: _kill_tree(proc.pid))

        async def _wait() -> tuple[bytes, bytes]:
            out, err = b"", b""
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            except TimeoutError:
                _kill_tree(proc.pid)
                await proc.wait()
                raise
            return out, err

        try:
            out, err = await _wait()
        except TimeoutError:
            return ToolResult(
                ok=False,
                error=f"脚本超时（>{timeout_s:.0f}s），已终止进程树",
                meta={"rc": None, "timed_out": True, "rel_path": rel},
            )
        except asyncio.CancelledError:
            _kill_tree(proc.pid)
            raise
        elapsed = time.monotonic() - started
        rc = proc.returncode
        stdout = out.decode("utf-8", errors="replace")
        stderr = err.decode("utf-8", errors="replace")
        limit = 20_000
        ok = rc == 0
        return ToolResult(
            ok=ok,
            content=(
                f"rc={rc} elapsed={elapsed:.1f}s\n--- stdout ---\n{stdout[-limit:]}\n"
                f"--- stderr ---\n{stderr[-limit:]}"
            ),
            error=None if ok else f"脚本退出码 {rc}",
            meta={"rc": rc, "elapsed_s": round(elapsed, 1), "rel_path": rel,
                  "stdout_tail": stdout[-2000:], "stderr_tail": stderr[-2000:]},
        )
