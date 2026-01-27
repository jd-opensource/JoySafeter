"""
Copilot Tools Module - Exports all tools for graph manipulation.

This module provides LangChain tools for the Copilot Agent to generate
graph actions (CREATE_NODE, CONNECT_NODES, etc.).
"""

# Import registry functions
# Import analysis tool
from app.core.copilot.tools.analysis import analyze_workflow

# Import context management
from app.core.copilot.tools.context import (
    get_current_graph_context,
    get_preloaded_models,
    set_current_graph_context,
    set_preloaded_models,
)

# Import core tools
from app.core.copilot.tools.core import (
    connect_nodes,
    create_node,
    delete_node,
    update_config,
)

# Import layout tool
from app.core.copilot.tools.layout import auto_layout

# Import models tool
from app.core.copilot.tools.models import list_models
from app.core.copilot.tools.registry import (
    NodeIdRegistry,
    get_node_registry,
    reset_node_registry,
)

# Import think tool
from app.core.copilot.tools.think import think

# Import external research tool
from app.core.tools.buildin.research_tools import tavily_search

# List of all Copilot tools
COPILOT_TOOLS = [
    create_node,
    connect_nodes,
    delete_node,
    update_config,
    list_models,
    auto_layout,
    analyze_workflow,
    think,  # Self-reflection tool
    tavily_search,
]


def get_copilot_tools():
    """Get the list of Copilot tools for agent creation."""
    return COPILOT_TOOLS.copy()


__all__ = [
    # Registry
    "NodeIdRegistry",
    "get_node_registry",
    "reset_node_registry",
    # Context
    "set_current_graph_context",
    "get_current_graph_context",
    "set_preloaded_models",
    "get_preloaded_models",
    # Core tools
    "create_node",
    "connect_nodes",
    "delete_node",
    "update_config",
    # Layout
    "auto_layout",
    # Analysis
    "analyze_workflow",
    # Models
    "list_models",
    # Think
    "think",
    # Research
    "tavily_search",
    # Main export
    "get_copilot_tools",
    "COPILOT_TOOLS",
]
