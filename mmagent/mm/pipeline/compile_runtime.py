"""Async bridge for synchronous paper compilers used by S4-S6."""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _accepts_cancel(compiler: Callable[..., Any]) -> bool:
    try:
        signature = inspect.signature(compiler)
    except (TypeError, ValueError):
        return False
    if "cancel" in signature.parameters:
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


async def run_compile(
    compiler: Callable[..., dict[str, Any]],
    root: Path,
    *,
    cancel=None,
) -> dict[str, Any]:
    """Run a blocking compiler off the sidecar event loop.

    New runtime compilers may accept a cancellation token. Existing one-argument
    test hooks remain compatible and are still executed in a worker thread.
    """
    if cancel is not None:
        cancel.check()

    def invoke() -> dict[str, Any]:
        if cancel is not None and _accepts_cancel(compiler):
            return compiler(root, cancel=cancel)
        return compiler(root)

    result = await asyncio.to_thread(invoke)
    if cancel is not None:
        cancel.check()
    return result
