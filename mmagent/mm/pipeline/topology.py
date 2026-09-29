"""Canonical MM-Final-Skill-compatible pipeline topology.

This module is intentionally declarative: it records the domain workflow that the
runtime must implement.  A stage being present here does *not* mean its execution
code is implemented.

Reference behavior (clean-room summary):
S0 -> G0 -> S1 -> G1 -> S2 -> G2(per question) -> S3 -> G3 -> S4 -> G4
-> S5 -> S5a -> S5b -> G5 -> S6.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateSpec:
    gate_id: str
    after_stage: str
    per_question: bool = False


@dataclass(frozen=True)
class StageSpec:
    stage_id: str
    display_name: str
    steps: tuple[str, ...]
    roles: tuple[str, ...]


STAGES: tuple[StageSpec, ...] = (
    StageSpec(
        "S0",
        "吃透题目",
        ("seed", "problem_reading", "reading_check", "answer_prediction", "trace_matrix"),
        ("reader", "answer_predictor"),
    ),
    StageSpec(
        "S1",
        "战略锦标赛",
        ("route_scout", "prototype_run", "adjudication", "plan_finalize"),
        ("planner", "modeler"),
    ),
    StageSpec(
        "S2",
        "建模求解",
        (
            "dag_layering",
            "model",
            "red_team_recompute",
            "compare",
            "arbitrate",
            "interpret",
            "repair",
            "escalation_swarm",
            "degraded_release",
        ),
        ("modeler", "red_team", "interpreter"),
    ),
    StageSpec(
        "S3",
        "图证",
        ("plot", "figure_review", "targeted_figure_revision"),
        ("plotter", "figure_reviewer"),
    ),
    StageSpec(
        "S4",
        "撰稿",
        (
            "narrative_draft",
            "paper_spine",
            "write",
            "chapter_review",
            "blind_reader",
            "targeted_revision",
            "editorial_guard",
            "integrate",
            "abstract_swarm",
            "abstract_restate_gate",
        ),
        ("writer", "chapter_reviewer", "blind_reader", "integrator"),
    ),
    StageSpec(
        "S5",
        "审稿场",
        (
            "compile",
            "render_pages",
            "audit",
            "mechanical_review",
            "reviewer_a",
            "reviewer_b",
            "defect_hunt",
            "judge_simulation",
            "merge_verdicts",
            "ledger_merge",
            "convergence_check",
            "fuse",
            "rework_calc",
            "rework_figure",
            "rework_text",
            "change_guard",
            "compile_repair",
            "round_checkpoint",
        ),
        ("reviewer", "defect_hunter", "judge_simulator", "modeler", "plotter", "writer"),
    ),
    StageSpec(
        "S5a",
        "摘要定稿",
        ("abstract_finalize", "abstract_restate_gate"),
        ("blind_reader", "writer"),
    ),
    StageSpec(
        "S5b",
        "美化",
        ("page_review", "figure_beautify", "text_layout", "compile", "page_guard"),
        ("beautifier", "plotter", "writer"),
    ),
    StageSpec(
        "S6",
        "出版复盘",
        ("page_final_review", "final_fixes", "final_compile", "harvest", "retrospective"),
        ("beautifier", "writer", "retrospector"),
    ),
)

GATES: tuple[GateSpec, ...] = (
    GateSpec("G0", "S0"),
    GateSpec("G1", "S1"),
    GateSpec("G2", "S2", per_question=True),
    GateSpec("G3", "S3"),
    GateSpec("G4", "S4"),
    GateSpec("G5", "S5b"),
)

PIPELINE_SEQUENCE: tuple[str, ...] = (
    "S0", "G0",
    "S1", "G1",
    "S2", "G2",
    "S3", "G3",
    "S4", "G4",
    "S5", "S5a", "S5b", "G5",
    "S6",
)


def stage(stage_id: str) -> StageSpec:
    return next(s for s in STAGES if s.stage_id == stage_id)


def gate(gate_id: str) -> GateSpec:
    return next(g for g in GATES if g.gate_id == gate_id)
