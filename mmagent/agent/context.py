"""Context Manager（v0.1 最小版）。

原则（总方案 §20）：search → targeted read → reason → tool → persist。
跨阶段关键信息进 交接/ 而不是聊天记忆；本模块负责生成任务上下文清单
（context manifest），并随 invocation 持久化，供审计与断点恢复。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ContextEntry:
    rel_path: str
    size: int
    sha256: str


@dataclass
class ContextManifest:
    node_key: str
    role_id: str
    entries: list[ContextEntry] = field(default_factory=list)
    instructions_chars: int = 0

    def to_dict(self) -> dict:
        return {
            "node_key": self.node_key,
            "role_id": self.role_id,
            "instructions_chars": self.instructions_chars,
            "entries": [e.__dict__ for e in self.entries],
        }

    def render(self) -> str:
        """给模型的文本形态：只列清单，正文由腿按需 fs.read（targeted read）。"""
        lines = ["## 上下文清单（正文用 fs.read 按需读取，不要凭记忆假设内容）"]
        for e in self.entries:
            lines.append(f"- {e.rel_path} ({e.size}B, sha256:{e.sha256[:12]})")
        return "\n".join(lines)


def hash_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(node_key: str, role_id: str, instructions: str, context_files: list[Path]) -> ContextManifest:
    m = ContextManifest(node_key=node_key, role_id=role_id, instructions_chars=len(instructions))
    for p in context_files:
        if p.is_file():
            m.entries.append(
                ContextEntry(rel_path=p.name, size=p.stat().st_size, sha256=hash_file(p))
            )
    return m


def dumps(manifest: ContextManifest) -> str:
    return json.dumps(manifest.to_dict(), ensure_ascii=False)
