from __future__ import annotations

from mmagent.mm.pipeline.topology import GATES, PIPELINE_SEQUENCE, STAGES
from mmagent.mm.roles.registry import role_ids


def test_pipeline_sequence_is_complete_and_ordered() -> None:
    assert PIPELINE_SEQUENCE == (
        "S0", "G0",
        "S1", "G1",
        "S2", "G2",
        "S3", "G3",
        "S4", "G4",
        "S5", "S5a", "S5b", "G5",
        "S6",
    )


def test_all_gates_exist_once_and_g2_is_per_question() -> None:
    assert tuple(g.gate_id for g in GATES) == ("G0", "G1", "G2", "G3", "G4", "G5")
    assert next(g for g in GATES if g.gate_id == "G2").per_question is True
    assert all(not g.per_question for g in GATES if g.gate_id != "G2")


def test_all_17_registered_roles_are_represented_in_workflow() -> None:
    workflow_roles = {role for s in STAGES for role in s.roles}
    assert set(role_ids()) == workflow_roles


def test_stage_ids_are_unique() -> None:
    ids = [s.stage_id for s in STAGES]
    assert len(ids) == len(set(ids))
