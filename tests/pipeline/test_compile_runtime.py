from __future__ import annotations

import time
from pathlib import Path

import pytest

from mmagent.mm.pipeline.compile_runtime import run_compile
from mmagent.runtime.cancellation import CancellationToken


@pytest.mark.asyncio
async def test_compile_runtime_keeps_legacy_one_arg_hook_compatible(
    tmp_path: Path,
) -> None:
    seen: list[Path] = []

    def compiler(root: Path) -> dict:
        seen.append(root)
        return {"rc": 0, "errors": [], "pages": 3}

    result = await run_compile(compiler, tmp_path)

    assert result["pages"] == 3
    assert seen == [tmp_path]


@pytest.mark.asyncio
async def test_compile_runtime_passes_cancel_to_aware_hook(tmp_path: Path) -> None:
    token = CancellationToken()
    seen: dict[str, object] = {}

    def compiler(root: Path, *, cancel=None) -> dict:
        seen["root"] = root
        seen["cancel"] = cancel
        return {"rc": 0, "errors": [], "pages": 4}

    result = await run_compile(compiler, tmp_path, cancel=token)

    assert result["pages"] == 4
    assert seen == {"root": tmp_path, "cancel": token}


@pytest.mark.asyncio
async def test_compile_runtime_runs_blocking_hook_off_event_loop(
    tmp_path: Path,
) -> None:
    import asyncio

    marker = asyncio.Event()

    def compiler(root: Path) -> dict:
        time.sleep(0.08)
        return {"rc": 0, "errors": [], "pages": 1}

    task = asyncio.create_task(run_compile(compiler, tmp_path))
    await asyncio.sleep(0.01)
    marker.set()

    assert marker.is_set()
    assert not task.done()
    assert (await task)["rc"] == 0
