from __future__ import annotations

from mmagent.mm.contracts.flow_contracts import (
    STAGE_CARRIER_CONTRACTS,
    STAGE_ORDER,
    StageCarrierContract,
    canonical_carrier,
    producer_chain,
    validate_stage_carrier_contracts,
)


def test_authoritative_stage_carrier_graph_is_structurally_valid() -> None:
    assert validate_stage_carrier_contracts() == []
    assert tuple(item.stage for item in STAGE_CARRIER_CONTRACTS) == STAGE_ORDER


def test_template_variable_names_normalize_to_same_carrier() -> None:
    assert canonical_carrier("交接/结果声明_问题{q}.json") == canonical_carrier(
        "交接/结果声明_问题{dep}.json"
    )


def test_s2_self_feed_is_explicitly_produced_by_s2() -> None:
    s2 = next(item for item in STAGE_CARRIER_CONTRACTS if item.stage == "S2")
    assert canonical_carrier(s2.self_consumes[0]) in {
        canonical_carrier(item) for item in s2.produces
    }


def test_orphan_cross_stage_consumer_is_rejected() -> None:
    contracts = tuple(
        StageCarrierContract(
            stage=item.stage,
            consumes=(
                item.consumes + ("交接/不存在.json",)
                if item.stage == "S4"
                else item.consumes
            ),
            self_consumes=item.self_consumes,
            produces=item.produces,
        )
        for item in STAGE_CARRIER_CONTRACTS
    )

    issues = validate_stage_carrier_contracts(contracts)

    assert any("S4 consumes orphan carrier: 交接/不存在.json" in x for x in issues)


def test_unbacked_same_stage_consumer_is_rejected() -> None:
    contracts = tuple(
        StageCarrierContract(
            stage=item.stage,
            consumes=item.consumes,
            self_consumes=(
                item.self_consumes + ("交接/未生产_问题{q}.json",)
                if item.stage == "S2"
                else item.self_consumes
            ),
            produces=item.produces,
        )
        for item in STAGE_CARRIER_CONTRACTS
    )

    issues = validate_stage_carrier_contracts(contracts)

    assert any("S2 self-consumes unproduced carrier" in x for x in issues)


def test_mutable_paper_carrier_has_ordered_producer_chain() -> None:
    assert producer_chain("论文/论文.tex") == ("S4", "S5", "S5b")
