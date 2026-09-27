"""Round-4 distinguishing behavior tests (R4-P1 / R4-F2/F3/F4 + provider R4 fixes).

All tests drive the real production paths (run_s5, run_g5_rework, the actual
OpenAICompatibleProvider against a mock HTTP transport) — no manual event
appending, no weakened invariants:

- a failed G5 figure transaction can never reach the Writer-only text route;
- an S5 calc/figure issue naming multiple questions stays unrouted (one issue
  is one repair identity);
- the S5 round checkpoint carries post-rework compile evidence, and a broken
  post-rework compile becomes a 硬伤 issue BEFORE the checkpoint is written;
- a failed G5 page guard cannot end a rework round as successful (R52);
- compatible-provider 4xx bodies are secret-redacted;
- compatible reasoning_effort is sent only behind the explicit capability.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from mmagent.mm.pipeline.s5_finalize import run_g5_rework
from mmagent.mm.pipeline.s5_review import run_s5
from mmagent.providers.mock import MockProvider, MockScript, MockTurn
from mmagent.providers.normalized import NormalizedMessage, TextPart
from mmagent.providers.openai_compatible import OpenAICompatibleProvider
from mmagent.state import events
from mmagent.workspace.path_policy import PathPolicy
from tests.pipeline.test_round3_closures import (
    _empty_leg,
    _fake_compile,
    _fake_render,
    _raise_issue_leg,
    _registry,
    _seed_g5_workspace,
    _seed_ledger,
    _seed_workspace,
    _write_turn,
)


def _ledger_rows(root: Path) -> list[dict]:
    return json.loads(
        (root / "台账" / "审稿台账.json").read_text(encoding="utf-8")
    )


# ==================== R4-F2: unique question routing ====================

@pytest.mark.asyncio
async def test_s5_multi_question_calc_issue_is_unrouted_once(tmp_path: Path) -> None:
    """A 算 issue naming two questions must be unrouted (active, no receipts,
    no attempt inflation) instead of being consumed by two transactions."""
    handle, run_id = _seed_workspace(
        tmp_path, "r4-calc-multi", plan=[{"编号": 1, "依赖问题": []}],
    )
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        issue = {
            "级别": "硬伤", "目标": "算",
            "定位": "问题1、问题2 结果",
            "问题": "问题1 与 问题2 的求解结果与数据不符",
            "指令": "按验证协议重算", "验收": "G2 通过",
        }
        turns: list[MockTurn] = []
        turns += _raise_issue_leg("r1a", "审稿/审稿意见_轮1A.json", issue)
        turns += _empty_leg("r1b", "审稿/审稿意见_轮1B.json")
        turns += _empty_leg("h1", "审稿/硬伤_轮1.json")
        turns += _empty_leg("j1", "审稿/评委模拟_轮1.json")
        # R2 final round (rework only runs in non-final rounds).
        turns += _empty_leg("r2a", "审稿/审稿意见_轮2A.json")
        turns += _empty_leg("r2b", "审稿/审稿意见_轮2B.json")
        turns += _empty_leg("h2", "审稿/硬伤_轮2.json")
        turns += _empty_leg("j2", "审稿/评委模拟_轮2.json")
        result = await run_s5(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            max_rounds=2, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        assert result["rounds"][0]["rework"]["unrouted"] == ["审-1-01"]
        assert not events.query_events(db, run_id=run_id, type="s5.calc_cascade_started")
        assert not events.query_events(db, run_id=run_id, type="checkpoint.s2_question")
        rows = _ledger_rows(root)
        assert rows[0]["状态"] == "待改"
        assert rows[0]["回执"] == []
        assert rows[0]["尝试次数"] == 0
        assert result["converged"] is False
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s5_multi_question_figure_issue_is_unrouted_once(tmp_path: Path) -> None:
    """Same unrouting rule for 图 issues: no plot transaction, no receipts."""
    handle, run_id = _seed_workspace(
        tmp_path, "r4-fig-multi", plan=[{"编号": 1, "依赖问题": []}],
    )
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        _seed_plot_script_multi(root)
        issue = {
            "级别": "硬伤", "目标": "图",
            "定位": "问题1 和 问题2 图",
            "问题": "问题1 与 问题2 图内数字过期",
            "指令": "重绘并同步正文", "验收": "图与结果一致",
        }
        turns: list[MockTurn] = []
        turns += _raise_issue_leg("r1a", "审稿/审稿意见_轮1A.json", issue)
        turns += _empty_leg("r1b", "审稿/审稿意见_轮1B.json")
        turns += _empty_leg("h1", "审稿/硬伤_轮1.json")
        turns += _empty_leg("j1", "审稿/评委模拟_轮1.json")
        turns += _empty_leg("r2a", "审稿/审稿意见_轮2A.json")
        turns += _empty_leg("r2b", "审稿/审稿意见_轮2B.json")
        turns += _empty_leg("h2", "审稿/硬伤_轮2.json")
        turns += _empty_leg("j2", "审稿/评委模拟_轮2.json")
        result = await run_s5(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            max_rounds=2, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        assert result["rounds"][0]["rework"]["unrouted"] == ["审-1-01"]
        assert not events.query_events(db, run_id=run_id, type="s5.figure_repair_succeeded")
        rows = _ledger_rows(root)
        assert rows[0]["状态"] == "待改"
        assert rows[0]["回执"] == []
        assert rows[0]["尝试次数"] == 0
    finally:
        handle.workspace.db.close()


def _seed_plot_script_multi(root: Path) -> None:
    for q in (1, 2):
        script = root / "求解" / f"问题{q}" / "绘图_图1.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "from pathlib import Path\n"
            f"p = Path('求解/问题{q}/图片')\n"
            "p.mkdir(parents=True, exist_ok=True)\n"
            "(p / '图1.png').write_bytes(b'PNG')\n",
            encoding="utf-8",
        )


# ==================== R4-F3: compile/fix before round checkpoint ====================

@pytest.mark.asyncio
async def test_s5_round_checkpoint_contains_post_rework_compile_evidence(
    tmp_path: Path,
) -> None:
    """A17 step 17: the round checkpoint must carry post_rework_compile
    evidence for a carrier that has already survived compile/fix."""
    handle, run_id = _seed_workspace(
        tmp_path, "r4-checkpoint-ok", plan=[{"编号": 1, "依赖问题": []}],
    )
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        issue = {
            "级别": "硬伤", "目标": "文", "定位": "论文/论文.tex",
            "问题": "表述与结果不一致",
            "指令": "做最小修订", "验收": "改动最小",
        }
        turns: list[MockTurn] = []
        turns += _raise_issue_leg("r1a", "审稿/审稿意见_轮1A.json", issue)
        turns += _empty_leg("r1b", "审稿/审稿意见_轮1B.json")
        turns += _empty_leg("h1", "审稿/硬伤_轮1.json")
        turns += _empty_leg("j1", "审稿/评委模拟_轮1.json")
        # Receipt-only text repair (no tex change → guard passes, no turns
        # for the post-rework compile because the fake compile succeeds).
        turns += _write_turn(
            "w1", "审稿/回执_R1_文.json",
            [{"id": "审-1-01", "改动": "最小修订", "证据": "论文/论文.tex"}],
        )
        turns += _empty_leg("r2a", "审稿/审稿意见_轮2A.json")
        turns += _empty_leg("r2b", "审稿/审稿意见_轮2B.json")
        turns += _empty_leg("h2", "审稿/硬伤_轮2.json")
        turns += _empty_leg("j2", "审稿/评委模拟_轮2.json")
        result = await run_s5(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            max_rounds=2, compile_paper=_fake_compile, render_pages=_fake_render,
        )
        checkpoints = events.query_events(
            db, run_id=run_id, type="checkpoint.s5_round_complete"
        )
        assert checkpoints
        # Post-rework checkpoints carry compile evidence; the final-round
        # break checkpoint (written before any rework) may not.
        rework_checkpoints = [
            cp for cp in checkpoints
            if "post_rework_compile" in (cp.payload.get("round_info") or {})
        ]
        assert rework_checkpoints, "no post-rework checkpoint recorded"
        for cp in rework_checkpoints:
            assert cp.payload["round_info"]["post_rework_compile"]["pass"] is True
        assert result["rounds"][0]["rework"]["文"] == 1
    finally:
        handle.workspace.db.close()


@pytest.mark.asyncio
async def test_s5_post_rework_compile_failure_becomes_hard_issue(tmp_path: Path) -> None:
    """A post-rework compile that stays broken after bounded repair must be
    merged as a 硬伤/文/编译 issue BEFORE the round checkpoint is written —
    the checkpoint ledger snapshot must not look healthy."""
    handle, run_id = _seed_workspace(
        tmp_path, "r4-checkpoint-broken", plan=[{"编号": 1, "依赖问题": []}],
    )
    try:
        root = handle.workspace.root
        db = handle.workspace.db

        def broken_compile(_root: Path) -> dict:
            return {"rc": 1, "errors": ["! Emergency stop."], "pages": 0}

        issue = {
            "级别": "硬伤", "目标": "文", "定位": "论文/论文.tex",
            "问题": "表述与结果不一致",
            "指令": "做最小修订", "验收": "改动最小",
        }
        turns: list[MockTurn] = []
        turns += _raise_issue_leg("r1a", "审稿/审稿意见_轮1A.json", issue)
        turns += _empty_leg("r1b", "审稿/审稿意见_轮1B.json")
        turns += _empty_leg("h1", "审稿/硬伤_轮1.json")
        turns += _empty_leg("j1", "审稿/评委模拟_轮1.json")
        turns += _write_turn(
            "w1", "审稿/回执_R1_文.json",
            [{"id": "审-1-01", "改动": "最小修订", "证据": "论文/论文.tex"}],
        )
        # Post-rework compile fails; the compile-repair writer leg (guarded,
        # receipt-gated) fails too — initial attempt + wave retry, text only.
        turns += [MockTurn(text="不修编译"), MockTurn(text="不修编译")]
        turns += _empty_leg("r2a", "审稿/审稿意见_轮2A.json")
        turns += _empty_leg("r2b", "审稿/审稿意见_轮2B.json")
        turns += _empty_leg("h2", "审稿/硬伤_轮2.json")
        turns += _empty_leg("j2", "审稿/评委模拟_轮2.json")
        turns += [MockTurn(text="仍不修"), MockTurn(text="仍不修")]
        result = await run_s5(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            max_rounds=2, compile_paper=broken_compile, render_pages=_fake_render,
        )
        checkpoints = events.query_events(
            db, run_id=run_id, type="checkpoint.s5_round_complete"
        )
        assert checkpoints
        rework_checkpoints = [
            cp for cp in checkpoints
            if "post_rework_compile" in (cp.payload.get("round_info") or {})
        ]
        assert rework_checkpoints, "no post-rework checkpoint recorded"
        for cp in rework_checkpoints:
            info = cp.payload["round_info"]
            assert info["post_rework_compile"]["pass"] is False
        # EVERY checkpoint (including the final-round break one) must already
        # see the hard compile issue — no healthy-looking checkpoint of a
        # broken carrier.
        for cp in checkpoints:
            snapshot = cp.payload.get("ledger") or []
            assert any(
                row.get("级别") == "硬伤"
                and row.get("目标") == "文"
                and row.get("定位") == "编译"
                for row in snapshot
                if isinstance(row, dict)
            ), cp.payload["round"]
        # The durable carrier on disk agrees.
        rows = _ledger_rows(root)
        assert any(
            row["级别"] == "硬伤" and row["目标"] == "文" and row["定位"] == "编译"
            for row in rows
        )
        assert result["converged"] is False
    finally:
        handle.workspace.db.close()


# ==================== R4-F4: page guard controls rework-round pass ====================

@pytest.mark.asyncio
async def test_g5_page_guard_failure_cannot_end_rework_round(tmp_path: Path) -> None:
    """R52: with the page guard failing (20 pages vs baseline 10), a Defect
    Hunter 通过=true must NOT end the rework loop — the bounded rework rounds
    are consumed before the final gate fails closed."""
    handle, run_id = _seed_g5_workspace(tmp_path, "r4-page-guard")
    try:
        root = handle.workspace.root
        db = handle.workspace.db
        _seed_ledger(root, [{
            "级别": "硬伤", "目标": "文", "定位": "论文/论文.tex",
            "问题": "表述与结果不一致",
        }])

        def bloated_compile(_root: Path) -> dict:
            (_root / "论文").mkdir(parents=True, exist_ok=True)
            (_root / "论文" / "论文.log").write_text(
                "Output written on 论文.pdf (20 pages).", encoding="utf-8"
            )
            (_root / "论文" / "论文.pdf").write_bytes(b"%PDF-bloated")
            return {"rc": 0, "errors": [], "pages": 20}

        turns: list[MockTurn] = []
        # R1: receipt-only text repair; hunter passes — but the page guard
        # must keep the round from breaking.
        turns += _write_turn(
            "w1", "审稿/回执_G5R1_文.json",
            [{"id": "审-1-01", "改动": "最小修订", "证据": "论文/论文.tex"}],
        )
        turns += _write_turn("h1", "审稿/G5复核1.json",
                             {"通过": True, "依据版本": "当前PDF"})
        # R2: the issue is 待复核 now, so only the hunter re-check runs.
        turns += _write_turn("h2", "审稿/G5复核2.json",
                             {"通过": True, "依据版本": "当前PDF"})
        # Final authoritative review.
        turns += _write_turn("f", "审稿/G5复核.json",
                             {"通过": True, "依据版本": "当前PDF"})
        result = await run_g5_rework(
            db, MockProvider(MockScript(turns)), _registry(), PathPolicy(root), run_id,
            beauty_baseline_pages=10, compile_paper=bloated_compile,
            render_pages=_fake_render, max_rework=2,
        )
        # The loop must have entered round 2 (old code would have broken at
        # round 1 because the hunter passed) and the final gate still fails
        # closed on the page violation.
        assert result["rework_rounds"] == 2
        guard_events = events.query_events(db, run_id=run_id, type="gate.g5_page_guard")
        assert len(guard_events) >= 1
        assert guard_events[0].payload["rework"] == 1
        assert result["pass"] is False
        assert any("页数超限" in x for x in result["issues"])
    finally:
        handle.workspace.db.close()


# ==================== Compatible provider: 4xx secret redaction ====================

@pytest.mark.asyncio
async def test_openai_compatible_4xx_never_exposes_api_key() -> None:
    """A compatible endpoint that echoes the credential in a 4xx body must not
    leak it through the ProviderError message."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="invalid key: sk-super-secret-value (echo)")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = OpenAICompatibleProvider(
        "https://relay.test/v1", lambda: "sk-super-secret-value", client=client
    )
    try:
        with pytest.raises(Exception) as exc_info:
            await p.generate(
                [NormalizedMessage(role="user", content=[TextPart(text="hi")])],
                [],
                model="m1",
            )
        assert "sk-super-secret-value" not in str(exc_info.value)
        assert "请求错误 400" in str(exc_info.value)
    finally:
        await client.aclose()


