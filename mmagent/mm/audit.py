"""Deterministic paper audit used by G4/G5.

This is a clean-room, intentionally conservative audit. It does not attempt to
replace human review; it produces mechanically checkable evidence for the gates.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_FORBIDDEN_TERMS = (
    "作为AI",
    "作为 AI",
    "提示词",
    "prompt",
    "AgentLoop",
    "内部流程",
)

_DECIMAL_TOO_PRECISE = re.compile(r"(?<![\w.])[-+]?\d+\.\d{5,}(?!\d)")
_NUMBER = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?:%|‰)?(?![\w.])")


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def audit_paper(workspace_root: Path) -> dict:
    """Scan TeX sources and write 审稿/审计报告.json."""
    root = Path(workspace_root)
    tex_dir = root / "论文"
    tex_files = sorted(p for p in tex_dir.glob("*.tex") if p.is_file())
    texts: list[tuple[Path, str]] = []
    for path in tex_files:
        try:
            texts.append((path, path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue

    forbidden_details: list[dict[str, str]] = []
    overprecise: list[dict[str, str]] = []
    numeric_paragraphs = 0
    traced_numeric_paragraphs = 0
    untraced: list[dict[str, str | int]] = []

    for path, text in texts:
        rel = path.relative_to(root).as_posix()
        for term in _FORBIDDEN_TERMS:
            if term.lower() in text.lower():
                forbidden_details.append({"文件": rel, "词": term})
        for match in _DECIMAL_TOO_PRECISE.finditer(text):
            overprecise.append({"文件": rel, "数字": match.group(0)})
        for index, paragraph in enumerate(_paragraphs(text), 1):
            if not _NUMBER.search(paragraph):
                continue
            numeric_paragraphs += 1
            if "% src:" in paragraph or "%src:" in paragraph:
                traced_numeric_paragraphs += 1
            else:
                untraced.append({"文件": rel, "段": index})

    coverage = 1.0 if numeric_paragraphs == 0 else traced_numeric_paragraphs / numeric_paragraphs
    report = {
        "禁用词": {"数量": len(forbidden_details), "明细": forbidden_details},
        "有效数字": {"过精数量": len(overprecise), "明细": overprecise},
        "数字溯源": {
            "覆盖率": round(coverage, 4),
            "含数字段": numeric_paragraphs,
            "有源段": traced_numeric_paragraphs,
        },
        "溯源核验": {
            "存疑数": len(untraced),
            "存疑明细": untraced,
        },
    }
    out = root / "审稿" / "审计报告.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
