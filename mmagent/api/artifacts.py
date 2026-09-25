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
            suffix = resolved.suffix.lower()
            mime, _ = mimetypes.guess_type(resolved.name)
            kind = (
                "pdf" if suffix == ".pdf"
                else "image" if suffix in {".png", ".jpg", ".jpeg", ".webp"}
                else "text" if suffix in _TEXT_SUFFIXES
                else "binary"
            )
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

    size = path.stat().st_size
    suffix = path.suffix.lower()
    mime, _ = mimetypes.guess_type(path.name)

    if suffix in _TEXT_SUFFIXES:
        if size > _MAX_TEXT_BYTES:
            raise ValueError(f"文本预览超过 {_MAX_TEXT_BYTES} bytes")
        return {
            "path": normalized,
            "kind": "text",
            "mime_type": mime or "text/plain",
            "size": size,
            "text": path.read_text(encoding="utf-8", errors="replace"),
        }

    if suffix == ".pdf" or suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        if size > _MAX_BINARY_PREVIEW_BYTES:
            raise ValueError(f"预览文件超过 {_MAX_BINARY_PREVIEW_BYTES} bytes")
        return {
            "path": normalized,
            "kind": "pdf" if suffix == ".pdf" else "image",
            "mime_type": mime or ("application/pdf" if suffix == ".pdf" else "application/octet-stream"),
            "size": size,
            "base64": base64.b64encode(path.read_bytes()).decode("ascii"),
        }

    return {
        "path": normalized,
        "kind": "binary",
        "mime_type": mime or "application/octet-stream",
        "size": size,
    }


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
