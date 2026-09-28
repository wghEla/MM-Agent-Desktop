"""Desktop-facing project import and artifact browsing helpers."""
from __future__ import annotations

import base64
import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mmagent.workspace.path_policy import PathPolicy, normalize_rel

_BROWSE_ROOTS = frozenset({"交付", "论文", "审稿", "交接", "求解", "红队结果", "日志"})
_WORKSPACE_BROWSE_ROOTS = (
    "输入",
    "求解",
    "图片",
    "论文",
    "审稿",
    "台账",
    "交接",
    "交付",
    "红队结果",
    "日志",
)
_IMPORT_TARGETS = {"problem": "输入/题目", "data": "输入/数据"}
_TEXT_SUFFIXES = {
    ".txt", ".md", ".json", ".yaml", ".yml", ".tex", ".log", ".py", ".csv",
}
_MAX_TEXT_BYTES = 2 * 1024 * 1024
_MAX_BINARY_PREVIEW_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class ArtifactView:
    path: str
    name: str
    size: int
    kind: str
    mime_type: str | None


def _preview_kind(path: Path) -> tuple[str, str | None]:
    suffix = path.suffix.lower()
    mime, _ = mimetypes.guess_type(path.name)
    kind = (
        "pdf" if suffix == ".pdf"
        else "image" if suffix in {".png", ".jpg", ".jpeg", ".webp"}
        else "text" if suffix in _TEXT_SUFFIXES
        else "binary"
    )
    return kind, mime


def _allowed_workspace_path(rel: str) -> str:
    normalized = normalize_rel(rel)
    top = normalized.split("/", 1)[0]
    if top not in _WORKSPACE_BROWSE_ROOTS:
        raise ValueError(f"workspace path 不在可浏览目录: {top}")
    return normalized


def list_workspace_tree(
    root: Path,
    *,
    limit: int = 2000,
    max_depth: int = 6,
) -> dict[str, Any]:
    """Return a bounded, read-only projection of user-visible workspace files.

    Runtime/SQLite remains authoritative.  The tree deliberately excludes internal
    directories such as .mmagent and validates every existing lexical path through
    PathPolicy so junction/symlink escapes are skipped fail-closed.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    if max_depth < 0:
        raise ValueError("max_depth must be non-negative")

    policy = PathPolicy(root)
    items: list[dict[str, Any]] = []
    truncated = False

    def append_item(path: Path, rel: str, *, depth: int, kind: str) -> bool:
        nonlocal truncated
        if len(items) >= limit:
            truncated = True
            return False
        row: dict[str, Any] = {
            "path": rel,
            "name": path.name,
            "kind": kind,
            "depth": depth,
            "size": None,
            "preview_kind": None,
        }
        if kind == "file":
            try:
                row["size"] = path.stat().st_size
            except OSError:
                row["size"] = None
            row["preview_kind"] = _preview_kind(path)[0]
        items.append(row)
        return True

    def walk(directory: Path, rel_dir: str, depth: int) -> None:
        nonlocal truncated
        if truncated or depth >= max_depth:
            return
        try:
            children = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
        except OSError:
            return
        for child in children:
            rel = f"{rel_dir}/{child.name}"
            try:
                resolved = policy.resolve(rel, must_exist=True)
            except Exception:
                continue
            kind = "directory" if resolved.is_dir() else "file" if resolved.is_file() else "other"
            if kind == "other":
                continue
            child_depth = depth + 1
            if not append_item(resolved, rel, depth=child_depth, kind=kind):
                return
            if kind == "directory":
                walk(resolved, rel, child_depth)
            if truncated:
                return

    for top in _WORKSPACE_BROWSE_ROOTS:
        base = root / top
        if not base.exists():
            continue
        try:
            resolved = policy.resolve(top, must_exist=True)
        except Exception:
            continue
        if not resolved.is_dir():
            continue
        if not append_item(resolved, top, depth=0, kind="directory"):
            break
        walk(resolved, top, 0)
        if truncated:
            break

    return {"items": items, "truncated": truncated}


def read_workspace_file(root: Path, rel: str) -> dict[str, Any]:
    normalized = _allowed_workspace_path(rel)
    path = PathPolicy(root).resolve(normalized, must_exist=True)
    if not path.is_file():
        raise ValueError("workspace path 不是文件")
    return _read_preview(path, normalized)


def _read_preview(path: Path, normalized: str) -> dict[str, Any]:
    size = path.stat().st_size
    kind, mime = _preview_kind(path)

    if kind == "text":
        if size > _MAX_TEXT_BYTES:
            raise ValueError(f"文本预览超过 {_MAX_TEXT_BYTES} bytes")
        return {
            "path": normalized,
            "kind": "text",
            "mime_type": mime or "text/plain",
            "size": size,
            "text": path.read_text(encoding="utf-8", errors="replace"),
        }

    if kind in {"pdf", "image"}:
        if size > _MAX_BINARY_PREVIEW_BYTES:
            raise ValueError(f"预览文件超过 {_MAX_BINARY_PREVIEW_BYTES} bytes")
        return {
            "path": normalized,
            "kind": kind,
            "mime_type": mime or ("application/pdf" if kind == "pdf" else "application/octet-stream"),
            "size": size,
            "base64": base64.b64encode(path.read_bytes()).decode("ascii"),
        }

    return {
        "path": normalized,
        "kind": "binary",
        "mime_type": mime or "application/octet-stream",
        "size": size,
    }


def _allowed_artifact_path(rel: str) -> str:
    normalized = normalize_rel(rel)
    top = normalized.split("/", 1)[0]
    if top not in _BROWSE_ROOTS:
        raise ValueError(f"artifact path 不在可浏览目录: {top}")
    return normalized


def list_artifacts(root: Path, *, limit: int = 1000) -> list[dict[str, Any]]:
    policy = PathPolicy(root)
    items: list[ArtifactView] = []
    for top in sorted(_BROWSE_ROOTS):
        base = root / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            # Re-validate through PathPolicy so junction/symlink paths fail closed.
            try:
                resolved = policy.resolve(rel, must_exist=True)
            except Exception:
                continue
            kind, mime = _preview_kind(resolved)
            items.append(ArtifactView(
                path=rel,
                name=resolved.name,
                size=resolved.stat().st_size,
                kind=kind,
                mime_type=mime,
            ))
            if len(items) >= limit:
                return [item.__dict__ for item in items]
    return [item.__dict__ for item in items]


def read_artifact(root: Path, rel: str) -> dict[str, Any]:
    normalized = _allowed_artifact_path(rel)
    path = PathPolicy(root).resolve(normalized, must_exist=True)
    if not path.is_file():
        raise ValueError("artifact 不是文件")
    return _read_preview(path, normalized)


def import_files(root: Path, sources: list[str], *, kind: str) -> list[dict[str, Any]]:
    target_rel = _IMPORT_TARGETS.get(kind)
    if target_rel is None:
        raise ValueError("import kind must be problem or data")
    if not sources:
        raise ValueError("sources must not be empty")

    target = PathPolicy(root).resolve(target_rel)
    target.mkdir(parents=True, exist_ok=True)
    imported: list[dict[str, Any]] = []

    for raw in sources:
        source = Path(raw).expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"导入源不是文件: {raw}")
        destination = target / source.name
        if destination.exists():
            stem, suffix = source.stem, source.suffix
            index = 2
            while destination.exists():
                destination = target / f"{stem}_{index}{suffix}"
                index += 1
        shutil.copy2(source, destination)
        imported.append({
            "source": str(source),
            "path": destination.relative_to(root).as_posix(),
            "size": destination.stat().st_size,
        })
    return imported
