from __future__ import annotations

import pytest

from mmagent.mm.roles.prompts import ROLE_SYSTEM_PROMPTS, get_system_prompt
from mmagent.mm.roles.registry import role_ids


def test_every_registered_role_has_a_clean_room_prompt() -> None:
    assert set(ROLE_SYSTEM_PROMPTS) == set(role_ids())
    for role_id in role_ids():
        prompt = get_system_prompt(role_id)
        assert len(prompt.strip()) >= 80, role_id


def test_role_prompts_are_not_one_generic_template() -> None:
    prompts = {get_system_prompt(role_id).strip() for role_id in role_ids()}
    assert len(prompts) == 17


def test_red_team_prompt_reinforces_independent_recomputation() -> None:
    prompt = get_system_prompt("red_team")
    assert "独立" in prompt
    assert "不能读取" in prompt
    assert "口径" in prompt


def test_unknown_role_prompt_fails_closed() -> None:
    with pytest.raises(KeyError):
        get_system_prompt("not-a-role")
