"""Three execution profiles (深度/标准/快速).

The persisted/API layer historically used both English and Chinese spellings.
Normalize them here so every pipeline stage consumes one canonical tier.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ProfileTier = Literal["深度", "标准", "快速"]


@dataclass(frozen=True)
class Profile:
    tier: ProfileTier
    全问开锦标赛: bool
    每问路线数: int
    摘要变体数: int
    图评轮数: int = 2
    章评轮数: int = 2
    审稿轮数: int = 4
    美化轮数: int = 2
    max_legs: int = 600
    max_hours: float = 40.0
    角色分档: bool = False
    描述: str = ""


深度 = Profile(
    tier="深度", 全问开锦标赛=True, 每问路线数=3, 摘要变体数=5,
    审稿轮数=4, 美化轮数=2, max_hours=40.0, 角色分档=False,
    描述="全开：全问锦标赛、3 路线、5 摘要变体、4 审稿轮、全员同档推理",
)

标准 = Profile(
    tier="标准", 全问开锦标赛=True, 每问路线数=3, 摘要变体数=3,
    审稿轮数=3, 美化轮数=2, max_hours=30.0, 角色分档=True,
    描述="角色分档推理、3 摘要变体、3 审稿轮、30h 上限",
)

快速 = Profile(
    tier="快速", 全问开锦标赛=False, 每问路线数=2, 摘要变体数=3,
    图评轮数=2, 章评轮数=2, 审稿轮数=2, 美化轮数=1, max_hours=20.0,
    角色分档=False,
    描述="冒烟：只最难问锦标赛、2 路线、2 审稿轮、20h 上限",
)

_PROFILES: dict[str, Profile] = {"深度": 深度, "标准": 标准, "快速": 快速}
_ALIASES: dict[str, ProfileTier] = {
    "deep": "深度",
    "depth": "深度",
    "standard": "标准",
    "normal": "标准",
    "quick": "快速",
    "fast": "快速",
}


def normalize_profile(tier: str) -> ProfileTier:
    value = str(tier).strip()
    if value in _PROFILES:
        return value  # type: ignore[return-value]
    canonical = _ALIASES.get(value.lower())
    if canonical is None:
        raise ValueError(
            f"未知档位 {tier!r}：可选 深度/标准/快速（兼容 deep/standard/quick）"
        )
    return canonical


def get_profile(tier: str) -> Profile:
    return _PROFILES[normalize_profile(tier)]


def all_profiles() -> dict[str, Profile]:
    return dict(_PROFILES)
