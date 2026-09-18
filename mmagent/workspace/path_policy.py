"""路径策略：一切文件访问的边界守卫。

规则（总方案 §21；v0.1.0 外审 P0-2/P2-5 修复后强化）：
- 所有相对路径先做 posix 归一，拒绝 `..`、`.`、盘符/反斜杠注入、绝对路径、NUL；
- Windows 段名加固：拒绝 ADS 语法（`:`）、尾点/尾空格、保留设备名（CON/PRN/AUX/NUL/COM1-9/LPT1-9）；
- 解析后必须仍位于工作区内（resolve + is_relative_to）；
- **词法组件逐级 reparse 检查**：在 Path.resolve() 抹掉别名之前，沿词法路径
  从 root 逐级 lstat，任何已存在的 reparse point（junction/symlink）→ PathEscape。
  这同时封死"junction 指向工作区内受限目录"的 scope 穿透（外审 P0-2）与
  "junction 指向工作区外"的逃逸。

已知残留（诚实声明，见 KNOWN_DEVIATIONS）：字符串路径检查存在理论 TOCTOU 窗口
（check 与 use 之间目录被替换）；彻底消除需要 handle-based open
（CreateFile FILE_FLAG_OPEN_REPARSE_POINT + GetFinalPathNameByHandle），列入 v0.2。
"""
from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path, PurePosixPath

from mmagent.agent.errors import PathEscape

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400

# Windows 保留设备名（大小写不敏感，可带扩展名）
_RESERVED_NAMES = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$", re.IGNORECASE
)


def normalize_rel(rel: str) -> str:
    """把任意输入归一成工作区内的 posix 相对路径；越界企图直接抛 PathEscape。"""
    if not rel:
        raise PathEscape("空路径")
    if rel != rel.strip() or rel != rel.strip("　"):
        raise PathEscape(f"路径含首尾空白（拒绝静默归一）: {rel!r}")
    s = rel.replace("\\", "/")
    if s.startswith("/") or (len(s) >= 2 and s[1] == ":"):
        raise PathEscape(f"拒绝绝对路径: {rel!r}")
    if "\x00" in s:
        raise PathEscape("路径含空字节")
    pure = PurePosixPath(s)
    out_parts: list[str] = []
    for part in pure.parts:
        if part in ("..", "."):
            raise PathEscape(f"拒绝路径分量 {part!r}: {rel!r}")
        if ":" in part:
            raise PathEscape(f"拒绝 NTFS ADS 语法（段含冒号）: {rel!r}")
        if part != part.rstrip(" ."):
            raise PathEscape(f"拒绝尾点/尾空格段: {rel!r}")
        stem = part.split("/", 1)[0]
        if _RESERVED_NAMES.match(stem.split("/")[0]):
            raise PathEscape(f"拒绝 Windows 保留设备名: {rel!r}")
        out_parts.append(part)
    if not out_parts:
        raise PathEscape(f"空路径: {rel!r}")
    return PurePosixPath(*out_parts).as_posix()


def _is_reparse(p: Path) -> bool:
    """fail-closed：FileNotFoundError 视为非 reparse；其他 OSError 一律按 reparse 处理（拒绝）。"""
    try:
        st = os.lstat(p)
        return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _lexical_reparse_walk(root: Path, rel_posix: str) -> None:
    """沿**词法**路径从 root 逐级检查已存在组件是否为 reparse point。

    必须在 Path.resolve() 之前做——resolve 会把 junction/symlink 消掉，
    导致"工作区内 junction 穿透 role scope"不可见（外审 P0-2）。
    """
    cur = root
    for part in PurePosixPath(rel_posix).parts:
        cur = cur / part
        if _is_reparse(cur):
            raise PathEscape(
                f"路径包含 reparse point（junction/symlink，禁止穿越 scope 边界）: {rel_posix!r}"
            )


class PathPolicy:
    """绑定一个工作区根的路径策略。"""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def resolve(self, rel: str, *, must_exist: bool = False) -> Path:
        reln = normalize_rel(rel)
        # 1) 词法 reparse 检查（resolve 之前——P0-2）
        _lexical_reparse_walk(self.root, reln)
        # 2) 解析后包含检查（跟随 reparse 后仍不得出工作区——外逃逸防线）
        p = (self.root / reln).resolve()
        if p != self.root and not p.is_relative_to(self.root):
            raise PathEscape(f"解析后越出工作区: {rel!r} -> {p}")
        # 3) 解析链兜底 reparse 检查（防御残留场景）
        if _has_reparse_component(self.root, p.parent):
            raise PathEscape(f"路径解析链包含 reparse point: {rel!r}")
        if must_exist and not p.exists():
            raise FileNotFoundError(f"文件不存在: {rel}")
        return p

    def parent_dir(self, rel: str) -> Path:
        p = self.resolve(rel)
        d = p.parent
        if not d.is_relative_to(self.root):
            raise PathEscape(rel)
        return d

    def ensure_parent(self, rel: str) -> Path:
        reln = normalize_rel(rel)
        parent = posixpath.dirname(reln)
        d = self.resolve(parent) if parent else self.root
        if not d.is_dir():
            d.mkdir(parents=True, exist_ok=True)
        return d

    def is_reparse_point(self, rel: str) -> bool:
        try:
            p = self.resolve(rel)
            return _is_reparse(p)
        except (OSError, PathEscape):
            return False


def _has_reparse_component(root: Path, target: Path) -> bool:
    """Windows：target 或其（root 之下的）任一祖先目录是 reparse point → True。"""
    if os.name != "nt":
        return False
    try:
        cur = target
        while True:
            if _is_reparse(cur):
                return True
            if cur == root:
                break
            parent = cur.parent
            if parent == cur:
                break
            cur = parent
    except OSError:
        return False
    return False


def join_posix(*parts: str) -> str:
    """工作区内部拼路径（posix 语义，供持久化 rel_path 用）。"""
    return posixpath.join(*[p.replace("\\", "/") for p in parts if p])
