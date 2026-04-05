"""
DeepAgents Copilot - Generate arbitrary Agent workflow graphs using the DeepAgents pattern.

Architecture:
- Manager Agent: orchestrate sub-agents + call create_node/connect_nodes
- SubAgents: requirements-analyst, workflow-architect, validator

Features:
- Sub-agent collaboration: analyze -> design -> validate -> generate
- Artifact persistence: analysis.json, blueprint.json, validation.json
- Standard output: GraphAction (fully compatible with existing Copilot)

Usage:
    from app.core.copilot_deepagents import stream_deepagents_actions

    async for event in stream_deepagents_actions(
        prompt="Create an APK security analysis team",
        graph_context={"nodes": [], "edges": []},
        graph_id="my_graph",
    ):
        print(event)
"""

from .manager import DEEPAGENTS_AVAILABLE
from .runner import run_copilot_manager
from .streaming import stream_deepagents_actions

__all__ = [
    "stream_deepagents_actions",
    "run_copilot_manager",
    "DEEPAGENTS_AVAILABLE",
]
