"""DeepAgents graph building components."""

from __future__ import annotations

from typing import Optional


def format_node_ctx(node_label: Optional[str] = None, graph_name: Optional[str] = None) -> str:
    """Build a human-readable context string for logs and error messages."""
    ctx = f'node "{node_label or "unknown"}"'
    if graph_name:
        ctx += f' in agent "{graph_name}"'
    return ctx
