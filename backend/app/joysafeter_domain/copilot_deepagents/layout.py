"""
Auto Layout Engine for DeepAgents Copilot.

Use networkx to implement a hierarchical layout algorithm, solving the problem
of LLMs being unable to generate tidy ReactFlow coordinates.
Uses topological sort + layered layout to ensure:
- Manager node on the left
- Sub-agent nodes vertically aligned on the right
- Automatic overlap avoidance
- Clean edge connections
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
    Compute layered layout using topological sort, overriding LLM-generated coordinates.

    Args:
        blueprint_data: blueprint dict containing nodes and edges
        x_spacing: horizontal spacing between nodes
        y_spacing: vertical spacing between nodes
        start_x: starting X coordinate
        start_y: starting Y coordinate

    Returns:
        blueprint_data with updated positions.
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
    """Implement layered layout using networkx."""
    nodes = blueprint_data.get("nodes", [])
    edges = blueprint_data.get("edges", [])

    # build directed graph
    G = nx.DiGraph()
    node_map = {n["id"]: n for n in nodes}

    for node in nodes:
        G.add_node(node["id"])
    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        if source in node_map and target in node_map:
            G.add_edge(source, target)

    # handle possible cycles (break them for topological sort)
    if not nx.is_directed_acyclic_graph(G):
        logger.warning("[LayoutEngine] Graph has cycles, attempting to break them")
        G = _break_cycles(G)

    # compute each node's layer (via topological sort)
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

    # assign orphan nodes (no edges) to layer 0
    for node in nodes:
        if node["id"] not in levels:
            levels[node["id"]] = 0

    # group by layer and compute coordinates
    level_nodes: Dict[int, List[str]] = {}
    for node_id, lvl in levels.items():
        level_nodes.setdefault(lvl, []).append(node_id)

    # sort within each layer (preserve original order stability)
    node_order = {n["id"]: i for i, n in enumerate(nodes)}
    for lvl in level_nodes:
        level_nodes[lvl].sort(key=lambda nid: node_order.get(nid, 999))

    # assign coordinates
    for node in nodes:
        node_id = node["id"]
        lvl = levels.get(node_id, 0)
        level_list = level_nodes.get(lvl, [])
        idx_in_level = level_list.index(node_id) if node_id in level_list else 0

        # compute centering offset (vertically center nodes in the same layer)
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
    Fallback layout: simple layered layout without networkx dependency.
    Manually compute layers based on edge relationships.
    """
    nodes = blueprint_data.get("nodes", [])
    edges = blueprint_data.get("edges", [])

    node_ids = {n["id"] for n in nodes}

    # build adjacency lists
    children: Dict[str, List[str]] = {n["id"]: [] for n in nodes}
    parents: Dict[str, List[str]] = {n["id"]: [] for n in nodes}

    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        if source in node_ids and target in node_ids:
            children[source].append(target)
            parents[target].append(source)

    # find root nodes (no parents)
    roots = [nid for nid in node_ids if not parents[nid]]
    if not roots:
        # if no root nodes, pick the first node as root
        roots = [nodes[0]["id"]] if nodes else []

    # BFS to compute layers
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

    # handle unvisited nodes (orphan nodes)
    for node in nodes:
        if node["id"] not in levels:
            levels[node["id"]] = 0

    # group by layer
    level_nodes: Dict[int, List[str]] = {}
    for node_id, lvl in levels.items():
        level_nodes.setdefault(lvl, []).append(node_id)

    # assign coordinates
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
    Break cycles in the graph to enable topological sort.
    Use a simplified feedback arc set approach.
    """
    # copy the graph
    G_copy = G.copy()

    # find and remove edges in cycles
    try:
        cycles = list(nx.simple_cycles(G_copy))
        edges_to_remove = set()

        for cycle in cycles:
            if len(cycle) >= 2:
                # remove the last edge in the cycle
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
    Calculate optimal spacing based on node count and canvas size.

    Returns:
        (x_spacing, y_spacing) tuple.
    """
    num_nodes = len(nodes)

    if num_nodes <= 2:
        return 350, 150
    elif num_nodes <= 5:
        return 300, 150
    elif num_nodes <= 10:
        return 280, 120
    else:
        # large graph: compress spacing
        return 250, 100


def center_graph_on_canvas(
    blueprint_data: Dict[str, Any],
    canvas_width: int = 1200,
    canvas_height: int = 800,
) -> Dict[str, Any]:
    """
    Center the entire graph on the canvas.
    """
    nodes = blueprint_data.get("nodes", [])
    if not nodes:
        return blueprint_data

    # compute current bounds
    min_x = min(n["position"]["x"] for n in nodes)
    max_x = max(n["position"]["x"] for n in nodes)
    min_y = min(n["position"]["y"] for n in nodes)
    max_y = max(n["position"]["y"] for n in nodes)

    graph_width = max_x - min_x
    graph_height = max_y - min_y

    # compute offset to center
    offset_x = (canvas_width - graph_width) // 2 - min_x
    offset_y = (canvas_height - graph_height) // 2 - min_y

    # ensure no negative coordinates
    offset_x = max(offset_x, 50 - min_x)
    offset_y = max(offset_y, 50 - min_y)

    for node in nodes:
        node["position"]["x"] += offset_x
        node["position"]["y"] += offset_y

    return blueprint_data
