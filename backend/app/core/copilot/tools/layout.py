"""
Layout Tools - Automatic node positioning.

Provides auto_layout tool for arranging nodes in various layouts.
"""

import json
from typing import Dict, List

from langchain.tools import tool
from pydantic import BaseModel, Field

from app.core.copilot.tools.context import get_current_graph_context


class AutoLayoutInput(BaseModel):
    """Input schema for auto_layout tool."""

    layout_type: str = Field(
        default="horizontal",
        description="Layout type: 'horizontal' (left-to-right), 'vertical' (top-to-bottom), 'tree' (hierarchical), 'grid' (grid arrangement)",
    )
    node_spacing_x: float = Field(default=300, description="Horizontal spacing between nodes")
    node_spacing_y: float = Field(default=150, description="Vertical spacing between nodes")
    start_x: float = Field(default=100, description="Starting X position")
    start_y: float = Field(default=100, description="Starting Y position")
    reasoning: str = Field(description="Explanation for why auto layout is needed")


@tool(
    args_schema=AutoLayoutInput,
    description="Automatically rearrange nodes for better visualization. Layout types: horizontal, vertical, tree, grid.",
)
def auto_layout(
    reasoning: str,
    layout_type: str = "horizontal",
    node_spacing_x: float = 300,
    node_spacing_y: float = 150,
    start_x: float = 100,
    start_y: float = 100,
) -> str:
    """
    Automatically rearrange nodes for better visualization.

    Args:
        reasoning: Why auto layout is needed
        layout_type: 'horizontal' (default), 'vertical', 'tree', 'grid'
        node_spacing_x: Horizontal spacing (default: 300)
        node_spacing_y: Vertical spacing (default: 150)
        start_x: Starting X position (default: 100)
        start_y: Starting Y position (default: 100)

    Returns:
        JSON with UPDATE_POSITION actions for all nodes.
    """
    graph_context = get_current_graph_context()

    nodes = graph_context.get("nodes", [])
    edges = graph_context.get("edges", [])

    if not nodes:
        return json.dumps(
            {
                "error": "No nodes in the current graph to layout",
                "suggestion": "Create some nodes first before applying auto layout",
            },
            ensure_ascii=False,
        )

    actions = []

    # Build adjacency list for topology analysis
    outgoing: Dict[str, List[str]] = {n.get("id"): [] for n in nodes}
    incoming: Dict[str, List[str]] = {n.get("id"): [] for n in nodes}

    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src in outgoing and tgt in incoming:
            outgoing[src].append(tgt)
            incoming[tgt].append(src)

    # Find root nodes (no incoming edges)
    root_nodes = [n for n in nodes if not incoming.get(n.get("id"), [])]

    if layout_type == "horizontal":
        # BFS from root nodes, assign columns
        visited = set()
        columns: Dict[str, int] = {}
        queue = [(n.get("id"), 0) for n in root_nodes]

        while queue:
            node_id, col = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)
            columns[node_id] = col
            for child in outgoing.get(node_id, []):
                if child not in visited:
                    queue.append((child, col + 1))

        # Assign positions by column
        col_counts: Dict[int, int] = {}
        for node in nodes:
            node_id = node.get("id")
            col = columns.get(node_id, 0)
            row = col_counts.get(col, 0)
            col_counts[col] = row + 1

            new_x = start_x + col * node_spacing_x
            new_y = start_y + row * node_spacing_y

            actions.append(
                {
                    "type": "UPDATE_POSITION",
                    "payload": {"id": node_id, "position": {"x": new_x, "y": new_y}},
                    "reasoning": f"Auto-layout: placing node in column {col}, row {row}",
                }
            )

    elif layout_type == "vertical":
        # Similar to horizontal but swap x and y
        visited = set()
        rows: Dict[str, int] = {}
        queue = [(n.get("id"), 0) for n in root_nodes]

        while queue:
            node_id, row = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)
            rows[node_id] = row
            for child in outgoing.get(node_id, []):
                if child not in visited:
                    queue.append((child, row + 1))

        row_counts: Dict[int, int] = {}
        for node in nodes:
            node_id = node.get("id")
            row = rows.get(node_id, 0)
            col = row_counts.get(row, 0)
            row_counts[row] = col + 1

            new_x = start_x + col * node_spacing_x
            new_y = start_y + row * node_spacing_y

            actions.append(
                {
                    "type": "UPDATE_POSITION",
                    "payload": {"id": node_id, "position": {"x": new_x, "y": new_y}},
                    "reasoning": f"Auto-layout (vertical): placing node in row {row}, column {col}",
                }
            )

    elif layout_type == "tree":
        # Tree layout with root at top
        visited = set()
        levels: Dict[str, int] = {}
        level_nodes: Dict[int, List[str]] = {}
        queue = [(n.get("id"), 0) for n in root_nodes]

        while queue:
            node_id, level = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)
            levels[node_id] = level
            if level not in level_nodes:
                level_nodes[level] = []
            level_nodes[level].append(node_id)
            for child in outgoing.get(node_id, []):
                if child not in visited:
                    queue.append((child, level + 1))

        # Position nodes centered in each level
        for level, node_list in level_nodes.items():
            count = len(node_list)
            total_width = (count - 1) * node_spacing_x
            start_offset = -total_width / 2

            for i, node_id in enumerate(node_list):
                new_x = start_x + 400 + start_offset + i * node_spacing_x  # Center around 400
                new_y = start_y + level * node_spacing_y

                actions.append(
                    {
                        "type": "UPDATE_POSITION",
                        "payload": {"id": node_id, "position": {"x": new_x, "y": new_y}},
                        "reasoning": f"Auto-layout (tree): level {level}, position {i + 1}/{count}",
                    }
                )

    elif layout_type == "grid":
        # Simple grid arrangement
        cols = max(3, int(len(nodes) ** 0.5))
        for i, node in enumerate(nodes):
            row = i // cols
            col = i % cols
            new_x = start_x + col * node_spacing_x
            new_y = start_y + row * node_spacing_y

            actions.append(
                {
                    "type": "UPDATE_POSITION",
                    "payload": {"id": node.get("id"), "position": {"x": new_x, "y": new_y}},
                    "reasoning": f"Auto-layout (grid): row {row}, col {col}",
                }
            )

    return json.dumps(
        {
            "layout_type": layout_type,
            "nodes_repositioned": len(actions),
            "actions": actions,
            "reasoning": reasoning,
        },
        ensure_ascii=False,
        indent=2,
    )
