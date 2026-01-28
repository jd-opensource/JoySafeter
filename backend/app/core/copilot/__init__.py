"""
Copilot Module - AI-powered graph building assistant.

This module provides the core functionality for the Copilot feature,
which helps users build agent workflows through natural language instructions.

Submodules:
- action_types: Pydantic models for requests/responses
- graph_analyzer: Graph topology analysis utilities
- prompt_builder: System prompt construction
- response_parser: Response parsing utilities
- tools: LangChain tools for graph manipulation
- agent: Copilot agent creation
"""

from app.core.copilot.action_types import (
    ConnectNodesPayload,
    CopilotHistoryResponse,
    CopilotMessage,
    CopilotRequest,
    CopilotResponse,
    CopilotThoughtStep,
    CopilotToolCall,
    CreateNodePayload,
    DeleteNodePayload,
    GraphAction,
    GraphActionType,
    UpdateConfigPayload,
)
from app.core.copilot.action_validator import (
    ActionValidationResult,
    extract_existing_node_ids,
    filter_invalid_actions,
    validate_actions,
)
from app.core.copilot.agent import get_copilot_agent
from app.core.copilot.graph_analyzer import (
    analyze_graph_topology,
    generate_topology_description,
    normalize_node,
)
from app.core.copilot.message_builder import build_langchain_messages
from app.core.copilot.prompt_builder import (
    build_copilot_system_prompt,
    build_llm_messages,
)
from app.core.copilot.response_parser import (
    expand_action_payload,
    extract_actions_from_agent_result,
    parse_copilot_response,
    parse_thought_to_steps,
    try_extract_thought_field,
)
from app.core.copilot.tool_output_parser import parse_tool_output
from app.core.copilot.tools import get_copilot_tools, get_node_registry, reset_node_registry

__all__ = [
    # Action types
    "GraphActionType",
    "GraphAction",
    "CopilotRequest",
    "CopilotResponse",
    "CreateNodePayload",
    "ConnectNodesPayload",
    "DeleteNodePayload",
    "UpdateConfigPayload",
    # Message persistence types
    "CopilotMessage",
    "CopilotThoughtStep",
    "CopilotToolCall",
    "CopilotHistoryResponse",
    # Agent
    "get_copilot_agent",
    # Prompt builder
    "build_copilot_system_prompt",
    "build_llm_messages",
    # Graph analyzer
    "normalize_node",
    "analyze_graph_topology",
    "generate_topology_description",
    # Response parser
    "try_extract_thought_field",
    "parse_thought_to_steps",
    "parse_copilot_response",
    "extract_actions_from_agent_result",
    "expand_action_payload",
    # Tool output parser
    "parse_tool_output",
    # Message builder
    "build_langchain_messages",
    # Tools
    "get_copilot_tools",
    "reset_node_registry",
    "get_node_registry",
    # Validator
    "validate_actions",
    "extract_existing_node_ids",
    "filter_invalid_actions",
    "ActionValidationResult",
]
