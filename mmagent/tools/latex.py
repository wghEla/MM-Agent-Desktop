"""XeLaTeX 工具：编译 / 日志检查 / 页数 / 页渲染。"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from mmagent.runtime.environment import discover_xelatex


class LatexTool:
    """XeLaTeX 编译器包装（工具发现由 EnvironmentManager 负责，Agent 不猜路径）。"""

    def __init__(self, workspace_root: Path, xelatex_path: str | None = None):
        self.root = workspace_root
        if xelatex_path:
            self.xelatex = xelatex_path
        else:
            cap = discover_xelatex()
            if not cap.ok or not cap.path:
                raise RuntimeError(f"XeLaTeX 未发现: {cap.detail}")
            self.xelatex = cap.path

    def compile(self, tex_file: str = "论文/论文.tex", *, timeout_s: float = 120.0) -> dict:
        """编译论文，返回 {"rc", "stdout_tail", "errors", "pages", "log_path"}。"""
        tex_path = self.root / tex_file
        if not tex_path.is_file():
            return {"rc": -1, "stdout_tail": "", "errors": [f"文件不存在: {tex_file}"], "pages": 0}
        workdir = tex_path.parent
        try:
            proc = subprocess.run(
                [self.xelatex, "-interaction=nonstopmode", "-synctex=1",
                 tex_path.name],
                cwd=str(workdir), capture_output=True, timeout=timeout_s,
                stdin=subprocess.DEVNULL,
            )
            rc = proc.returncode
            stdout = proc.stdout.decode("utf-8", errors="replace")[-5000:]
        except subprocess.TimeoutExpired:
            return {"rc": -2, "stdout_tail": "编译超时", "errors": ["超时"], "pages": 0}

        log_path = workdir / (tex_path.stem + ".log")
        errors, pages = [], 0
        if log_path.is_file():
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            errors = self.inspect_log_text(log_text)
            pages = self.count_pages_text(log_text)

        return {"rc": rc, "stdout_tail": stdout[-2000:], "errors": errors, "pages": pages,
                "log_path": str(log_path)}

    @staticmethod
    def inspect_log_text(log_text: str) -> list[str]:
        """从 .log 提取编译错误（E>0 行）。"""
        errors = []
        for m in re.finditer(r"^(.*?)\.(\d+): (.*?)$", log_text, re.MULTILINE):
            errors.append(f"{m.group(1)}:{m.group(2)}: {m.group(3)}")
        for m in re.finditer(r"! (.*?)$", log_text, re.MULTILINE):
            errors.append(f"! {m.group(1)}")
        return errors[:20]

    @staticmethod
    def count_pages_text(log_text: str) -> int:
        """从 .log 提取总页数。"""
        m = re.search(r"Output written on .*?\((\d+) pages?", log_text)
        return int(m.group(1)) if m else 0

    def page_count(self, tex_file: str = "论文/论文.tex") -> int:
        """获取上次编译的页数（不重新编译）。"""
        tex_path = self.root / tex_file
        log_path = tex_path.parent / (tex_path.stem + ".log")
        if not log_path.is_file():
            return 0
        return self.count_pages_text(log_path.read_text(encoding="utf-8", errors="replace"))



def render_pdf_pages(
    workspace_root: Path,
    pdf_file: str = "论文/论文.pdf",
    *,
    output_dir: str = "论文/页",
    dpi: int = 144,
) -> list[Path]:
    """Render the current paper PDF into deterministic PNG page images.

    This is a trusted runtime operation rather than an Agent-authored script.
    Existing page PNGs are removed first so reviewers cannot accidentally inspect
    stale pages from an older PDF revision.
    """
    if dpi < 72 or dpi > 300:
        raise ValueError("dpi must be between 72 and 300")

    import fitz

    root = Path(workspace_root)
    pdf_path = root / pdf_file
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF 不存在: {pdf_file}")

    out = root / output_dir
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()

    rendered: list[Path] = []
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    with fitz.open(pdf_path) as doc:
        for index, page in enumerate(doc, 1):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            path = out / f"page_{index:03d}.png"
            pix.save(path)
            rendered.append(path)
    return rendered