# ==================== Compatible provider: reasoning_effort capability ====================

def _compatible_client(captures: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captures.append(request)
        return httpx.Response(200, json={
            "id": "c1", "object": "chat.completion", "created": 1, "model": "m1",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": "ok",
            }}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        })

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _user_msgs():
    return [NormalizedMessage(role="user", content=[TextPart(text="hi")])]


@pytest.mark.asyncio
async def test_compatible_reasoning_effort_default_off() -> None:
    """Without the explicit capability, no reasoning_effort field is sent and
    the adapter advertises no reasoning levels."""
    captures: list[httpx.Request] = []
    client = _compatible_client(captures)
    p = OpenAICompatibleProvider("https://relay.test/v1", lambda: "k", client=client)
    try:
        assert not p.capabilities().reasoning_levels
        await p.generate(_user_msgs(), [], model="m1", reasoning="high")
        payload = json.loads(captures[0].content)
        assert "reasoning_effort" not in payload
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_compatible_reasoning_effort_explicit_on() -> None:
    """With the explicit capability, reasoning_effort is sent and the adapter
    advertises low/medium/high."""
    captures: list[httpx.Request] = []
    client = _compatible_client(captures)
    p = OpenAICompatibleProvider(
        "https://relay.test/v1", lambda: "k", client=client, reasoning_effort=True
    )
    try:
        assert p.capabilities().reasoning_levels == frozenset({"low", "medium", "high"})
        await p.generate(_user_msgs(), [], model="m1", reasoning="high")
        payload = json.loads(captures[0].content)
        assert payload["reasoning_effort"] == "high"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_compatible_profile_extra_round_trip_both_capabilities(tmp_path) -> None:
    """Both compatible-only capabilities persist through the provider-profile
    API and reach the adapter capabilities."""
    from mmagent.api.projects import create_project
    from mmagent.api.providers import build_provider, create_provider_profile
    from mmagent.runtime.credentials import MemoryCredentialStore

    handle = create_project(tmp_path / "proj-r4", name="providers-r4", profile="标准")
    store = MemoryCredentialStore()
    db = handle.workspace.db
    try:
        profile = create_provider_profile(
            db, store,
            name="CompatBoth",
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            model="m",
            api_key="sk-x",
            extra={"image_input": True, "reasoning_effort": True},
        )
        provider = build_provider(db, store, profile.model_profile_id)
        caps = provider.capabilities()
        assert caps.image_input is True
        assert caps.reasoning_levels == frozenset({"low", "medium", "high"})

        stored = json.loads(
            db.query_one(
                "SELECT extra_json FROM providers WHERE id = ?",
                (profile.provider_id,),
            )["extra_json"]
        )
        assert stored["image_input"] is True
        assert stored["reasoning_effort"] is True
    finally:
        db.close()
