"""G4 paper gate and S4 narrative pre-gate.

This module implements the mechanically checkable core of the pinned G4
contract. Subjective writing quality remains with chapter/blind reviewers.
The implementation is intentionally fail-closed when required evidence such as
the audit report or compile log is absent.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from mmagent.mm.config.thresholds import DEFAULT_THRESHOLDS
from mmagent.tools.latex import LatexTool


def check_narrative(workspace_root: Path, problem_numbers: list[int]) -> tuple[bool, list[str]]:
    root = Path(workspace_root)
    path = root / "交接" / "叙事底稿.md"
    if not path.is_file():
        return False, ["交接/叙事底稿.md 缺失"]
    text = path.read_text(encoding="utf-8", errors="replace")
    issues: list[str] = []
    for q in problem_numbers:
        marker = f"## 问题{q}"
        start = text.find(marker)
        if start < 0:
            issues.append(f"叙事底稿缺 {marker}")
            continue
        next_heading = text.find("\n## 问题", start + len(marker))
        section = text[start: next_heading if next_heading >= 0 else len(text)]
        plain = re.sub(r"[#*_`>-]", "", section)
        if len(re.sub(r"\s+", "", plain)) < 150:
            issues.append(f"问题{q} 叙事不足 150 字")
    if re.search(r"\\begin\{|\\end\{|\$[^$]+\$", text):
        issues.append("叙事底稿含 LaTeX/公式标记")
    if re.search(r"\b[^\s]+\.(?:py|json|tex)\b", text):
        issues.append("叙事底稿含工程文件名")
    return not issues, issues


def _load_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _matrix_open_items(root: Path) -> int | None:
    data = _load_json(root / "交接" / "需求追踪矩阵.json")
    if not isinstance(data, list):
        return None
    closed = {"已落位", "已销号", "完成", "已完成"}
    return sum(1 for item in data if not isinstance(item, dict) or str(item.get("状态", "")) not in closed)


def check_g4(workspace_root: Path) -> tuple[bool, list[str]]:
    root = Path(workspace_root)
    issues: list[str] = []
    thresholds = DEFAULT_THRESHOLDS

    paper = root / "论文" / "论文.tex"
    abstract = root / "论文" / "0.摘要.tex"
    if not paper.is_file():
        issues.append("论文/论文.tex 缺失")
        return False, issues
    if not abstract.is_file():
        issues.append("论文/0.摘要.tex 缺失")

    tex_text = paper.read_text(encoding="utf-8", errors="replace")
    if "\\tableofcontents" in tex_text:
        issues.append("正文不得包含 \\tableofcontents")

    log_path = root / "论文" / "论文.log"
    if not log_path.is_file():
        issues.append("论文/论文.log 缺失（未完成编译验证）")
    else:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        errors = LatexTool.inspect_log_text(log_text)
        if errors:
            issues.append(f"编译错误 E={len(errors)}")
        pages = LatexTool.count_pages_text(log_text)
        if pages and pages > thresholds.max_body_pages:
            issues.append(f"正文页数超限: {pages} > {thresholds.max_body_pages}")

    audit = _load_json(root / "审稿" / "审计报告.json")
    if not isinstance(audit, dict):
        issues.append("审稿/审计报告.json 缺失或不可解析")
    else:
        forbidden = (audit.get("禁用词") or {}).get("数量", 0)
        if isinstance(forbidden, (int, float)) and forbidden > 0:
            issues.append(f"禁用词命中 {int(forbidden)} 处")
        overprecise = (audit.get("有效数字") or {}).get("过精数量", 0)
        if isinstance(overprecise, (int, float)) and overprecise > 0:
            issues.append(f"有效数字过精 {int(overprecise)} 处")
        trace = (audit.get("数字溯源") or {}).get("覆盖率")
        if not isinstance(trace, (int, float)):
            issues.append("审计报告缺数字溯源覆盖率")
        elif trace < thresholds.src_annotation_coverage:
            issues.append(
                f"% src 溯源覆盖率不足: {trace:.2f} < {thresholds.src_annotation_coverage:.2f}"
            )
        provenance = audit.get("溯源核验") or {}
        suspicious = provenance.get("存疑数", 0)
        unresolved = [
            x for x in (provenance.get("存疑明细") or [])
            if "已解释" not in json.dumps(x, ensure_ascii=False)
        ]
        if isinstance(suspicious, (int, float)) and suspicious > 0 and unresolved:
            issues.append(f"溯源核验仍有未解释项: {len(unresolved)}")

    open_items = _matrix_open_items(root)
    if open_items is None:
        issues.append("需求追踪矩阵缺失或不可解析")
    elif open_items:
        issues.append(f"需求追踪矩阵仍有 {open_items} 条未销号")

    return not issues, issues
