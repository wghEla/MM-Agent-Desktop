"""Windows 进程树管理（总方案 §22；v0.2.0 按外审十轮意见定稿）。

核心机制：**Windows Job Object**（KILL_ON_JOB_CLOSE）+ **CREATE_SUSPENDED 原子启动**
（pywin32 原生 CreateProcess；v0.2 **不使用** PROC_THREAD_ATTRIBUTE_HANDLE_LIST，
完整 attr-list 白名单列入 v0.3——ctypes 直传 Unicode env 块存在 87 quirk，
见 KNOWN_DEVIATIONS）。

不变量：
- I-J1 树的终止确认 = **Job 活跃进程数归零**（root 退出 ≠ 树死）。
- I-J2 Runtime 崩溃不孤儿化：KILL_ON_JOB_CLOSE；Job 创建/绑定失败 = fail-closed。
- I-J3 重派前回收：per-name 串行 + compare-and-remove；旧副本无法确认终止 →
  old quarantined、新挂起进程确认终止（从未运行）后才抛错；绝不双跑/无主活进程。
- I-J4 取消语义（诚实定义）：rc=-99 仅表示"取消终止请求成功提交且随后确认树归零"；
  调用时树已归零（dead_before）或终止请求失败但树自然归零（natural_exit）→ 保留真实 rc；
  请求失败且树仍活 → quarantined + 显式失败。
- I-J5 输出预算：超 quota 立即终止 Job；尾部 seek 限读。
- I-J6 句柄继承面（v0.2 弱保证，诚实声明）：Runtime 为每个 spawn 仅创建 3 个可继承
  std 句柄，且 create→CreateProcess→父侧关闭 全程持有模块级 _CREATE_LOCK；返回的
  process/thread 句柄不可继承。不保证进程中其他组件的可继承句柄不被继承（v0.3 HANDLE_LIST）。
- I-J7 spawn 是**显式提交序列**：CreateProcess 成功 = 资源所有权分界点；此后任何异常
  都有 guard 持有资源完成 终止/隔离/清理 回滚，不存在半提交对象。
- I-J8 v0.2 仅支持 Windows（POSIX 路径已移除；POSIX 支持列入后续版本）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import win32api
import win32file
import win32job

from mmagent.agent.errors import ToolTimeout

_CANCELLED_RC = -99
_TERMINATE_WAIT_S = 10.0
_STILL_ACTIVE = 259
_DEFAULT_OUTPUT_QUOTA = 256 * 1024 * 1024
_TAIL_BYTES = 40_000

# I-J6 继承面窗口锁：可继承 std 句柄创建 → CreateProcess → 父侧关闭 全程互斥
_CREATE_LOCK = threading.Lock()


@dataclass
class ManagedProcess:
    name: str
    pid: int
    argv: list[str]
    h_process: Any | None = None
    h_thread: Any | None = None
    job_handle: Any | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    root_exited: bool = False
    tree_exited: bool = False
    rc: int | None = None
    stdout_tail: bytes = b""
    stderr_tail: bytes = b""
    quarantined: bool = False

    @property
    def alive(self) -> bool:
        """root 是否仍在运行（诊断用；生命周期判定用 tree_alive）。"""
        if self.root_exited or self.tree_exited:
            return False
        if self.h_process is not None:
            import win32process

            code = int(win32process.GetExitCodeProcess(self.h_process))
            if code != _STILL_ACTIVE:
                self.root_exited = True
                self.rc = self.rc if self.rc is not None else code
                return False
            return True
        return False

    @property
    def tree_alive(self) -> bool:
        """整棵树是否仍有活跃进程（Job 活跃数 > 0；root 退出不代表树死）。"""
        if self.tree_exited:
            return False
        if self.job_handle is not None:
            n = _job_active_count(self.job_handle)
            if n == 0:
                self.tree_exited = True
                self.root_exited = True
                if self.rc is None and self.h_process is not None:
                    import win32process

                    self.rc = int(win32process.GetExitCodeProcess(self.h_process))
                return False
            return True
        return self.alive


class JobSetupIncomplete(Exception):
    """Job 绑定失败且挂起进程终止未确认：携带未收口的 proc，调用方必须 quarantine。"""

    def __init__(self, proc: ManagedProcess, message: str):
        super().__init__(message)
        self.proc = proc


class ProcessRegistry:
    """name → ManagedProcess；quarantined 集合（identity 去重）；compare-and-remove。

    终止 authority 只在 ProcessManager（lifecycle gate 后）——注册表不提供终止方法。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._procs: dict[str, ManagedProcess] = {}
        self._name_locks: dict[str, threading.Lock] = {}
        self._quarantined: list[ManagedProcess] = []
        self._accepting = True

    def name_lock(self, name: str) -> threading.Lock:
        with self._lock:
            return self._name_locks.setdefault(name, threading.Lock())

    def publish(self, proc: ManagedProcess) -> ManagedProcess | None:
        with self._lock:
            if not self._accepting:
                raise RuntimeError("ProcessManager 已 shutdown，拒绝新 spawn")
            old = self._procs.get(proc.name)
            self._procs[proc.name] = proc
            return old

    def get(self, name: str) -> ManagedProcess | None:
        with self._lock:
            return self._procs.get(name)

    def remove(self, name: str, expected: ManagedProcess | None = None) -> ManagedProcess | None:
        with self._lock:
            cur = self._procs.get(name)
            if cur is None:
                return None
            if expected is not None and cur is not expected:
                return None
            return self._procs.pop(name)

    def quarantine(self, proc: ManagedProcess) -> None:
        proc.quarantined = True
        with self._lock:
            if not any(q is proc for q in self._quarantined):  # identity 去重
                self._quarantined.append(proc)

    @property
    def quarantined(self) -> list[ManagedProcess]:
        with self._lock:
            return list(self._quarantined)

    def remove_quarantined(self, proc: ManagedProcess) -> bool:
        """resolution primitive：quarantined 对象确认收口后从隔离集合移除（identity）。"""
        with self._lock:
            for i, q in enumerate(self._quarantined):
                if q is proc:
                    self._quarantined.pop(i)
                    return True
            return False

    def orphans(self, *, grace_s: float = 0.0) -> list[ManagedProcess]:
        with self._lock:
            procs = list(self._procs.values())
        now = time.monotonic()
        return [p for p in procs if p.tree_alive and now - p.started_at > grace_s]


