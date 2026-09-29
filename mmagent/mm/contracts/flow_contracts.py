"""Cross-stage carrier contracts for the paper-foundry pipeline.

This registry captures *boundary ownership*: which stage is responsible for
publishing a durable carrier and which later stages are allowed to depend on it.

It deliberately does not pretend every S3-S6 JSON payload already has a full
Pydantic schema.  Field-level schemas remain separate.  The purpose here is to
mechanically reject orphan consumers, backwards dependencies, and ambiguous
multi-stage ownership while those richer schemas are completed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

STAGE_ORDER = (
    "S0",
    "S1",
    "S2",
    "S3",
    "S4",
    "S5",
    "S5a",
    "S5b",
    "G5",
    "S6",
)
_STAGE_INDEX = {stage: index for index, stage in enumerate(STAGE_ORDER)}

EXTERNAL_SOURCES = frozenset({
    "输入/题目/**",
    "输入/数据/**",
})


@dataclass(frozen=True)
class StageCarrierContract:
    stage: str
    consumes: tuple[str, ...] = ()
    self_consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()


STAGE_CARRIER_CONTRACTS: tuple[StageCarrierContract, ...] = (
    StageCarrierContract(
        "S0",
        consumes=("输入/题目/**", "输入/数据/**"),
        produces=(
            "交接/题面契约.json",
            "交接/数据档案.json",
            "交接/典型答卷预测.md",
            "交接/需求追踪矩阵.json",
        ),
    ),
    StageCarrierContract(
        "S1",
        consumes=(
            "交接/题面契约.json",
            "交接/数据档案.json",
            "交接/需求追踪矩阵.json",
        ),
        produces=(
            "交接/路线侦察.json",
            "交接/计划.json",
            "求解/问题{q}/原型_{i}.py",
        ),
    ),
    StageCarrierContract(
        "S2",
        consumes=(
            "交接/计划.json",
            "输入/数据/**",
        ),
        self_consumes=("交接/结果声明_问题{dep}.json",),
        produces=(
            "求解/问题{q}/求解_问题{q}.py",
            "求解/问题{q}/结果/**",
            "交接/结果声明_问题{q}.json",
            "交接/结果解读_问题{q}.md",
            "交接/红队_问题{q}.json",
            "交接/仲裁_问题{q}.json",
            "交接/降级放行.json",
        ),
    ),
    StageCarrierContract(
        "S3",
        consumes=(
            "交接/结果声明_问题{q}.json",
            "求解/问题{q}/结果/**",
        ),
        produces=(
            "交接/图注素材_问题{q}.json",
            "求解/问题{q}/绘图_*.py",
            "求解/问题{q}/图片/*.png",
            "审稿/图评R{round}_问题{q}*.json",
        ),
    ),
    StageCarrierContract(
        "S4",
        consumes=(
            "交接/需求追踪矩阵.json",
            "交接/结果声明_问题{q}.json",
            "交接/图注素材_问题{q}.json",
            "求解/问题{q}/图片/*.png",
        ),
        produces=(
            "交接/叙事底稿.md",
            "交接/论点脊柱.json",
            "交接/需求覆盖.json",
            "论文/论文.tex",
            "论文/0.摘要.tex",
            "审稿/章评R{round}.json",
            "审稿/读者R{round}.json",
        ),
    ),
    StageCarrierContract(
        "S5",
        consumes=(
            "论文/论文.tex",
            "论文/0.摘要.tex",
            "交接/需求追踪矩阵.json",
        ),
        produces=(
            "论文/论文.tex",
            "台账/审稿台账.json",
            "审稿/审稿台账_视图.json",
            "审稿/审稿意见_轮{round}*.json",
            "审稿/硬伤_轮{round}.json",
            "审稿/评委模拟_轮{round}.json",
        ),
    ),
    StageCarrierContract(
        "S5a",
        consumes=("论文/论文.tex", "论文/0.摘要.tex"),
        produces=("论文/0.摘要.tex", "审稿/摘要复述_定稿{attempt}.json"),
    ),
    StageCarrierContract(
        "S5b",
        consumes=("论文/论文.tex", "论文/0.摘要.tex"),
        produces=(
            "论文/论文.tex",
            "审稿/美{round}*.json",
            "审稿/回执_美化R{round}_*.json",
        ),
    ),
    StageCarrierContract(
        "G5",
        consumes=(
            "论文/论文.tex",
            "论文/0.摘要.tex",
            "审稿/审稿台账_视图.json",
        ),
        produces=("审稿/G5复核.json",),
    ),
    StageCarrierContract(
        "S6",
        consumes=(
            "论文/论文.tex",
            "论文/0.摘要.tex",
            "审稿/G5复核.json",
        ),
        produces=(
            "交付/论文.pdf",
            "交付/论文源码/**",
            "交付/求解源码/**",
            "交付/交接/**",
            "审稿/回流账.json",
            "审稿/复盘报告.json",
        ),
    ),
)


_PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")


def canonical_carrier(pattern: str) -> str:
    """Normalize template variable names without weakening path structure."""
    return _PLACEHOLDER_RE.sub("{*}", pattern)


def validate_stage_carrier_contracts(
    contracts: tuple[StageCarrierContract, ...] = STAGE_CARRIER_CONTRACTS,
) -> list[str]:
    """Return structural contract errors; an empty list means the graph is valid."""
    issues: list[str] = []
    seen_stages: set[str] = set()
    producer_history: dict[str, list[str]] = {}

    for contract in contracts:
        stage = contract.stage
        if stage not in _STAGE_INDEX:
            issues.append(f"unknown stage: {stage}")
            continue
        if stage in seen_stages:
            issues.append(f"duplicate stage contract: {stage}")
            continue
        seen_stages.add(stage)

        own_produces = {
            canonical_carrier(raw) for raw in contract.produces
        }
        for raw in contract.consumes:
            carrier = canonical_carrier(raw)
            if carrier in {canonical_carrier(x) for x in EXTERNAL_SOURCES}:
                continue
            producers = producer_history.get(carrier, [])
            if not producers:
                issues.append(f"{stage} consumes orphan carrier: {raw}")
                continue
            latest = producers[-1]
            if _STAGE_INDEX[latest] >= _STAGE_INDEX[stage]:
                issues.append(
                    f"{stage} consumes non-upstream carrier {raw} from {latest}"
                )

        for raw in contract.self_consumes:
            carrier = canonical_carrier(raw)
            if carrier not in own_produces:
                issues.append(
                    f"{stage} self-consumes unproduced carrier: {raw}"
                )

        for raw in contract.produces:
            carrier = canonical_carrier(raw)
            producer_history.setdefault(carrier, []).append(stage)

    missing = [stage for stage in STAGE_ORDER if stage not in seen_stages]
    for stage in missing:
        issues.append(f"missing stage contract: {stage}")
    return issues


def producer_chain(pattern: str) -> tuple[str, ...]:
    carrier = canonical_carrier(pattern)
    return tuple(
        contract.stage
        for contract in STAGE_CARRIER_CONTRACTS
        if carrier in {canonical_carrier(x) for x in contract.produces}
    )
