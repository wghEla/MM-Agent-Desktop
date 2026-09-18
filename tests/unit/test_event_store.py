"""事件存储单测：append-only 触发器、顺序、过滤、可回放。"""
from __future__ import annotations

import pytest

from mmagent.state import events, repositories


def test_append_and_query_order(db, run_id):
    for i in range(5):
        events.append_event(db, "ev", {"i": i}, run_id=run_id)
    evs = [e for e in events.query_events(db, run_id=run_id) if e.type == "ev"]
    assert [e.payload["i"] for e in evs] == [0, 1, 2, 3, 4]
    assert evs[0].id < evs[-1].id


def test_append_only_no_update_no_delete(db, run_id):
    events.append_event(db, "ev", {"x": 1}, run_id=run_id)
    with pytest.raises(Exception, match="append-only"):
        db.execute("UPDATE events SET type = 'hacked'")
    with pytest.raises(Exception, match="append-only"):
        db.execute("DELETE FROM events")


def test_filter_by_type_and_task(db, run_id):
    t = repositories.create_task(db, run_id=run_id, stage_key="S0", node_key="S0.0")
    events.append_event(db, "a", {}, run_id=run_id)
    events.append_event(db, "b", {}, run_id=run_id, task_id=t.id)
    assert [e.type for e in events.query_events(db, type="b")] == ["b"]
    assert all(e.task_id == t.id for e in events.query_events(db, task_id=t.id))


def test_after_id_pagination(db, run_id):
    ids = [events.append_event(db, "ev", {"n": i}) for i in range(10)]
    page2 = events.query_events(db, after_id=ids[4], limit=100)
    assert page2[0].id == ids[5]
