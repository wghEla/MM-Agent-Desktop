"""Frozen composite input package for S2 independent recomputation."""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class FrozenInputEntry:
    source: str
    frozen_path: str
    sha256: str
    size: int
    kind: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_entry(
    root: Path,
    source: Path,
    target_root: Path,
    rel_target: Path,
    *,
    kind: str,
) -> FrozenInputEntry:
    target = target_root / rel_target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return FrozenInputEntry(
        source=source.relative_to(root).as_posix(),
        frozen_path=target.relative_to(root).as_posix(),
        sha256=_sha256(target),
        size=target.stat().st_size,
        kind=kind,
    )


def freeze_question_inputs(
    workspace_root: Path,
    question_num: int,
    *,
    dependency_questions: list[int] | tuple[int, ...] = (),
) -> dict:
    """Build a fresh, content-hashed input package for one S2 question.

    The package contains:
    - immutable copies of user-provided files under 输入/数据 (excluding prior
      frozen packages);
    - frozen result declarations and result files from dependency questions.

    Runtime owns this package.  Red-team roles read it instead of arbitrary
    modeler workspace files, which makes independent recomputation auditable.
    """
    root = Path(workspace_root)
    data_root = root / "输入" / "数据"
    data_root.mkdir(parents=True, exist_ok=True)
    final_dir = data_root / f"问题{question_num}_冻结合成输入"
    temp_dir = data_root / f".问题{question_num}_冻结合成输入.tmp-{uuid.uuid4().hex[:8]}"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    entries: list[FrozenInputEntry] = []
    try:
        for source in sorted(data_root.rglob("*")):
            if not source.is_file():
                continue
            rel = source.relative_to(data_root)
            # Never recursively capture an earlier frozen package or temp tree.
            if any(
                part.startswith("问题") and part.endswith("_冻结合成输入")
                or part.startswith(".问题") and "_冻结合成输入.tmp-" in part
                for part in rel.parts
            ):
                continue
            entries.append(
                _copy_entry(
                    root,
                    source,
                    temp_dir,
                    Path("raw") / rel,
                    kind="raw_data",
                )
            )

        deps = sorted({int(q) for q in dependency_questions if int(q) != question_num})
        for dep in deps:
            declaration = root / "交接" / f"结果声明_问题{dep}.json"
            if not declaration.is_file():
                raise FileNotFoundError(
                    f"冻结问题{question_num}输入失败：依赖问{dep}缺 交接/结果声明_问题{dep}.json"
                )
            entries.append(
                _copy_entry(
                    root,
                    declaration,
                    temp_dir,
                    Path("deps") / f"问题{dep}" / "结果声明.json",
                    kind="dependency_declaration",
                )
            )

            result_root = root / "求解" / f"问题{dep}" / "结果"
            if result_root.is_dir():
                for source in sorted(result_root.rglob("*")):
                    if not source.is_file():
                        continue
                    rel = source.relative_to(result_root)
                    entries.append(
                        _copy_entry(
                            root,
                            source,
                            temp_dir,
                            Path("deps") / f"问题{dep}" / "结果" / rel,
                            kind="dependency_result",
                        )
                    )

        manifest = {
            "问题编号": question_num,
            "依赖问题": deps,
            "文件": [asdict(entry) for entry in entries],
        }
        (temp_dir / "输入清单.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if final_dir.exists():
            shutil.rmtree(final_dir)
        temp_dir.rename(final_dir)

        # frozen_path was generated under the temp directory. Rewrite it to the
        # final canonical package path before publishing the manifest.
        for item in manifest["文件"]:
            old = item["frozen_path"]
            marker = temp_dir.name + "/"
            if marker in old:
                item["frozen_path"] = old.replace(
                    marker, final_dir.name + "/", 1
                )
        (final_dir / "输入清单.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return manifest
    except BaseException:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def verify_frozen_question_inputs(
    workspace_root: Path,
    question_num: int,
) -> tuple[bool, list[str]]:
    """Mechanically verify the published manifest against frozen file bytes."""
    root = Path(workspace_root)
    package = root / "输入" / "数据" / f"问题{question_num}_冻结合成输入"
    manifest_path = package / "输入清单.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, [f"冻结输入清单不可用: {exc}"]

    issues: list[str] = []
    if manifest.get("问题编号") != question_num:
        issues.append("冻结输入清单问题编号不匹配")
    rows = manifest.get("文件")
    if not isinstance(rows, list):
        return False, issues + ["冻结输入清单 文件 必须为数组"]

    for row in rows:
        if not isinstance(row, dict):
            issues.append("冻结输入清单存在非对象条目")
            continue
        rel = str(row.get("frozen_path", ""))
        try:
            path = root / rel
            path.relative_to(package)
        except (ValueError, TypeError):
            issues.append(f"冻结路径越界: {rel!r}")
            continue
        if not path.is_file():
            issues.append(f"冻结文件缺失: {rel}")
            continue
        expected_hash = str(row.get("sha256", ""))
        actual_hash = _sha256(path)
        if expected_hash != actual_hash:
            issues.append(f"冻结文件 hash 不匹配: {rel}")
        if int(row.get("size", -1)) != path.stat().st_size:
            issues.append(f"冻结文件 size 不匹配: {rel}")
    return not issues, issues
