"""G3 figure-evidence gate.

Clean-room implementation of the pinned paper-foundry mechanical checks:
- 16–22 rendered PNG figures
- at least 3 mechanism/schematic drawing scripts
- bar + line plot share <= 1/2 of detected chart kinds
- no non-schematic chart kind appears in more than 3 plotting scripts
- figure-caption material exists

This gate deliberately checks only mechanically observable evidence. Visual
quality remains the figure-reviewer responsibility.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from mmagent.mm.config.thresholds import DEFAULT_THRESHOLDS

_KIND_PATTERNS: dict[str, re.Pattern[str]] = {
    "bar": re.compile(r"\\.(?:bar|barh)\\s*\\("),
    "line": re.compile(r"\\.plot\\s*\\("),
    "scatter": re.compile(r"\\.scatter\\s*\\("),
    "heatmap": re.compile(r"\\.(?:imshow|pcolormesh)\\s*\\("),
    "box": re.compile(r"\\.boxplot\\s*\\("),
    "pie": re.compile(r"\\.pie\\s*\\("),
    "area": re.compile(r"\\.(?:fill_between|stackplot)\\s*\\("),
    "hist": re.compile(r"\\.hist\\s*\\("),
    "schematic": re.compile(r"FancyArrowPatch|FancyBboxPatch|add_patch\\s*\\("),
}


def _plot_kind_counts(root: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    for script in root.glob("求解/**/绘图_*.py"):
        try:
            source = script.read_text(encoding="utf-8")
        except OSError:
            continue
        for kind, pattern in _KIND_PATTERNS.items():
            if pattern.search(source):
                counts[kind] += 1
    return counts


def check_g3(workspace_root: Path) -> tuple[bool, list[str]]:
    """Return (passed, issues) for the figure-evidence gate."""
    root = Path(workspace_root)
    issues: list[str] = []
    thresholds = DEFAULT_THRESHOLDS

    pngs = [p for p in root.glob("求解/**/图片/*.png") if p.is_file()]
    if len(pngs) < thresholds.figures_min:
        issues.append(f"图数不足: {len(pngs)} < {thresholds.figures_min}")
    if len(pngs) > thresholds.figures_max:
        issues.append(f"图数超额: {len(pngs)} > {thresholds.figures_max}")

    counts = _plot_kind_counts(root)
    if counts["schematic"] < 3:
        issues.append(f"机理/示意图脚本不足: {counts['schematic']} < 3")

    total_kinds = sum(counts.values())
    if total_kinds == 0:
        issues.append("未检测到绘图脚本中的图型证据")
    else:
        bar_line_share = (counts["bar"] + counts["line"]) / total_kinds
        if bar_line_share > 0.5:
            issues.append(f"柱状+折线占比过高: {bar_line_share:.2f} > 0.50")

    for kind, count in counts.items():
        if kind != "schematic" and count > 3:
            issues.append(f"同型图脚本过多: {kind}={count} > 3")

    caption_material = [p for p in (root / "交接").glob("图注素材*.json") if p.is_file()]
    if not caption_material:
        issues.append("交接/图注素材*.json 缺失")

    return not issues, issues
