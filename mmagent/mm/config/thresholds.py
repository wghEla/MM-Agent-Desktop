"""质量阈值默认值 — 复现上游行为值（总方案 §33，FIDELITY_MATRIX D 组）。

这些值是"用户的决定"（原 Skill 铁律 11）：v1 前不提供 UI 修改入口。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    red_team_relative_tolerance: float = 0.01

    figure_review_rounds: int = 2
    figure_review_threshold: float = 7.0

    chapter_review_rounds: int = 2
    chapter_review_threshold: float = 7.0

    review_score_target: float = 8.6
    review_plateau: float = 0.15

    beauty_threshold: float = 8.5

    change_guard_normal: float = 0.45
    change_guard_escalated: float = 0.70
    page_guard_growth: float = 0.10
    page_guard_min_pages: int = 2

    fuse_attempt_threshold: int = 2
    gate_max_rework: int = 2
    escalation_variants: int = 3

    default_concurrency: int = 4
    min_concurrency: int = 2

    max_body_pages: int = 20
    figures_min: int = 16
    figures_max: int = 22
    src_annotation_coverage: float = 0.6
    decimal_places_max: int = 4

    max_legs: int = 600
    max_hours_deep: float = 40.0
    max_hours_standard: float = 30.0
    max_hours_quick: float = 20.0


DEFAULT_THRESHOLDS = Thresholds()

# 角色分档（复现上游 LEG_EFFORT 分档表；reasoning 协议不支持时由 Provider 如实声明）
ROLE_REASONING_TIERS: dict[str, str] = {
    # 算/证/裁 → xhigh
    "reader": "xhigh",
    "answer_predictor": "xhigh",
    "planner": "xhigh",
    "modeler": "xhigh",
    "red_team": "xhigh",
    "interpreter": "xhigh",
    # 写/审 → high
    "writer": "high",
    "reviewer": "high",
    "defect_hunter": "high",
    "chapter_reviewer": "high",
    "integrator": "high",
    "plotter": "high",
    # 看图/闭卷/第一印象 → medium
    "figure_reviewer": "medium",
    "beautifier": "medium",
    "judge_simulator": "medium",
    "blind_reader": "medium",
    "retrospector": "medium",
}
