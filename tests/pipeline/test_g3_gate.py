from __future__ import annotations

from pathlib import Path

from mmagent.mm.gates.g3 import check_g3


def _make_passing_workspace(root: Path) -> Path:
    (root / "交接").mkdir(parents=True)
    for i in range(16):
        p = root / "求解" / f"问题{(i % 3) + 1}" / "图片" / f"fig_{i:02d}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"PNG")

    scripts = {
        "绘图_s1.py": "from matplotlib.patches import FancyArrowPatch\\n",
        "绘图_s2.py": "from matplotlib.patches import FancyBboxPatch\\n",
        "绘图_s3.py": "ax.add_patch(obj)\\n",
        "绘图_l1.py": "ax.plot(x,y)\\n",
        "绘图_l2.py": "ax.plot(x,y)\\n",
        "绘图_b1.py": "ax.bar(x,y)\\n",
        "绘图_b2.py": "ax.barh(x,y)\\n",
        "绘图_sc1.py": "ax.scatter(x,y)\\n",
        "绘图_sc2.py": "ax.scatter(x,y)\\n",
        "绘图_h1.py": "ax.imshow(a)\\n",
        "绘图_h2.py": "ax.pcolormesh(a)\\n",
        "绘图_x1.py": "ax.boxplot(a)\\n",
        "绘图_x2.py": "ax.boxplot(a)\\n",
    }
    script_dir = root / "求解" / "问题1"
    script_dir.mkdir(parents=True, exist_ok=True)
    for name, content in scripts.items():
        (script_dir / name).write_text(content, encoding="utf-8")

    (root / "交接" / "图注素材_总.json").write_text("{}", encoding="utf-8")
    return root


def test_g3_passing_evidence(tmp_path: Path) -> None:
    root = _make_passing_workspace(tmp_path / "proj")
    ok, issues = check_g3(root)
    assert ok, issues


def test_g3_rejects_too_few_figures(tmp_path: Path) -> None:
    root = _make_passing_workspace(tmp_path / "proj")
    for p in list(root.glob("求解/**/图片/*.png"))[10:]:
        p.unlink()
    ok, issues = check_g3(root)
    assert not ok
    assert any("图数不足" in issue for issue in issues)


def test_g3_rejects_missing_schematic_evidence(tmp_path: Path) -> None:
    root = _make_passing_workspace(tmp_path / "proj")
    for p in root.glob("求解/**/绘图_s*.py"):
        p.unlink()
    ok, issues = check_g3(root)
    assert not ok
    assert any("示意" in issue for issue in issues)


def test_g3_rejects_bar_line_dominance(tmp_path: Path) -> None:
    root = _make_passing_workspace(tmp_path / "proj")
    for i in range(3, 9):
        (root / "求解" / "问题1" / f"绘图_extra_line_{i}.py").write_text(
            "ax.plot(x,y)\\n", encoding="utf-8"
        )
    ok, issues = check_g3(root)
    assert not ok
    assert any("柱状+折线" in issue for issue in issues)
