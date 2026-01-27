"""
Copilot Tools - LangChain tools for graph manipulation.

This file is maintained for backward compatibility.
All tools have been refactored into the tools/ submodule.

New code should import from app.core.copilot.tools directly.
"""

# Re-export everything from the tools submodule for backward compatibility
from app.core.copilot.tools import (
    COPILOT_TOOLS,
    # Registry
    NodeIdRegistry,
    # Analysis
    analyze_workflow,
    # Layout
    auto_layout,
    connect_nodes,
    # Core tools
    create_node,
    delete_node,
    # Main export
    get_copilot_tools,
    get_current_graph_context,
    get_node_registry,
    get_preloaded_models,
    # Models
    list_models,
    reset_node_registry,
    # Context
    set_current_graph_context,
    set_preloaded_models,
    # Research
    tavily_search,
    # Think
    think,
    update_config,
)

__all__ = [
    "NodeIdRegistry",
    "get_node_registry",
    "reset_node_registry",
    "set_current_graph_context",
    "get_current_graph_context",
    "set_preloaded_models",
    "get_preloaded_models",
    "create_node",
    "connect_nodes",
    "delete_node",
    "update_config",
    "auto_layout",
    "analyze_workflow",
    "list_models",
    "think",
    "tavily_search",
    "get_copilot_tools",
    "COPILOT_TOOLS",
]
