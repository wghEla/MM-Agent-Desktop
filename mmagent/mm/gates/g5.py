"""G5 publication gate: G4 + ledger convergence + stale-value + page guard."""
from __future__ import annotations

import json
from pathlib import Path

from mmagent.mm.contracts.degraded_release import is_issue_degraded
from mmagent.mm.gates.g4 import check_g4
from mmagent.mm.guards.guards import page_guard, stale_value_guard

_BLOCKING = {"硬伤", "正确性"}
_ACTIVE = {"待改", "待复核", "未消解"}


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check_g5(
    workspace_root: Path,
    *,
    beauty_baseline_pages: int | None = None,
    current_pages: int | None = None,
) -> tuple[bool, list[str]]:
    """Mechanical publication checks.

    Blocking shelved issues require an explicit degraded-release record in
    交接/降级放行.json containing their ids; otherwise publication fails closed.
    """
    root = Path(workspace_root)
    ok4, issues = check_g4(root)
    issues = list(issues)

    ledger = _load_json(root / "台账" / "审稿台账.json")
    if not isinstance(ledger, list):
        issues.append("台账/审稿台账.json 缺失或不可解析")
    else:
        for item in ledger:
            if not isinstance(item, dict) or item.get("级别") not in _BLOCKING:
                continue
            state = str(item.get("状态", ""))
            iid = str(item.get("id", "?"))
            if state in _ACTIVE:
                issues.append(f"阻塞级台账未收敛: {iid} {item.get('级别')}/{state}")
            elif state == "搁置":
                generation = item.get("generation")
                try:
                    generation_i = int(generation)
                except (TypeError, ValueError):
                    issues.append(f"阻塞级搁置缺有效 generation: {iid}")
                    continue
                if not is_issue_degraded(root, iid, generation_i):
                    issues.append(
                        f"阻塞级搁置未登记精确降级放行: {iid} generation={generation_i}"
                    )

    stale_ok, stale_issues = stale_value_guard(root)
    if not stale_ok:
        issues.extend(stale_issues)

    if beauty_baseline_pages is not None:
        if current_pages is None or current_pages <= 0:
            issues.append("G5 无法取得返工后页数")
        else:
            page_ok, detail = page_guard(
                beauty_baseline_pages, current_pages, baseline=beauty_baseline_pages
            )
            if not page_ok:
                issues.append(detail)

    return bool(ok4 and not issues), issues