def _job_active_count(job_handle: Any) -> int | None:
    """Job 内活跃进程数（=0 才是整棵树归零）。"""
    if job_handle is None:
        return None
    try:
        acct = win32job.QueryInformationJobObject(job_handle, win32job.JobObjectBasicAccountingInformation)
        return int(acct["ActiveProcesses"])
    except Exception:
        return None


def _terminate_tree_state(proc: ManagedProcess) -> str:
    """终止整棵树，返回因果状态（外审 round7 P1-1）：

    - "dead_before"：调用时树已归零（自然退出），未发出终止请求；
    - "killed"：终止请求成功提交且随后确认 Job 归零；
    - "natural_exit"：终止请求提交失败，但随后树自然归零（保留真实 rc）；
    - "failed"：请求失败且树仍活（quarantined）。
    """
    if not proc.tree_alive:
        return "dead_before"
    requested = False
    try:
        win32job.TerminateJobObject(proc.job_handle, 137)
        requested = True
    except Exception:
        requested = False
    if requested:
        deadline = time.monotonic() + _TERMINATE_WAIT_S
        while time.monotonic() < deadline:
            if not proc.tree_alive:
                return "killed"
            time.sleep(0.05)
        proc.quarantined = True
        return "failed"
    # 请求失败：给自然退出一个短观察窗
    grace = time.monotonic() + 2.0
    while time.monotonic() < grace:
        if not proc.tree_alive:
            return "natural_exit"
        time.sleep(0.05)
    proc.quarantined = True
    return "failed"


def _terminate_and_confirm_tree(proc: ManagedProcess) -> bool:
    """布尔包装：failed → False（已 quarantine）；killed/natural_exit/dead_before → True。"""
    return _terminate_tree_state(proc) != "failed"


