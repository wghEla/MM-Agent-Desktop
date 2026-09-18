"""产物（artifact）：校验、hash、封存（sealing）、版本登记。

不变量（总方案 §15/§19/§34；外审 P1-7 修复后强化）：
- 模型宣告"完成"不等于产物有效：存在性 + JSON 可解析 + schema 校验全过才算；
- **单次读入**：校验、hash、封存基于同一份内存字节——校验后磁盘再被篡改，
  入库的仍是"已验证的那份内容"（内容寻址封存副本，消除 verify→commit TOCTOU 的
  "登记内容 ≠ 验证内容"面）；
- 产物带 version/hash/producer/sealed_path；重算产生新版本（stale-value 基础，v0.5 扩展）。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from mmagent.agent.errors import ArtifactInvalid, ArtifactMissing
from mmagent.state.db import Database
from mmagent.workspace.path_policy import PathPolicy


@dataclass(frozen=True)
class ExpectedArtifact:
    """一个 Task 必须产出的产物。schema_model 为 None 时只要求文件存在。"""

    rel_path: str
    schema_model: type[BaseModel] | None = None
    required: bool = True
    kind: str = "json"


@dataclass(frozen=True)
class ArtifactCheck:
    rel_path: str
    version: int
    hash: str
    schema_id: str | None
    content: bytes  # 已验证的字节（封存源）
    kind: str = "json"
    producer_task: str | None = None


def verify_expected_artifacts(
    policy: PathPolicy,
    expected: list[ExpectedArtifact],
    *,
    schema_registry: dict[str, type[BaseModel]] | None = None,
) -> list[ArtifactCheck]:
    """校验全部 expected artifacts（单次读入内存）。

    required 且缺失 → ArtifactMissing；JSON 非法/schema 不过 → ArtifactInvalid。
    """
    checks: list[ArtifactCheck] = []
    for exp in expected:
        p = policy.root / exp.rel_path
        if not p.is_file():
            if exp.required:
                raise ArtifactMissing(f"缺少期望产物: {exp.rel_path}")
            continue
        data_bytes = p.read_bytes()  # 单次读入：之后磁盘变化不影响本次验收内容
        model = exp.schema_model
        if model is None and schema_registry:
            model = schema_registry.get(exp.rel_path)
        parsed = None
        if exp.kind == "json":
            # kind=json 的产物**必须**是合法 JSON，即使没有 schema（外审 round2 gate #5）
            try:
                parsed = json.loads(data_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise ArtifactInvalid(f"产物不是合法 JSON: {exp.rel_path} ({e})") from e
        if model is not None:
            try:
                model.model_validate(parsed)
            except ValidationError as e:
                raise ArtifactInvalid(f"产物 schema 校验失败: {exp.rel_path}: {e}") from e
        digest = hashlib.sha256(data_bytes).hexdigest()
        checks.append(
            ArtifactCheck(
                rel_path=exp.rel_path,
                version=1,
                hash=digest,
                schema_id=model.__name__ if model else None,
                content=data_bytes,
                kind=exp.kind,
            )
        )
    return checks


def seal_artifacts(policy: PathPolicy, checks: list[ArtifactCheck], task_id: str) -> list[Path]:
    """把已验证字节写入内容寻址封存区 .mmagent/artifacts/。

    封存区不在任何 agent 角色 write_scope 内（Default deny），作为只进审计底账。
    路径必须过 PathPolicy（词法 reparse 检查 + 包含检查）——封存是 runtime 最敏感的
    写路径，不允许绕过边界原语（外审 round2 gate #6：预置 .mmagent junction 防线）。
    同 task+hash 幂等。
    """
    for c in checks:
        rel = policy.resolve(f".mmagent/artifacts/{task_id}_{c.hash[:16]}_{Path(c.rel_path).name}")
        parent_ok = policy.resolve(".mmagent/artifacts")
        if not parent_ok.is_dir():
            parent_ok.mkdir(parents=True, exist_ok=True)
        if not rel.exists() or rel.read_bytes() != c.content:
            rel.write_bytes(c.content)
        # out 收集在下方循环外统一处理
    out = []
    for c in checks:
        out.append(policy.resolve(f".mmagent/artifacts/{task_id}_{c.hash[:16]}_{Path(c.rel_path).name}"))
    return out


def build_artifact_rows(
    db: Database, task_id: str, checks: list[ArtifactCheck], sealed_paths: list[Path]
) -> list[dict[str, Any]]:
    """构造入库行（版本号 = 该 task+path 的下一个版本）。"""
    out = []
    for c, sp in zip(checks, sealed_paths, strict=True):
        r = db.query_one(
            "SELECT MAX(version) AS v FROM artifacts WHERE task_id = ? AND rel_path = ?",
            (task_id, c.rel_path),
        )
        version = int(r["v"] or 0) + 1
        out.append(
            {
                "id": f"art_{uuid.uuid4().hex[:12]}",
                "rel_path": c.rel_path,
                "kind": c.kind,
                "schema_id": c.schema_id,
                "version": version,
                "hash": c.hash,
                "sealed_path": str(sp),
                "input_versions": {},
            }
        )
    return out
