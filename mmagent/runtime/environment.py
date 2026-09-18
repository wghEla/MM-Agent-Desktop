"""Environment Manager：工具发现、能力缓存、体检（复现原 Skill 体检.sh/环境就绪.sh 语义）。

发现约定（KNOWN_DEVIATIONS #5/#6，按本机真实布局修正）：
- XeLaTeX：在根目录下**深度搜索** `**/bin/windows/xelatex.exe`（实际布局
  `D:/Apps/texlive/texlive/<年>/bin/windows/xelatex.exe`，比总方案初稿多一层）；
  多版本时选可解析版本号最新的；执行 `--version` 验证后写入 capability cache。
- MATLAB：兼容两种布局——`<root>/bin/matlab.exe`（本机实际：直接根目录安装）
  与 `<root>/R*/bin/matlab.exe`（版本化布局）。
- Agent 不自己猜工具路径；Environment 层负责发现并缓存。
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_TEXLIVE_ROOTS = ("D:/Apps/texlive", "C:/texlive")
_DEFAULT_MATLAB_ROOTS = ("D:/Apps/Matlab", "C:/Program Files/MATLAB")


@dataclass
class ToolCapability:
    name: str
    path: str | None
    version: str | None = None
    ok: bool = False
    detail: str = ""


@dataclass
class EnvironmentReport:
    xelatex: ToolCapability
    matlab: ToolCapability
    ghostscript: ToolCapability
    managed_python: ToolCapability
    disk_free_gb: float | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def hard_failures(self) -> list[str]:
        """硬失败项（对应原 Skill 体检：✗ 为硬失败，不得开炉）。"""
        bad = []
        if not self.xelatex.ok:
            bad.append("xelatex 未发现——论文无法编译")
        if not self.managed_python.ok:
            bad.append("受管 Python 不可用——求解脚本无法运行")
        return bad

    def warnings(self) -> list[str]:
        w = []
        if not self.matlab.ok:
            w.append("MATLAB 未发现——MATLAB 路线将在 G1 被排除（降级而非失败）")
        if not self.ghostscript.ok:
            w.append("ghostscript 未发现——PDF 页渲染可能受限")
        if self.disk_free_gb is not None and self.disk_free_gb < 20:
            w.append(f"磁盘剩余 {self.disk_free_gb:.1f} GB < 20 GB（一炉镜像约 1.5 GB + 日志 1 GB）")
        return w


def _run_version(args: list[str], timeout_s: float = 30.0) -> str:
    import subprocess

    try:
        p = subprocess.run(
            args, capture_output=True, timeout=timeout_s,
            stdin=subprocess.DEVNULL,
        )
        out = (p.stdout or b"") + (p.stderr or b"")
        return out.decode("utf-8", errors="replace").strip()[:300]
    except (OSError, subprocess.SubprocessError) as e:
        return f"(无法执行: {e})"


def discover_xelatex(roots: tuple[str, ...] = _DEFAULT_TEXLIVE_ROOTS) -> ToolCapability:
    """深度搜索 `**/bin/windows/xelatex.exe`，选版本最新的；执行 --version 验证。"""
    candidates: list[tuple[tuple[int, ...], Path]] = []
    for root_s in roots:
        root = Path(root_s)
        if not root.is_dir():
            continue
        for p in root.glob("**/bin/windows/xelatex.exe"):
            # 从路径解析年份版本（如 texlive/2026/...）
            m = re.search(r"(?:texlive[/\\])?(\d{4})", str(p))
            key = (int(m.group(1)),) if m else (0,)
            candidates.append((key, p))
    if not candidates:
        # PATH 兜底
        which = shutil.which("xelatex")
        if which:
            ver = _run_version([which, "--version"])
            return ToolCapability("xelatex", which, ver.splitlines()[0] if ver else None, True, ver[:120])
        return ToolCapability("xelatex", None, None, False, "未发现（搜索根 + PATH 均无）")
    candidates.sort(key=lambda c: c[0], reverse=True)
    best = candidates[0][1]
    ver = _run_version([str(best), "--version"])
    ok = "XeTeX" in ver or "xetex" in ver.lower()
    return ToolCapability("xelatex", str(best), ver.splitlines()[0] if ver else None, ok, ver[:120])


def discover_matlab(roots: tuple[str, ...] = _DEFAULT_MATLAB_ROOTS) -> ToolCapability:
    """双布局发现：`<root>/bin/matlab.exe`（直接根目录安装）与 `<root>/R*/bin/matlab.exe`。"""
    for root_s in roots:
        root = Path(root_s)
        if not root.is_dir():
            continue
        direct = root / "bin" / "matlab.exe"
        if direct.is_file():
            return ToolCapability("matlab", str(direct), None, True, "直接根目录布局")
        versioned = sorted(root.glob("R*/bin/matlab.exe"), reverse=True)
        if versioned:
            return ToolCapability(
                "matlab", str(versioned[0]), versioned[0].parent.parent.name, True, "版本化布局"
            )
    return ToolCapability("matlab", None, None, False, "未发现（MATLAB 路线将降级）")


def discover_ghostscript() -> ToolCapability:
    which = shutil.which("gswin64c") or shutil.which("gswin32c") or shutil.which("gs")
    if which:
        return ToolCapability("ghostscript", which, None, True, "")
    return ToolCapability("ghostscript", None, None, False, "未发现")


def managed_python() -> ToolCapability:
    """受管解释器 = 当前 venv 的 python（产品版由 %LOCALAPPDATA% 受管 runtime 提供）。"""
    import sys

    return ToolCapability("managed_python", sys.executable, f"{sys.version_info.major}.{sys.version_info.minor}", True, "")


def disk_free_gb(path: str | Path = ".") -> float | None:
    try:
        import shutil as _shutil

        return _shutil.disk_usage(str(path)).free / 1024**3
    except OSError:
        return None


def probe_all(workspace_root: str | Path | None = None) -> EnvironmentReport:
    """全量体检（体检.sh 语义）。workspace_root 给定时写入 capability cache。"""
    xelatex = discover_xelatex()
    matlab = discover_matlab()
    gs = discover_ghostscript()
    py = managed_python()
    free = disk_free_gb(workspace_root or ".")
    report = EnvironmentReport(xelatex=xelatex, matlab=matlab, ghostscript=gs, managed_python=py, disk_free_gb=free)
    if workspace_root:
        cache = Path(workspace_root) / ".mmagent" / "capabilities.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return report
