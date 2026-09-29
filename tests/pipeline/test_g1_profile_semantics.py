from __future__ import annotations

import json
from pathlib import Path

from mmagent.mm.gates.g1 import check_g1


def _seed(root: Path) -> None:
    (root / "交接").mkdir(parents=True)
    scout = {
        "问题清单": [
            {
                "编号": 1,
                "路线": [
                    {"路线名": "1A", "方法": "A"},
                    {"路线名": "1B", "方法": "B"},
                    {"路线名": "1C", "方法": "C"},
                ],
            },
            {
                "编号": 2,
                "路线": [
                    {"路线名": "2A", "方法": "A"},
                    {"路线名": "2B", "方法": "B"},
                    {"路线名": "2C", "方法": "C"},
                ],
            },
        ],
        "最难问题编号": 2,
    }
    (root / "交接" / "路线侦察.json").write_text(
        json.dumps(scout, ensure_ascii=False), encoding="utf-8"
    )


def _write_plan(root: Path, *, q1_routes: list[str], q2_routes: list[str]) -> None:
    plan = {
        "问题清单": [
            {
                "编号": 1,
                "主方法": "A",
                "依赖问题": [],
                "锦标赛": {"参赛路线": q1_routes, "优胜": "1A", "依据": "真实原型"},
            },
            {
                "编号": 2,
                "主方法": "A",
                "依赖问题": [],
                "锦标赛": {"参赛路线": q2_routes, "优胜": "2A", "依据": "真实原型"},
            },
        ],
        "叙事主线": "test",
    }
    (root / "交接" / "计划.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8"
    )


def _write_evidence(root: Path, routes: dict[int, list[str]]) -> None:
    rows = []
    for q, names in routes.items():
        for index, name in enumerate(names, 1):
            rows.append({
                "问题编号": q,
                "路线名": name,
                "脚本": f"求解/问题{q}/原型_{index}.py",
                "rc": 0,
                "stdout_tail": "ok",
                "stderr_tail": "",
            })
    (root / "交接" / "原型结果.json").write_text(
        json.dumps({"条目": rows}, ensure_ascii=False), encoding="utf-8"
    )


def test_standard_requires_full_tournament_for_every_question(tmp_path: Path) -> None:
    root = tmp_path / "p"
    _seed(root)
    _write_evidence(root, {1: ["1A"], 2: ["2A", "2B", "2C"]})
    _write_plan(root, q1_routes=["1A"], q2_routes=["2A", "2B", "2C"])

    ok, issues = check_g1(root, profile="标准")
    assert not ok
    assert any("问1 路线 1B 缺原型证据" in issue for issue in issues)
    assert any("问1 锦标赛参赛路线" in issue for issue in issues)


def test_quick_only_requires_full_tournament_for_hardest_question(tmp_path: Path) -> None:
    root = tmp_path / "p"
    _seed(root)
    _write_evidence(root, {1: ["1A"], 2: ["2A", "2B"]})
    _write_plan(root, q1_routes=["1A"], q2_routes=["2A", "2B"])

    ok, issues = check_g1(root, profile="快速")
    assert ok, issues
