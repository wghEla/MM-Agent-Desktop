"""G2 per-question mechanical gate and red-team evidence verification."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmagent.mm.config.thresholds import DEFAULT_THRESHOLDS


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def mechanical_red_team_verdict(
    workspace_root: Path,
    question_num: int,
    *,
    tolerance: float = DEFAULT_THRESHOLDS.red_team_relative_tolerance,
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    """Compare frozen headline metrics with the red-team script output.

    The LLM-authored report may explain a genuine definition/scope difference,
    but it cannot decide the numeric pass/fail by writing "结论=对齐".

    A mismatch may be classified as a non-blocking 口径 difference only when:
    - the report contains a discrepancy for that exact key with 类型=口径; and
    - 口径对照 contains the same key with both 声明口径 and 独立口径 non-empty.
    """
    root = Path(workspace_root)
    decl_path = root / "交接" / f"结果声明_问题{question_num}.json"
    red_result_path = root / "求解" / f"问题{question_num}" / "红队结果" / "复算.json"
    report_path = root / "交接" / f"红队_问题{question_num}.json"

    issues: list[str] = []
    try:
        decl = json.loads(decl_path.read_text(encoding="utf-8"))
        declared = decl.get("核心指标") or {}
    except (OSError, json.JSONDecodeError) as exc:
        return False, [], [f"结果声明不可解析: {exc}"]
    try:
        recomputed = json.loads(red_result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, [], [f"红队复算证据缺失或不可解析: {exc}"]
    if not isinstance(declared, dict) or not declared:
        return False, [], ["核心指标为空"]
    if not isinstance(recomputed, dict):
        return False, [], ["红队复算.json 顶层必须为对象"]

    report: dict[str, Any] = {}
    try:
        raw = json.loads(report_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            report = raw
    except (OSError, json.JSONDecodeError):
        pass

   口径_keys: set[str] = set()
    raw_discrepancies = report.get("分歧明细") or []
    if isinstance(raw_discrepancies, list):
        for item in raw_discrepancies:
            if isinstance(item, dict) and item.get("类型") == "口径" and item.get("键"):
                口径_keys.add(str(item["键"]))

    evidenced_scope_keys: set[str] = set()
    raw_scope = report.get("口径对照") or []
    if isinstance(raw_scope, list):
        for item in raw_scope:
            if not isinstance(item, dict):
                continue
            key = str(item.get("键") or "")
            if (
                key
                and str(item.get("声明口径") or "").strip()
                and str(item.get("独立口径") or "").strip()
            ):
                evidenced_scope_keys.add(key)

    discrepancies: list[dict[str, Any]] = []
    blocking = False
    for key, declared_raw in declared.items():
        declared_value = _number(declared_raw)
        if declared_value is None:
            issues.append(f"核心指标 {key!r} 不是数值，无法机械复核")
            blocking = True
            continue
        if key not in recomputed:
            discrepancies.append({
                "键": key,
                "声明值": declared_value,
                "复算值": None,
                "相对差": 1.0,
                "类型": "数值",
                "机械结论": "红队结果缺键",
            })
            blocking = True
            continue
        red_value = _number(recomputed.get(key))
        if red_value is None:
            discrepancies.append({
                "键": key,
                "声明值": declared_value,
                "复算值": None,
                "相对差": 1.0,
                "类型": "数值",
                "机械结论": "红队值非数值",
            })
            blocking = True
            continue

        if declared_value == 0.0:
            relative = 0.0 if red_value == 0.0 else 1.0
        else:
            relative = abs(red_value - declared_value) / abs(declared_value)

        if relative > tolerance:
            scope_evidenced = key in 口径_keys and key in evidenced_scope_keys
            kind = "口径" if scope_evidenced else "数值"
            discrepancies.append({
                "键": key,
                "声明值": declared_value,
                "复算值": red_value,
                "相对差": relative,
                "类型": kind,
                "机械结论": "口径差已举证" if scope_evidenced else "超出容差",
            })
            if not scope_evidenced:
                blocking = True

    passed = not blocking and not issues
    return passed, discrepancies, issues


def normalize_red_team_report(
    workspace_root: Path,
    question_num: int,
    *,
    tolerance: float = DEFAULT_THRESHOLDS.red_team_relative_tolerance,
) -> tuple[bool, list[str]]:
    """Rewrite only mechanically-owned fields of the red-team carrier."""
    root = Path(workspace_root)
    path = root / "交接" / f"红队_问题{question_num}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    passed, discrepancies, issues = mechanical_red_team_verdict(
        root, question_num, tolerance=tolerance
    )
    raw["问题编号"] = question_num
    raw["结论"] = "对齐" if passed else "不齐"
    raw["分歧明细"] = discrepancies
    raw["机械复核"] = {
        "容差": tolerance,
        "通过": passed,
        "issues": issues,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return passed, issues


def check_g2(workspace_root: Path, question_num: int) -> tuple[bool, list[str]]:
    """G2 per-question gate. Returns (pass, issues)."""
    issues: list[str] = []
    root = Path(workspace_root)
    q = f"问题{question_num}"

    decl_path = root / "交接" / f"结果声明_问题{question_num}.json"
    if not decl_path.is_file():
        return False, [f"{q} 结果声明缺失"]
    try:
        decl = json.loads(decl_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"{q} 结果声明不可解析: {exc}"]
    metrics = decl.get("核心指标") or {}
    if not metrics:
        issues.append(f"{q} 核心指标为空（答案门教训：不能空放行）")

    rt_path = root / "交接" / f"红队_问题{question_num}.json"
    if not rt_path.is_file():
        issues.append(f"{q} 红队报告缺失")
    else:
        try:
            rt = json.loads(rt_path.read_text(encoding="utf-8"))
            mechanical = rt.get("机械复核") or {}
            if not isinstance(mechanical, dict) or "通过" not in mechanical:
                issues.append(f"{q} 红队报告缺机械复核证据")
            elif not mechanical.get("通过"):
                issues.append(f"{q} 红队机械复核不齐")
            conclusion = rt.get("结论", "")
            if conclusion != ("对齐" if mechanical.get("通过") else "不齐"):
                issues.append(f"{q} 红队结论与机械复核不一致")
        except Exception as exc:
            issues.append(f"{q} 红队报告不可解析: {exc}")

    arb_path = root / "交接" / f"仲裁_问题{question_num}.json"
    if arb_path.is_file():
        try:
            arb = json.loads(arb_path.read_text(encoding="utf-8"))
            for item in arb.get("逐项", []):
                if item.get("应改方", "").startswith("建模"):
                    status = item.get("消解状态", "待处理")
                    if status not in ("已消解", "已解释"):
                        issues.append(
                            f"{q} 仲裁条目 {item.get('条目', '?')!r} "
                            f"消解状态={status!r}（须已消解/已解释）"
                        )
        except Exception as exc:
            issues.append(f"{q} 仲裁台账不可解析: {exc}")

    solver = root / "求解" / f"问题{question_num}" / f"求解_问题{question_num}.py"
    if not solver.is_file():
        issues.append(f"{q} 求解脚本缺失")

    exp_path = root / "交接" / "实验记录.json"
    if exp_path.is_file():
        try:
            exps = json.loads(exp_path.read_text(encoding="utf-8"))
            if not isinstance(exps, list):
                issues.append("实验记录顶层须为数组")
        except Exception as exc:
            issues.append(f"实验记录不可解析: {exc}")

    return (len(issues) == 0), issues
