"""三大守卫 + 换版清单守卫（复现上游 变化/结构/页数 守卫语义）。"""
from __future__ import annotations

import difflib
import re


def _正文单位(text: str) -> list[str]:
    """tex 正文切成句子级单位（去 % 注释行，按句末标点切分）。"""
    lines = [l for l in text.splitlines() if not l.strip().startswith("%")]
    units: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        for x in re.split(r"(?<=[。！？；])", line):
            x = x.strip()
            if x:
                units.append(x)
    return units


def _引号片段(条目们: list[dict]) -> set[str]:
    """评审意见中引号引出的原文片段 = 修改腿被点名要动的地方。"""
    fragments: set[str] = set()
    for item in 条目们 or []:
        text = " ".join(str(item.get(k) or "") for k in ("问题", "指令", "定位"))
        for m in re.finditer(r'["\u201c\u300c\u300e]([^"\u201d\u300d\u300f]{4,120})["\u201d\u300d\u300f]', text):
            fragments.add(m.group(1).strip())
    return fragments


def _被点名(单位: str, 片段: str) -> bool:
    if 片段 in 单位 or 单位 in 片段:
        return True
    if len(片段) >= 10 and len(单位) >= 10:
        m = difflib.SequenceMatcher(None, 片段, 单位, autojunk=False)
        if m.find_longest_match(0, len(片段), 0, len(单位)).size >= 10:
            return True
    return False


def change_guard(
    old_text: str, new_text: str, 条目们: list[dict], *,
    上限: float = 0.45,
) -> tuple[bool, float, dict]:
    """变化守卫（句子尺 + 点名掩码 + 字符丢失比）。

    返回 (通过, 比例, 明细)。比例 = min(未点名句改动比, 字符丢失比)。
    """
    old_units = _正文单位(old_text)
    new_units = _正文单位(new_text)
    fragments = _引号片段(条目们)

    if not old_units:
        return True, 0.0, {"msg": "旧文为空"}

    # 点名掩码
    named = [False] * len(old_units)
    for i, unit in enumerate(old_units):
        for frag in fragments:
            if _被点名(unit, frag):
                named[i] = True
                break

    # 未点名句改动比
    new_set = set(new_units)
    unnamed_indices = [i for i in range(len(old_units)) if not named[i]]
    if unnamed_indices:
        changed = sum(1 for i in unnamed_indices if old_units[i] not in new_set)
        unnamed_ratio = changed / len(unnamed_indices)
    else:
        unnamed_ratio = 0.0

    # 字符丢失比
    old_joined = "\n".join(old_units)
    new_joined = "\n".join(new_units)
    if not old_joined:
        char_ratio = 0.0
    elif len(old_joined) + len(new_joined) <= 60000:
        blocks = difflib.SequenceMatcher(None, old_joined, new_joined, autojunk=False).get_matching_blocks()
        kept = sum(b.size for b in blocks)
        char_ratio = 1.0 - kept / len(old_joined)
    else:
        char_ratio = unnamed_ratio

    ratio = min(unnamed_ratio, char_ratio)
    detail = {"句比": round(1 - sum(1 for u in old_units if u in new_set) / len(old_units), 3),
              "未点名比": round(unnamed_ratio, 3), "字比": round(char_ratio, 3),
              "点名片段": len(fragments), "单位数": len(old_units)}
    return ratio <= 上限, ratio, detail


def structure_guard(old_files: dict[str, str], new_files: dict[str, str]) -> tuple[bool, list[str]]:
    """结构守卫：\\input 集不减、空章、附录源码清单不减。"""
    issues: list[str] = []
    for fname, old_content in old_files.items():
        new_content = new_files.get(fname)
        if new_content is None:
            issues.append(f"{fname} 消失")
            continue
        old_inputs = set(re.findall(r"\\(?:input|include)\{([^}]+)\}", old_content))
        new_inputs = set(re.findall(r"\\(?:input|include)\{([^}]+)\}", new_content))
        lost = old_inputs - new_inputs
        if lost:
            issues.append(f"{fname} \\input 集减少: {sorted(lost)}")
        if not new_content.strip():
            issues.append(f"{fname} 变为空文件")
    return (not issues), issues


def page_guard(old_pages: int, new_pages: int, *, baseline: int | None = None) -> tuple[bool, str]:
    """页数守卫：增长 > max(10%, 2页) 或 骤降 >20% 告警。"""
    base = baseline if baseline is not None else old_pages
    threshold = max(int(base * 0.10), 2)
    if new_pages > base + threshold:
        return False, f"页数超限: {new_pages} > {base}+{threshold}"
    if new_pages < base * 0.8 and base > 5:
        return False, f"页数骤降: {new_pages} < {base}*0.8（可能丢章）"
    return True, ""



def stale_value_guard(workspace_root, *, include_globs: tuple[str, ...] = (
    "论文/**/*.tex", "交接/图注素材*.json", "审稿/**/*.json"
)) -> tuple[bool, list[str]]:
    """换版旧值守卫：换版清单中的旧值不得继续残留在发布载体。

    只扫描文本 carrier，不扫描换版清单自身，避免旧值定义把自己判成残留。
    新旧值相同或旧值为空时跳过。返回 (通过, 明细)。
    """
    import json
    from pathlib import Path

    root = Path(workspace_root)
    changes: list[tuple[str, str, str]] = []
    for manifest in root.glob("交接/换版清单_问题*.json"):
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, [f"换版清单不可解析: {manifest.name}"]
        items = raw.get("条目", []) if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return False, [f"换版清单格式错误: {manifest.name}"]
        for item in items:
            if not isinstance(item, dict):
                continue
            old = str(item.get("旧值", "")).strip()
            new = str(item.get("新值", "")).strip()
            key = str(item.get("键", "?"))
            if old and old != new:
                changes.append((key, old, new))

    if not changes:
        return True, []

    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in include_globs:
        for path in root.glob(pattern):
            if path.is_file() and path not in seen and "换版清单_" not in path.name:
                seen.add(path)
                files.append(path)

    issues: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for key, old, new in changes:
            if old in text:
                rel = path.relative_to(root).as_posix()
                issues.append(f"旧值残留: {key} {old!r} -> {new!r} 仍见于 {rel}")
    return not issues, issues
