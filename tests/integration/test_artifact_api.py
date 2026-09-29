from __future__ import annotations

from pathlib import Path

import pytest

from mmagent.api.artifacts import import_files, list_artifacts, read_artifact
from mmagent.api.projects import create_project


def test_import_and_artifact_preview(tmp_path: Path) -> None:
    handle = create_project(tmp_path / "proj", name="artifacts", profile="标准")
    try:
        source = tmp_path / "problem.txt"
        source.write_text("题面内容", encoding="utf-8")
        imported = import_files(handle.workspace.root, [str(source)], kind="problem")
        assert imported[0]["path"] == "输入/题目/problem.txt"

        paper = handle.workspace.root / "交付" / "论文.pdf"
        paper.parent.mkdir(parents=True, exist_ok=True)
        paper.write_bytes(b"%PDF-preview")
        note = handle.workspace.root / "审稿" / "note.md"
        note.write_text("review", encoding="utf-8")

        listed = list_artifacts(handle.workspace.root)
        paths = {item["path"] for item in listed}
        assert "交付/论文.pdf" in paths
        assert "审稿/note.md" in paths

        preview = read_artifact(handle.workspace.root, "审稿/note.md")
        assert preview["kind"] == "text"
        assert preview["text"] == "review"

        pdf = read_artifact(handle.workspace.root, "交付/论文.pdf")
        assert pdf["kind"] == "pdf"
        assert pdf["base64"]
    finally:
        handle.workspace.db.close()


def test_artifact_reader_rejects_internal_state(tmp_path: Path) -> None:
    handle = create_project(tmp_path / "proj", name="artifacts-deny", profile="标准")
    try:
        with pytest.raises(ValueError):
            read_artifact(handle.workspace.root, ".mmagent/project.db")
    finally:
        handle.workspace.db.close()