def _close_handles(proc: ManagedProcess) -> None:
    """确认树已归零后关闭句柄（唯一合法的关闭时机）。"""
    for attr in ("job_handle", "h_process", "h_thread"):
        h = getattr(proc, attr)
        if h is not None:
            try:
                win32api.CloseHandle(h)
            except Exception:
                pass
            setattr(proc, attr, None)


def _read_outputs(proc: ManagedProcess) -> None:
    """尾部限读：seek 到 (size - tail) 再读，内存不随文件大小线性增长。"""
    for attr, path in (("stdout_tail", proc.stdout_path), ("stderr_tail", proc.stderr_path)):
        if not path or not os.path.exists(path):
            continue
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as f:
                f.seek(max(0, size - _TAIL_BYTES))
                setattr(proc, attr, f.read()[-_TAIL_BYTES:])
        except OSError:
            pass


def _output_size(proc: ManagedProcess) -> int:
    total = 0
    for p in (proc.stdout_path, proc.stderr_path):
        if p and os.path.exists(p):
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
    return total


def _cleanup_files(proc: ManagedProcess) -> None:
    import shutil

    if proc.stdout_path:
        shutil.rmtree(os.path.dirname(proc.stdout_path), ignore_errors=True)
    proc.stdout_path = None
    proc.stderr_path = None


