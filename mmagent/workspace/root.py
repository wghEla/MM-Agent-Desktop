"""项目工作区：目录约定（保留原 Skill 中文逻辑名）+ SQLite 真相库 + 单运行锁。

目录约定（总方案 §7）：
  输入/{题目,数据}  交接/  求解/  红队结果/  论文/  审稿/  台账/  日志/  快照/  交付/
  .mmagent/{project.db, run.lock, config_snapshot.json, checkpoints/}
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from mmagent.agent.errors import RunLocked
from mmagent.state.db import Database

WORKSPACE_DIRS: tuple[str, ...] = (
    "输入/题目",
    "输入/数据",
    "交接",
    "求解",
    "红队结果",
    "论文",
    "审稿",
    "台账",
    "日志",
    "快照",
    "交付",
    ".mmagent/checkpoints",
)


class ProjectWorkspace:
    """一个数模项目的工作区（磁盘布局 + project.db）。"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.db = Database(self.root / ".mmagent" / "project.db")
        self.db.migrate()

    # ------------------------------------------------------------- 创建/打开
    @classmethod
    def create(cls, root: Path, *, name: str, profile: str = "standard") -> ProjectWorkspace:
        root = Path(root)
        if any((root / d).exists() for d in WORKSPACE_DIRS):
            raise FileExistsError(f"目标目录已有工作区结构: {root}")
        for d in WORKSPACE_DIRS:
            (root / d).mkdir(parents=True, exist_ok=True)
        ws = cls(root)
        from mmagent.state import repositories

        repositories.create_project(ws.db, name=name, root_path=root, profile=profile)
        (root / ".mmagent" / "config_snapshot.json").write_text(
            json.dumps({"name": name, "profile": profile}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        return ws

    @classmethod
    def open(cls, root: Path) -> ProjectWorkspace:
        root = Path(root)
        if not (root / ".mmagent" / "project.db").is_file():
            raise FileNotFoundError(f"不是 mmagent 工作区（缺 project.db）: {root}")
        return cls(root)

    # ------------------------------------------------------------- 单运行锁
    # 复现原 Skill 铁律 1：一个父目录只起一个驱动。
    # SQLite（runs 表 status）+ run.lock 文件双层保护。
    def acquire_run_lock(self, run_id: str) -> None:
        lock = self.root / ".mmagent" / "run.lock"
        try:
            if lock.exists():
                data = json.loads(lock.read_text(encoding="utf-8"))
                pid = int(data.get("pid", 0))
                if pid and _pid_alive(pid):
                    raise RunLocked(
                        f"已有运行中的 owner pid={pid} run={data.get('run_id')}；"
                        "拒绝接管（如确认已死请走 crash recovery）"
                    )
            lock.write_text(json.dumps({"run_id": run_id, "pid": os.getpid()}), encoding="utf-8")
        except RunLocked:
            raise
        except (OSError, ValueError) as e:
            raise RunLocked(f"run.lock 不可用: {e}") from e

    def release_run_lock(self) -> None:
        lock = self.root / ".mmagent" / "run.lock"
        try:
            if lock.exists():
                lock.unlink()
        except OSError:
            pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            dw = ctypes.c_ulong(0)
            ok = k32.GetExitCodeProcess(h, ctypes.byref(dw))
            return bool(ok) and dw.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
