"""
Auto Layout Engine for DeepAgents Copilot.

使用 networkx 实现分层布局算法，解决 LLM 无法生成整齐 ReactFlow 坐标的问题。
采用拓扑排序 + 分层布局，确保：
- Manager 节点在左侧
- 子代理节点垂直排列在右侧
- 自动避免节点重叠
- 边连接整齐美观
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

from loguru import logger

try:
    import networkx as nx

    NETWORKX_AVAILABLE = True
except ImportError:
    nx = None
    NETWORKX_AVAILABLE = False
    logger.warning("[LayoutEngine] networkx not available, using fallback layout")


def apply_auto_layout(
    blueprint_data: Dict[str, Any],
    x_spacing: int = 300,
    y_spacing: int = 150,
    start_x: int = 100,
    start_y: int = 100,
) -> Dict[str, Any]:
    """
    使用拓扑排序计算分层布局，覆盖 LLM 生成的坐标。

    Args:
        blueprint_data: 包含 nodes 和 edges 的 blueprint 字典
        x_spacing: 水平方向节点间距
        y_spacing: 垂直方向节点间距
        start_x: 起始 X 坐标
        start_y: 起始 Y 坐标

    Returns:
        更新了 position 的 blueprint_data
    """
    nodes = blueprint_data.get("nodes", [])
    blueprint_data.get("edges", [])

    if not nodes:
        return blueprint_data

    if NETWORKX_AVAILABLE:
        return _apply_networkx_layout(blueprint_data, x_spacing, y_spacing, start_x, start_y)
    else:
        return _apply_fallback_layout(blueprint_data, x_spacing, y_spacing, start_x, start_y)


def _apply_networkx_layout(
    blueprint_data: Dict[str, Any],
    x_spacing: int,
    y_spacing: int,
    start_x: int,
    start_y: int,
) -> Dict[str, Any]:
    """使用 networkx 实现分层布局"""
    nodes = blueprint_data.get("nodes", [])
    edges = blueprint_data.get("edges", [])

    # 构建有向图
    G = nx.DiGraph()
    node_map = {n["id"]: n for n in nodes}

    for node in nodes:
        G.add_node(node["id"])
    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        if source in node_map and target in node_map:
            G.add_edge(source, target)

    # 处理可能存在的环（打破环以便拓扑排序）
    if not nx.is_directed_acyclic_graph(G):
        logger.warning("[LayoutEngine] Graph has cycles, attempting to break them")
        G = _break_cycles(G)

    # 计算每个节点的层级（使用拓扑排序）
    levels: Dict[str, int] = {}
    try:
        for node_id in nx.topological_sort(G):
            predecessors = list(G.predecessors(node_id))
            if predecessors:
                levels[node_id] = max(levels.get(p, 0) for p in predecessors) + 1
            else:
                levels[node_id] = 0
    except nx.NetworkXError as e:
        logger.warning(f"[LayoutEngine] Topological sort failed: {e}, using fallback")
        return _apply_fallback_layout(blueprint_data, x_spacing, y_spacing, start_x, start_y)

    # 对于孤立节点（没有边连接），分配到层级 0
    for node in nodes:
        if node["id"] not in levels:
            levels[node["id"]] = 0

    # 按层级分组并计算坐标
    level_nodes: Dict[int, List[str]] = {}
    for node_id, lvl in levels.items():
        level_nodes.setdefault(lvl, []).append(node_id)

    # 在每个层级内排序（保持原始顺序的稳定性）
    node_order = {n["id"]: i for i, n in enumerate(nodes)}
    for lvl in level_nodes:
        level_nodes[lvl].sort(key=lambda nid: node_order.get(nid, 999))

    # 分配坐标
    for node in nodes:
        node_id = node["id"]
        lvl = levels.get(node_id, 0)
        level_list = level_nodes.get(lvl, [])
        idx_in_level = level_list.index(node_id) if node_id in level_list else 0

        # 计算居中偏移（使同层节点垂直居中）
        level_height = (len(level_list) - 1) * y_spacing
        y_offset = -level_height // 2 if len(level_list) > 1 else 0

        node["position"] = {
            "x": start_x + lvl * x_spacing,
            "y": start_y + idx_in_level * y_spacing + y_offset + (level_height // 2),
        }

    logger.info(f"[LayoutEngine] Applied networkx layout to {len(nodes)} nodes across {len(level_nodes)} levels")
    return blueprint_data


def _apply_fallback_layout(
    blueprint_data: Dict[str, Any],
    x_spacing: int,
    y_spacing: int,
    start_x: int,
    start_y: int,
) -> Dict[str, Any]:
    """
    Fallback 布局：不依赖 networkx 的简单分层布局。
    基于边关系手动计算层级。
    """
    nodes = blueprint_data.get("nodes", [])
    edges = blueprint_data.get("edges", [])

    node_ids = {n["id"] for n in nodes}

    # 构建邻接表
    children: Dict[str, List[str]] = {n["id"]: [] for n in nodes}
    parents: Dict[str, List[str]] = {n["id"]: [] for n in nodes}

    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        if source in node_ids and target in node_ids:
            children[source].append(target)
            parents[target].append(source)

    # 找出根节点（没有父节点的节点）
    roots = [nid for nid in node_ids if not parents[nid]]
    if not roots:
        # 如果没有根节点，选择第一个节点作为根
        roots = [nodes[0]["id"]] if nodes else []

    # BFS 计算层级
    levels: Dict[str, int] = {}
    visited: Set[str] = set()
    queue = [(root, 0) for root in roots]

    while queue:
        node_id, lvl = queue.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        levels[node_id] = max(levels.get(node_id, 0), lvl)

        for child in children.get(node_id, []):
            if child not in visited:
                queue.append((child, lvl + 1))

    # 处理未访问的节点（孤立节点）
    for node in nodes:
        if node["id"] not in levels:
            levels[node["id"]] = 0

    # 按层级分组
    level_nodes: Dict[int, List[str]] = {}
    for node_id, lvl in levels.items():
        level_nodes.setdefault(lvl, []).append(node_id)

    # 分配坐标
    node_map = {n["id"]: n for n in nodes}
    for lvl, node_list in level_nodes.items():
        for idx, node_id in enumerate(node_list):
            node = node_map.get(node_id)
            if node:
                node["position"] = {
                    "x": start_x + lvl * x_spacing,
                    "y": start_y + idx * y_spacing,
                }

    logger.info(f"[LayoutEngine] Applied fallback layout to {len(nodes)} nodes")
    return blueprint_data


def _break_cycles(G: "nx.DiGraph") -> "nx.DiGraph":
    """
    打破图中的环以便拓扑排序。
    使用反馈边集（feedback arc set）的简化方法。
    """
    # 复制图
    G_copy = G.copy()

    # 尝试找到并移除环中的边
    try:
        cycles = list(nx.simple_cycles(G_copy))
        edges_to_remove = set()

        for cycle in cycles:
            if len(cycle) >= 2:
                # 移除环中的最后一条边
                edges_to_remove.add((cycle[-1], cycle[0]))

        for edge in edges_to_remove:
            if G_copy.has_edge(*edge):
                G_copy.remove_edge(*edge)
                logger.debug(f"[LayoutEngine] Removed edge {edge} to break cycle")
    except Exception as e:
        logger.warning(f"[LayoutEngine] Failed to break cycles: {e}")

    return G_copy


def calculate_optimal_spacing(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    canvas_width: int = 1200,
    canvas_height: int = 800,
) -> tuple[int, int]:
    """
    根据节点数量和画布大小计算最优间距。

    Returns:
        (x_spacing, y_spacing) 元组
    """
    num_nodes = len(nodes)

    if num_nodes <= 2:
        return 350, 150
    elif num_nodes <= 5:
        return 300, 150
    elif num_nodes <= 10:
        return 280, 120
    else:
        # 大型图，压缩间距
        return 250, 100


def center_graph_on_canvas(
    blueprint_data: Dict[str, Any],
    canvas_width: int = 1200,
    canvas_height: int = 800,
) -> Dict[str, Any]:
    """
    将整个图居中到画布中心。
    """
    nodes = blueprint_data.get("nodes", [])
    if not nodes:
        return blueprint_data

    # 计算当前边界
    min_x = min(n["position"]["x"] for n in nodes)
    max_x = max(n["position"]["x"] for n in nodes)
    min_y = min(n["position"]["y"] for n in nodes)
    max_y = max(n["position"]["y"] for n in nodes)

    graph_width = max_x - min_x
    graph_height = max_y - min_y

    # 计算偏移使其居中
    offset_x = (canvas_width - graph_width) // 2 - min_x
    offset_y = (canvas_height - graph_height) // 2 - min_y

    # 确保不会出现负坐标
    offset_x = max(offset_x, 50 - min_x)
    offset_y = max(offset_y, 50 - min_y)

    for node in nodes:
        node["position"]["x"] += offset_x
        node["position"]["y"] += offset_y

    return blueprint_data