def _win_spawn_suspended(
    name: str, argv: list[str], cwd: str, env: dict[str, str]
) -> ManagedProcess:
    """Windows 原子启动（I-J7 提交序列）：挂起创建 → Job → assign →（注册后）resume。

    - 资源所有权分界点 = CreateProcess 成功；此后任何异常都有 guard 完成回滚
      （确认终止挂起 child → 关句柄 → 清 tmpdir；未确认 → JobSetupIncomplete 交 quarantine）。
    - std 句柄创建与 CreateProcess 全程持 _CREATE_LOCK（I-J6 弱保证窗口）。
    - 继承面（I-J6 v0.2 弱保证）：仅本函数创建的 3 个 std 句柄可继承；返回的
      process/thread 句柄不可继承；不保证第三方可继承句柄不被继承。
    - fail-closed：Job 创建/绑定失败 → 终止挂起进程并等待退出确认 → 清理 → 抛错；
      终止未确认 → JobSetupIncomplete(proc) 交调用方 quarantine。
    """
    import win32process
    import win32security

    with _CREATE_LOCK:
        tmpdir = tempfile.mkdtemp(prefix="mmagent_proc_")
        out_path = os.path.join(tmpdir, "stdout.txt")
        err_path = os.path.join(tmpdir, "stderr.txt")
        created: list[Any] = []
        # ManagedProcess 构造在 pre-create rollback scope 内（外审 round16 P1-1）：
        # 构造失败时 child 尚未创建，rollback 关闭空 created 集合 + 清 tmpdir 后抛出。
        # CreateProcess 成功 = 资源所有权移交分界点。
        proc = None
        try:
            proc = ManagedProcess(
                name=name, pid=0, argv=argv, stdout_path=out_path, stderr_path=err_path,
            )
            sa = win32security.SECURITY_ATTRIBUTES()
            sa.bInheritHandle = True
            h_out = win32file.CreateFile(
                out_path, win32file.GENERIC_WRITE, win32file.FILE_SHARE_READ, sa,
                win32file.CREATE_ALWAYS, win32file.FILE_ATTRIBUTE_NORMAL, None,
            )
            created.append(h_out)
            h_err = win32file.CreateFile(
                err_path, win32file.GENERIC_WRITE, win32file.FILE_SHARE_READ, sa,
                win32file.CREATE_ALWAYS, win32file.FILE_ATTRIBUTE_NORMAL, None,
            )
            created.append(h_err)
            h_in = win32file.CreateFile(
                "NUL", win32file.GENERIC_READ,
                win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE, sa,
                win32file.OPEN_EXISTING, win32file.FILE_ATTRIBUTE_NORMAL, None,
            )
            created.append(h_in)
            si = win32process.STARTUPINFO()
            si.dwFlags = win32process.STARTF_USESTDHANDLES
            si.hStdInput = h_in
            si.hStdOutput = h_out
            si.hStdError = h_err
            # process/thread SA=None → 返回句柄不可继承；CREATE_SUSPENDED(0x4)；
            # env 字典由 pywin32 原生构造环境块
            h_process, h_thread, _pid, _tid = win32process.CreateProcess(
                None, subprocess.list2cmdline(argv), None, None, True,
                win32process.CREATE_SUSPENDED, env, cwd, si,
            )
            # 所有权移交：child 自此刻起由 guard 管理
            proc.h_process = h_process
            proc.h_thread = h_thread
            proc.pid = _pid
        except Exception:
            # CreateProcess 之前失败：best-effort 逐个关闭已创建句柄 + 清 tmpdir
            # （cleanup 失败不遮蔽原始异常）
            for h in created:
                try:
                    win32file.CloseHandle(h)
                except Exception:
                    pass
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise
        else:
            # 子进程已继承，父侧副本关闭——best-effort：
            # 清理异常不截断 child 收口（外审 round11 P1-1）
            for h in (h_in, h_out, h_err):
                try:
                    win32file.CloseHandle(h)
                except Exception:
                    pass

        # ===== CreateProcess 成功：资源所有权分界点（此后异常必须回滚 child）=====
        try:
            job = win32job.CreateJobObject(None, "")
            try:
                ext = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
                ext["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, ext)
                win32job.AssignProcessToJobObject(job, h_process)
            except Exception:
                win32api.CloseHandle(job)  # Job 句柄不泄漏
                raise
            proc.job_handle = job
        except Exception as setup_err:
            # 挂起进程从未运行用户代码：确认终止 → 清理 → 抛 OSError；
            # 终止未确认 → JobSetupIncomplete(proc) 交调用方 quarantine（round6 P1-1）。
            confirmed = False
            try:
                win32api.TerminateProcess(h_process, 137)
                confirmed = win32event_wait(h_process)
            except Exception:
                pass
            if confirmed:
                for h in (h_thread, h_process):
                    try:
                        win32file.CloseHandle(h)
                    except Exception:
                        pass
                shutil.rmtree(tmpdir, ignore_errors=True)
                raise OSError(f"Job 绑定失败（已终止挂起进程）: {setup_err}") from setup_err
            proc.stdout_path = out_path
            proc.stderr_path = err_path
            raise JobSetupIncomplete(proc, "Job 绑定失败且挂起进程终止未确认") from setup_err
        return proc


def win32event_wait(h_process: Any, timeout_s: float = _TERMINATE_WAIT_S) -> bool:
    import win32event

    return win32event.WaitForSingleObject(h_process, int(timeout_s * 1000)) == win32event.WAIT_OBJECT_0


def _resume(proc: ManagedProcess) -> None:
    if proc.h_thread is not None:
        import win32api
        import win32process

        win32process.ResumeThread(proc.h_thread)
        win32api.CloseHandle(proc.h_thread)
        proc.h_thread = None


class ProcessManager:
    """spawn（原子挂起启动 + 显式提交序列）+ 树级确认等待/终止 + 输出预算 + 孤儿检测。

    所有树级生命周期操作（terminate/close/remove）都经 _commit_lock 串行化；
    cancel 回调同样在 gate 内执行，杜绝并发 close/query/terminate（round5/round9/round10）。
    """

    def __init__(self, *, output_quota_bytes: int = _DEFAULT_OUTPUT_QUOTA):
        self.output_quota_bytes = output_quota_bytes
        self.registry = ProcessRegistry()
        self._commit_lock = threading.RLock()  # lifecycle gate

    def spawn(
        self,
        name: str,
        argv: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ManagedProcess:
        """拉起进程（提交序列 I-J7）：挂起创建→Job→回收旧（树级确认）→publish→resume。

        resume 失败 → 确认终止 → 清理/隔离 + 移出注册 → 抛错。
        （shutdown 与 spawn 由 _commit_lock 线性化：publish 失败结构性不可达。）
        """
        with self._commit_lock:
            if not self.registry._accepting:
                raise RuntimeError("ProcessManager 已 shutdown，拒绝新 spawn（fail-fast）")
            try:
                proc = _win_spawn_suspended(name, argv, cwd, env)
            except JobSetupIncomplete as e:
                # 终止未确认：保留句柄，proc 入 quarantine（round6 P1-1）
                self.registry.quarantine(e.proc)
                raise RuntimeError(
                    "新进程 Job 绑定失败且终止未确认（quarantined）；需人工检查"
                ) from e
            with self.registry.name_lock(name):
                # 回收旧副本并确认整树死亡（round2/round8 P1-2）
                old = self.registry.get(name)
                if old is not None:
                    if not old.tree_exited:
                        if not _terminate_and_confirm_tree(old):
                            self.registry.quarantine(old)
                            if _terminate_and_confirm_tree(proc):
                                _close_handles(proc)
                                _cleanup_files(proc)
                            else:
                                self.registry.quarantine(proc)
                            raise RuntimeError(
                                f"旧进程 {name} 无法确认终止：已 quarantined；"
                                "新进程已终止（未运行任何用户代码）；需人工检查"
                            )
                    # 旧对象无论死活，回收句柄与临时文件，防泄漏
                    _close_handles(old)
                    _cleanup_files(old)
                self.registry.publish(proc)
                # resume 失败回滚（round9 P1-2）
                try:
                    _resume(proc)
                except Exception as e:
                    if _terminate_and_confirm_tree(proc):
                        _close_handles(proc)
                        _cleanup_files(proc)
                        self.registry.remove(name, expected=proc)
                    else:
                        self.registry.quarantine(proc)
                    raise RuntimeError(f"resume 失败，spawn 已回滚: {e}") from e
            return proc

    def communicate(
        self, proc: ManagedProcess, timeout_s: float, cancel=None
    ) -> tuple[int, bytes, bytes, bool]:
        """等待**整棵树**结束（生命周期判定与终止 authority 全部在 gate 内，round10 P1-1）。

        返回 (rc, stdout, stderr, timed_out)。
        取消三态 / 输出预算 / quarantined 语义见模块 docstring 与 I-J4/I-J5。
        """
        state = {"cancel_kill_confirmed": False, "cancel_kill_failed": False}
        if cancel is not None:

            def _on_cancel() -> None:
                with self._commit_lock:
                    if not proc.tree_alive:
                        return  # 自然归零：保留真实 rc（round7 因果性）
                    st = _terminate_tree_state(proc)
                    if st == "killed":
                        state["cancel_kill_confirmed"] = True
                    elif st == "natural_exit":
                        pass  # 自然归零：保留真实 rc
                    else:  # failed
                        state["cancel_kill_failed"] = True
                        self.registry.quarantine(proc)

            cancel.on_cancel(_on_cancel)

        deadline = time.monotonic() + timeout_s
        # 决策（存活/配额/超时/终止）与 cancel callback 共享同一 gate（round10 P1-1）
        while True:
            with self._commit_lock:
                # 每轮锁内先查取消失败（round11 P1-2：不得被后续 timeout 吞掉）
                if state["cancel_kill_failed"]:
                    self.registry.quarantine(proc)
                    raise ToolTimeout(
                        "进程的取消终止未确认（quarantined）——需人工检查"
                    )
                if not proc.tree_alive:
                    # 终态提交原子化：quota 最终检查 + 因果判定 + 输出快照都在 gate 内
                    if _output_size(proc) > self.output_quota_bytes:
                        _read_outputs(proc)
                        raise ToolTimeout(
                            "进程输出超过预算（进程已退出）"
                        )
                    _read_outputs(proc)
                    if state["cancel_kill_confirmed"]:
                        proc.rc = _CANCELLED_RC
                    rc = proc.rc if proc.rc is not None else 0
                    return rc, proc.stdout_tail, proc.stderr_tail, False
                if _output_size(proc) > self.output_quota_bytes:
                    st = _terminate_tree_state(proc)
                    _read_outputs(proc)
                    if st == "failed":
                        self.registry.quarantine(proc)
                        raise ToolTimeout(
                            "进程输出超限且终止未确认（quarantined）——需人工检查"
                        )
                    proc.rc = proc.rc if proc.rc is not None else 137
                    if state["cancel_kill_confirmed"]:
                        proc.rc = _CANCELLED_RC
                    raise ToolTimeout(
                        "进程输出超过预算，Job 已终止"
                    )
                if time.monotonic() >= deadline:
                    st = _terminate_tree_state(proc)
                    _read_outputs(proc)
                    if st == "failed":
                        self.registry.quarantine(proc)
                        raise ToolTimeout(
                            "进程超时且终止未确认（quarantined）——需人工检查"
                        )
                    proc.rc = proc.rc if proc.rc is not None else 137
                    if state["cancel_kill_confirmed"]:
                        proc.rc = _CANCELLED_RC
                    return proc.rc, proc.stdout_tail, proc.stderr_tail, True
            time.sleep(0.05)

    def kill(self, name: str) -> bool:
        with self._commit_lock:
            proc = self.registry.get(name)
            if proc is None:
                return False
            st = _terminate_tree_state(proc)
            if st == "failed":
                self.registry.quarantine(proc)
                return False
            return True

    def recycle(self, name: str, expected: ManagedProcess | None = None) -> bool:
        """回收（compare-and-remove）并确认整树死亡后才移出注册表。"""
        with self._commit_lock:
            proc = self.registry.get(name)
            if proc is None:
                return False
            if expected is not None and proc is not expected:
                return False
            if proc.tree_alive:
                st = _terminate_tree_state(proc)
                if st == "failed":
                    self.registry.quarantine(proc)
                    return False
            _close_handles(proc)
            _cleanup_files(proc)
            self.registry.remove(name, expected=proc)
            return True

    def shutdown(self) -> None:
        """Runtime 退出：关闭 accept + 收口全部托管进程与 quarantined（gate 内）。"""
        with self._commit_lock:
            self.registry._accepting = False
            procs = list(self.registry._procs.values())
        # identity-keyed unresolved 集（round11 P1-4）：瞬态终止失败在后续轮恢复时
        # 从 unresolved 移除，不产生 false failure；quarantined 列表保留为历史诊断。
        unresolved: dict[int, tuple[ManagedProcess, str]] = {}

        def _note_failure(p: ManagedProcess, msg: str) -> None:
            self.registry.quarantine(p)
            unresolved[id(p)] = (p, msg)

        def _resolve(p: ManagedProcess) -> None:
            # 统一 success 出口（完整 resolution primitive，round17 P1）：
            # close + cleanup + 移出隔离集合 + 清标记 + compare-and-remove 出 _procs
            # + 移出 unresolved
            _close_handles(p)
            _cleanup_files(p)
            self.registry.remove_quarantined(p)
            p.quarantined = False
            self.registry.remove(p.name, expected=p)
            unresolved.pop(id(p), None)

        for p in procs:
            with self._commit_lock:
                if p.tree_alive:
                    st = _terminate_tree_state(p)
                    if st == "failed":
                        _note_failure(p, f"{p.name}(pid={p.pid}) 终止未确认")
                        continue
                # 统一 success 出口：_resolve 内含 compare-and-remove（round17 P1）
                _resolve(p)
        # quarantined 收口：含无 Job 的挂起进程（JobSetupIncomplete）；确认收口 = _resolve
        # （close + cleanup + remove_quarantined + 清标记 + compare-and-remove + unresolved.pop）
        for q in self.registry.quarantined:
            with self._commit_lock:
                if q.tree_exited:
                    _resolve(q)
                    continue
                if q.job_handle is not None:
                    if _terminate_and_confirm_tree(q):
                        _resolve(q)
                        continue
                    _note_failure(q, f"quarantined {q.name} 终止仍未确认")
                    continue
                if q.h_process is not None:
                    # 无 Job 挂起进程：TerminateProcess（失败也继续）+ root 信号确认
                    try:
                        win32api.TerminateProcess(q.h_process, 137)
                    except Exception:
                        pass
                    if win32event_wait(q.h_process):
                        q.tree_exited = True
                        q.rc = 137
                        _resolve(q)
                        continue
                _note_failure(q, f"quarantined {q.name} 收口失败")
        if unresolved:
            details = [msg for _, msg in unresolved.values()]
            raise RuntimeError(f"shutdown 有 {len(details)} 个进程未能确认终止: {details}")
