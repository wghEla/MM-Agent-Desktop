"""协作式取消令牌。

语义：
- cancel() 是幂等的；之后 is_cancelled 恒真，check() 抛 TaskCancelled；
- 支持注册回调（工具层用来终止子进程）；
- 不强制抢占：只在安全边界（turn 之间、工具调用前后）检查，复现原 Skill
  「正在执行的安全工具允许到边界或按策略取消」的语义。
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._async_event: asyncio.Event | None = None
        self._callbacks: list[Callable[[], None]] = []
        self._reason: str | None = None

    # ------------------------------------------------------------- 状态
    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        return self._reason

    def check(self) -> None:
        from mmagent.agent.errors import TaskCancelled

        if self._event.is_set():
            raise TaskCancelled(self._reason or "cancelled")

    # ------------------------------------------------------------- 触发
    def cancel(self, reason: str = "cancelled") -> None:
        if self._event.is_set():
            return
        self._reason = reason
        self._event.set()
        for cb in list(self._callbacks):
            try:
                cb()
            except Exception:
                # 回调（如杀进程）失败不能阻断取消传播；孤儿检测由进程层兜底
                pass

    def on_cancel(self, callback: Callable[[], None]) -> None:
        if self._event.is_set():
            callback()
            return
        self._callbacks.append(callback)

    # ------------------------------------------------------------- async 侧
    async def wait(self) -> None:
        if not self._event.is_set():
            await asyncio.to_thread(self._event.wait)
