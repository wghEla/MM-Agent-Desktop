"""问题 DAG（拓扑分层 / 环检测 / 下游闭包）—— 复现上游 调度器.py 语义。"""
from __future__ import annotations


def build_dependency_graph(problem_list: list[dict]) -> dict[int, list[int]]:
    """从计划.json 的问题清单构建 {编号: [依赖编号]}。非法依赖丢弃。"""
    graph: dict[int, list[int]] = {}
    for q in problem_list:
        try:
            num = int(q.get("编号"))
        except (TypeError, ValueError):
            continue
        graph[num] = []
    for q in problem_list:
        try:
            num = int(q.get("编号"))
        except (TypeError, ValueError):
            continue
        for dep in q.get("依赖问题") or []:
            try:
                d = int(dep)
            except (TypeError, ValueError):
                continue
            if d in graph and d != num and d not in graph[num]:
                graph[num].append(d)
    return graph


def detect_cycle(graph: dict[int, list[int]]) -> list[int]:
    """返回参与环的节点列表（空 = 无环）。自环也算。"""
    visited: dict[int, int] = {}  # 0=未访问 1=在栈 2=完成
    cycle: set[int] = set()

    def dfs(n: int, stack: list[int]) -> None:
        visited[n] = 1
        stack.append(n)
        for d in graph.get(n, []):
            state = visited.get(d, 0)
            if state == 1:
                if d in stack:
                    cycle.update(stack[stack.index(d):])
                else:
                    cycle.add(d)
            elif state == 0:
                dfs(d, stack)
        stack.pop()
        visited[n] = 2

    for n in graph:
        if visited.get(n, 0) == 0:
            dfs(n, [])
    return sorted(cycle)


def topological_layers(graph: dict[int, list[int]]) -> list[list[int]]:
    """返回 [[同层可并行编号...], ...]。有环抛 ValueError。"""
    cycle = detect_cycle(graph)
    if cycle:
        raise ValueError(f"问题依赖图存在环: {cycle}")
    remaining = {n: set(d for d in graph[n] if d in graph) for n in graph}
    layers: list[list[int]] = []
    done: set[int] = set()
    while remaining:
        layer = sorted(n for n, deps in remaining.items() if not (deps - done))
        if not layer:
            raise ValueError(f"依赖无法推进（疑似环）: {sorted(remaining)}")
        layers.append(layer)
        done |= set(layer)
        for n in layer:
            del remaining[n]
    return layers


def all_downstreams(graph: dict[int, list[int]], source: int) -> list[int]:
    """传递闭包下游（不含自身）。"""
    result: set[int] = set()
    queue = [source]
    while queue:
        cur = queue.pop()
        for n, deps in graph.items():
            if cur in deps and n not in result:
                result.add(n)
                queue.append(n)
    return sorted(result)
