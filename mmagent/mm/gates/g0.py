"""G0 契约门（机械判据，复现原 Skill 门检.py G0 函数语义）。

判据（SOURCE_MAP §2 G0 行）：
- 题面契约文件存在且为合法 JSON
- 顶层键齐全（赛题/问题/硬约束清单/歧义裁定/附件清单）
- 每问有 原文摘录/解读/需求条目
- 需求号 N-序号 连续（Pydantic model_validator 强制）
- 歧义裁定每条有 裁定 + 理由
- 附件清单覆盖 数据/ 全部文件
- 需求矩阵条目数 = 需求条目总数
"""
from __future__ import annotations

import json
from pathlib import Path

from mmagent.mm.contracts.s0_contracts import ProblemContract


def check_g0(workspace_root: Path) -> tuple[bool, list[str]]:
    """G0 门检。返回 (pass, 明细列表)。明细非空 = FAIL。"""
    issues: list[str] = []
    root = Path(workspace_root)

    # 1) 题面契约存在且合法
    contract_path = root / "交接" / "题面契约.json"
    if not contract_path.is_file():
        return False, ["交接/题面契约.json 缺失"]
    try:
        raw = json.loads(contract_path.read_text(encoding="utf-8"))
        contract = ProblemContract.model_validate(raw)
    except Exception as e:
        return False, [f"题面契约 schema 校验失败: {e}"]

    # 2) 顶层键（Pydantic 已强制必填字段，此处检查可选但推荐的键）
    for key in ("标题", "硬约束清单", "歧义裁定", "附件清单"):
        if key not in raw:
            issues.append(f"契约缺顶层键：{key}")
    # 问题清单非空（G0 上游教训：答案门不读核心指标 → 三问交白卷仍放行）
    if not contract.问题:
        issues.append("契约 问题 为空")

    # 3) 每问内容非空
    for prob in contract.问题:
        if not prob.原文摘录.strip():
            issues.append(f"问{prob.编号} 原文摘录为空")
        if not prob.解读.strip():
            issues.append(f"问{prob.编号} 解读为空")
        if not prob.需求条目:
            issues.append(f"问{prob.编号} 需求条目为空")

    # 4) 歧义裁定完整性
    for i, amb in enumerate(contract.歧义裁定, 1):
        if not amb.裁定.strip():
            issues.append(f"歧义裁定第{i}条缺'裁定'")
        if not amb.理由.strip():
            issues.append(f"歧义裁定第{i}条缺'理由'")

    # 5) 附件清单覆盖 数据/ 全部文件
    data_dir = root / "输入" / "数据"
    if data_dir.is_dir():
        actual = {f.name for f in data_dir.iterdir() if f.is_file()}
        declared = {a.文件 for a in contract.附件清单}
        missing = actual - declared
        if missing:
            issues.append(f"附件清单未覆盖: {sorted(missing)}")

    # 6) 需求矩阵条目数 = 需求条目总数
    matrix_path = root / "交接" / "需求追踪矩阵.json"
    if matrix_path.is_file():
        try:
            matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
            total_reqs = sum(len(p.需求条目) for p in contract.问题)
            if isinstance(matrix, list) and len(matrix) != total_reqs:
                issues.append(f"需求矩阵条目数({len(matrix)}) ≠ 需求条目总数({total_reqs})")
        except Exception as e:
            issues.append(f"需求追踪矩阵.json 不可解析: {e}")
    else:
        issues.append("交接/需求追踪矩阵.json 缺失")

    return (len(issues) == 0), issues
