"""G2 门检（每问）：核心指标非空 + 红队结论对齐 + 仲裁台账结清。

复现上游 门检.py G2 函数语义（SOURCE_MAP §2 G2 行）。
"""
from __future__ import annotations

import json
from pathlib import Path


def check_g2(workspace_root: Path, question_num: int) -> tuple[bool, list[str]]:
    """G2 每问门检。返回 (pass, issues)。"""
    issues: list[str] = []
    root = Path(workspace_root)
    q = f"问题{question_num}"

    # 1) 结果声明存在且核心指标非空（答案门教训：不能空放行）
    decl_path = root / "交接" / f"结果声明_问题{question_num}.json"
    if not decl_path.is_file():
        return False, [f"{q} 结果声明缺失"]
    try:
        decl = json.loads(decl_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, [f"{q} 结果声明不可解析: {e}"]
    metrics = decl.get("核心指标") or {}
    if not metrics:
        issues.append(f"{q} 核心指标为空（答案门教训：不能空放行）")

    # 2) 红队报告存在且结论对齐
    rt_path = root / "交接" / f"红队_问题{question_num}.json"
    if not rt_path.is_file():
        issues.append(f"{q} 红队报告缺失（不阻塞但记入 issues）")
    else:
        try:
            rt = json.loads(rt_path.read_text(encoding="utf-8"))
            conclusion = rt.get("结论", "")
            if conclusion == "不齐":
                issues.append(f"{q} 红队结论不齐")
            elif conclusion not in ("对齐", "不齐"):
                issues.append(f"{q} 红队结论异常: {conclusion!r}")
        except Exception as e:
            issues.append(f"{q} 红队报告不可解析: {e}")

    # 3) 仲裁台账：应改方=建模 的条目消解状态必须为 已消解/已解释
    arb_path = root / "交接" / f"仲裁_问题{question_num}.json"
    if arb_path.is_file():
        try:
            arb = json.loads(arb_path.read_text(encoding="utf-8"))
            for item in arb.get("逐项", []):
                if item.get("应改方", "").startswith("建模"):
                    status = item.get("消解状态", "待处理")
                    if status not in ("已消解", "已解释"):
                        issues.append(
                            f"{q} 仲裁条目 {item.get('条目', '?')!r} 消解状态={status!r}（须已消解/已解释）"
                        )
        except Exception as e:
            issues.append(f"{q} 仲裁台账不可解析: {e}")

    # 4) 求解脚本存在
    solver = root / "求解" / f"问题{question_num}" / f"求解_问题{question_num}.py"
    if not solver.is_file():
        issues.append(f"{q} 求解脚本缺失")

    # 5) 实验记录存在（科学尝试不含流程词）
    exp_path = root / "交接" / "实验记录.json"
    if exp_path.is_file():
        try:
            exps = json.loads(exp_path.read_text(encoding="utf-8"))
            if not isinstance(exps, list):
                issues.append("实验记录顶层须为数组")
        except Exception as e:
            issues.append(f"实验记录不可解析: {e}")

    return (len(issues) == 0), issues
