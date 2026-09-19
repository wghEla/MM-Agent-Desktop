"""DAG 拓扑/环/下游闭包单测（复现上游 调度器.py 自测语义）。"""
from __future__ import annotations

import pytest

from mmagent.orchestration.dag import (
    all_downstreams,
    build_dependency_graph,
    detect_cycle,
    topological_layers,
)


class TestDAG:
    def test_basic_topology(self):
        g = build_dependency_graph([
            {"编号": 1, "依赖问题": []},
            {"编号": 2, "依赖问题": [1]},
            {"编号": 3, "依赖问题": []},
        ])
        assert topological_layers(g) == [[1, 3], [2]]

    def test_chain(self):
        g = build_dependency_graph([
            {"编号": 1, "依赖问题": []},
            {"编号": 2, "依赖问题": [1]},
            {"编号": 3, "依赖问题": [2]},
        ])
        assert topological_layers(g) == [[1], [2], [3]]
        assert all_downstreams(g, 1) == [2, 3]

    def test_cycle_detected(self):
        g = build_dependency_graph([
            {"编号": 1, "依赖问题": [2]},
            {"编号": 2, "依赖问题": [1]},
        ])
        assert detect_cycle(g) == [1, 2]
        with pytest.raises(ValueError, match="环"):
            topological_layers(g)

    def test_self_dependency_dropped(self):
        g = build_dependency_graph([{"编号": 1, "依赖问题": [1]}])
        assert g == {1: []}

    def test_invalid_dependency_dropped(self):
        g = build_dependency_graph([
            {"编号": 1, "依赖问题": []},
            {"编号": 2, "依赖问题": [999]},  # 不存在的编号
        ])
        assert g[2] == []

    def test_all_downstreams_multi(self):
        g = build_dependency_graph([
            {"编号": 1, "依赖问题": []},
            {"编号": 2, "依赖问题": [1]},
            {"编号": 3, "依赖问题": [1]},
            {"编号": 4, "依赖问题": [2, 3]},
        ])
        assert sorted(all_downstreams(g, 1)) == [2, 3, 4]
        assert all_downstreams(g, 4) == []
