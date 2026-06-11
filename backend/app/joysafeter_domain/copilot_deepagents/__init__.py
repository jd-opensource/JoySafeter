"""
DeepAgents Copilot - Generate arbitrary Agent workflow graphs using the DeepAgents pattern.

Architecture:
- Manager Agent: orchestrate sub-agents + call create_node/connect_nodes
- SubAgents: requirements-analyst, workflow-architect, validator

Features:
- Sub-agent collaboration: analyze -> design -> validate -> generate
- Artifact persistence: analysis.json, blueprint.json, validation.json
- Standard output: GraphAction (fully compatible with existing Copilot)
"""

from .manager import DEEPAGENTS_AVAILABLE
from .runner import run_copilot_manager, stream_copilot_manager

__all__ = [
    "stream_copilot_manager",
    "run_copilot_manager",
    "DEEPAGENTS_AVAILABLE",
]
