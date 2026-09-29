from __future__ import annotations

import pytest

from mmagent.mm.config.profiles import get_profile, normalize_profile


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("标准", "标准"),
        ("standard", "标准"),
        ("normal", "标准"),
        ("深度", "深度"),
        ("deep", "深度"),
        ("快速", "快速"),
        ("quick", "快速"),
        ("fast", "快速"),
    ],
)
def test_profile_aliases_are_normalized(raw: str, canonical: str) -> None:
    assert normalize_profile(raw) == canonical
    assert get_profile(raw).tier == canonical


def test_unknown_profile_fails_closed() -> None:
    with pytest.raises(ValueError):
        normalize_profile("turbo")
