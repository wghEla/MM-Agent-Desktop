"""MATLAB 工具：发现 + batch 执行。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from mmagent.runtime.environment import discover_matlab


class MatlabTool:
    """MATLAB batch 执行器（发现由 EnvironmentManager 负责）。"""

    def __init__(self, workspace_root: Path, matlab_path: str | None = None):
        self.root = workspace_root
        if matlab_path:
            self.matlab = matlab_path
        else:
            cap = discover_matlab()
            if not cap.ok or not cap.path:
                raise RuntimeError(f"MATLAB 未发现: {cap.detail}")
            self.matlab = cap.path

    def run_batch(self, command: str, *, timeout_s: float = 300.0) -> dict:
        """matlab.exe -batch 执行（headless）。"""
        try:
            proc = subprocess.run(
                [self.matlab, "-batch", command],
                cwd=str(self.root), capture_output=True, timeout=timeout_s,
                stdin=subprocess.DEVNULL,
            )
            return {
                "rc": proc.returncode,
                "stdout": proc.stdout.decode("utf-8", errors="replace")[-5000:],
                "stderr": proc.stderr.decode("utf-8", errors="replace")[-2000:],
            }
        except subprocess.TimeoutExpired:
            return {"rc": -2, "stdout": "", "stderr": "超时"}
        except OSError as e:
            return {"rc": -1, "stdout": "", "stderr": str(e)}

    def run_script(self, script_path: str, *, timeout_s: float = 300.0) -> dict:
        """运行 .m 脚本。"""
        abs_path = self.root / script_path
        if not abs_path.is_file():
            return {"rc": -1, "stdout": "", "stderr": f"脚本不存在: {script_path}"}
        return self.run_batch(f"run('{abs_path}')", timeout_s=timeout_s)
