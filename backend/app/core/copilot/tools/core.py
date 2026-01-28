"""
Core Copilot Tools - Node CRUD operations.

Provides tools for creating, connecting, deleting, and updating nodes in the graph.
"""

import json
import uuid
from typing import Any, Dict, List, Optional

from langchain.tools import tool
from pydantic import BaseModel, Field

from app.core.copilot.tools.registry import get_node_registry

# ==================== Tool Input Schemas ====================


class CreateNodeInput(BaseModel):
    """Input schema for create_node tool."""

    node_type: str = Field(
        description="Node type. Must be one of: 'agent', 'condition', 'condition_agent', 'direct_reply', 'human_input', 'http', 'custom_function', 'execute_flow', 'iteration'"
    )
    label: str = Field(description="Human-readable label for the node (e.g., 'Support Agent', 'Sentiment Check')")
    position_x: float = Field(
        description="X position coordinate on canvas. Use nextAvailablePosition.x from context_data for sequential nodes."
    )
    position_y: float = Field(
        description="Y position coordinate on canvas. Use nextAvailablePosition.y from context_data for sequential nodes."
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="REQUIRED for agent nodes. Detailed system prompt defining the agent's behavior, role, and task. Be specific!",
    )
    model: Optional[str] = Field(
        default=None,
        description="Optional for agent nodes. Model name (e.g., 'gpt-4o', 'gpt-4o-mini'). Leave empty to use default.",
    )
    use_deep_agents: Optional[bool] = Field(
        default=False,
        description="For agent nodes only. Set to True to enable DeepAgents mode for complex multi-step tasks.",
    )
    description: Optional[str] = Field(
        default=None,
        description="REQUIRED for DeepAgents subagents. Clear, action-oriented description of what this subagent does (e.g., 'Conducts web research and synthesizes findings'). Required when use_deep_agents=True or parent has useDeepAgents=true.",
    )
    tools_builtin: Optional[List[str]] = Field(
        default=None,
        description="For agent nodes only. List of builtin tool names (e.g., ['web_search', 'code_interpreter']).",
    )
    tools_mcp: Optional[List[str]] = Field(
        default=None,
        description="For agent nodes only. List of MCP tool identifiers (e.g., ['server_name::tool_name']).",
    )
    reasoning: str = Field(description="Explanation for why this node is being created")


class ConnectNodesInput(BaseModel):
    """Input schema for connect_nodes tool."""

    source: str = Field(description="Source node ID")
    target: str = Field(description="Target node ID")
    reasoning: str = Field(description="Explanation for why these nodes are being connected")


class DeleteNodeInput(BaseModel):
    """Input schema for delete_node tool."""

    node_id: str = Field(description="ID of the node to delete")
    reasoning: str = Field(description="Explanation for why this node is being deleted")


class UpdateConfigInput(BaseModel):
    """Input schema for update_config tool."""

    node_id: str = Field(description="ID of the node to update")
    system_prompt: Optional[str] = Field(default=None, description="New system prompt")
    model: Optional[str] = Field(default=None, description="New model name")
    use_deep_agents: Optional[bool] = Field(default=None, description="Enable/disable DeepAgents mode")
    description: Optional[str] = Field(default=None, description="New description for DeepAgents")
    reasoning: str = Field(description="Explanation for this configuration update")


# ==================== Tool Definitions ====================


@tool(
    args_schema=CreateNodeInput,
    description="Create a new node in the graph workflow. Returns CREATE_NODE action with generated ID. See system prompt for DeepAgents rules and position calculation.",
)
def create_node(
    node_type: str,
    label: str,
    position_x: float,
    position_y: float,
    reasoning: str,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    use_deep_agents: Optional[bool] = False,
    description: Optional[str] = None,
    tools_builtin: Optional[List[str]] = None,
    tools_mcp: Optional[List[str]] = None,
    expression: Optional[str] = None,
    instruction: Optional[str] = None,
    options: Optional[List[str]] = None,
    template: Optional[str] = None,
    prompt: Optional[str] = None,
) -> str:
    """
    Create a new node in the graph workflow.

    Args:
        node_type: Node type ('agent', 'condition', etc.)
        label: Human-readable label
        position_x: X coordinate (use pre-calculated positions from system prompt context)
        position_y: Y coordinate (use pre-calculated positions from system prompt context)
        reasoning: Why this node is being created
        system_prompt: Required for agent nodes - defines agent behavior
        model: Optional model name for agent nodes
        use_deep_agents: Set True for DeepAgents Manager nodes only
        description: Required for DeepAgents nodes - action-oriented description
        tools_builtin: Optional builtin tools list (not for DeepAgents Manager)
        tools_mcp: Optional MCP tools list (not for DeepAgents Manager)
        expression: For condition nodes
        instruction: For condition_agent nodes
        options: For condition_agent nodes
        template: For direct_reply nodes
        prompt: For human_input nodes

    Returns:
        JSON string with CREATE_NODE action containing generated node ID.
        Node can be referenced by ID or label (@label:LabelName).

    Note:
    - Position values are pre-calculated in system prompt for DeepAgents workflows
    - For DeepAgents: Use exact positions from <position-calculation> section
    - For single nodes: Use nextAvailablePosition from context
    - See system prompt for DeepAgents architecture rules and systemPrompt quality standards
    """
    try:
        # Generate unique node ID
        node_id = f"{node_type}_{uuid.uuid4().hex[:8]}"

        # Register in the node registry for semantic reference
        registry = get_node_registry()
        registry.register(node_id, label, node_type)

        # Build config based on node type
        config: Dict[str, Any] = {}

        if node_type == "agent":
            if system_prompt:
                config["systemPrompt"] = system_prompt
            if model:
                config["model"] = model
            if use_deep_agents:
                config["useDeepAgents"] = True
            if description:
                config["description"] = description
            if tools_builtin or tools_mcp:
                config["tools"] = {
                    "builtin": tools_builtin or [],
                    "mcp": tools_mcp or [],
                }
        elif node_type == "condition":
            if expression:
                config["expression"] = expression
        elif node_type == "condition_agent":
            if instruction:
                config["instruction"] = instruction
            if options:
                config["options"] = options
            else:
                config["options"] = ["Option A", "Option B"]
        elif node_type == "direct_reply":
            if template:
                config["template"] = template
        elif node_type == "human_input":
            if prompt:
                config["prompt"] = prompt

        action = {
            "type": "CREATE_NODE",
            "payload": {
                "id": node_id,
                "type": node_type,
                "label": label,
                "position": {"x": position_x, "y": position_y},
                "config": config,
            },
            "reasoning": reasoning,
            "_label_ref": f"@{label}",  # Can also reference by label
        }
        # Return as JSON string for LangChain compatibility
        return json.dumps(action, ensure_ascii=False)
    except Exception as e:
        from loguru import logger

        logger.error(f"create_node failed: {e}")
        return json.dumps({"type": "ERROR", "error": str(e), "message": "Failed to create node"}, ensure_ascii=False)


@tool(
    args_schema=ConnectNodesInput,
    description="Connect two nodes with an edge. Nodes can be referenced by ID or label (@label:Name). See system prompt for DeepAgents topology rules.",
)
def connect_nodes(
    source: str,
    target: str,
    reasoning: str,
) -> str:
    """
    Connect two nodes with an edge.

    Args:
        source: Source node ID or label reference (@label:Name)
        target: Target node ID or label reference (@label:Name)
        reasoning: Why these nodes are connected

    Returns:
        JSON string with CONNECT_NODES action.

    Note: See system prompt for DeepAgents star topology requirements.
    """
    try:
        # Resolve semantic references to actual IDs
        registry = get_node_registry()
        resolved_source = registry.resolve(source)
        resolved_target = registry.resolve(target)

        action = {
            "type": "CONNECT_NODES",
            "payload": {
                "source": resolved_source,
                "target": resolved_target,
            },
            "reasoning": reasoning,
        }

        # Include original references for debugging if they were resolved
        if resolved_source != source or resolved_target != target:
            action["_resolved"] = {
                "source_ref": source,
                "target_ref": target,
                "source_id": resolved_source,
                "target_id": resolved_target,
            }

        return json.dumps(action, ensure_ascii=False)
    except Exception as e:
        from loguru import logger

        logger.error(f"connect_nodes failed: {e}")
        return json.dumps({"type": "ERROR", "error": str(e), "message": "Failed to connect nodes"}, ensure_ascii=False)


@tool(
    args_schema=DeleteNodeInput,
    description="Delete a node from the graph. Node can be referenced by ID or label. Removes node and all connected edges.",
)
def delete_node(
    node_id: str,
    reasoning: str,
) -> str:
    """
    Delete a node from the graph.

    Args:
        node_id: Node ID or label reference (@label:Name)
        reasoning: Why this node is being deleted

    Returns:
        JSON string with DELETE_NODE action.
    """
    try:
        # Resolve semantic reference to actual ID
        registry = get_node_registry()
        resolved_id = registry.resolve(node_id)

        action = {
            "type": "DELETE_NODE",
            "payload": {
                "id": resolved_id,
            },
            "reasoning": reasoning,
        }
        return json.dumps(action, ensure_ascii=False)
    except Exception as e:
        from loguru import logger

        logger.error(f"delete_node failed: {e}")
        return json.dumps({"type": "ERROR", "error": str(e), "message": "Failed to delete node"}, ensure_ascii=False)


@tool(
    args_schema=UpdateConfigInput,
    description="Update node configuration. Only include parameters that need to change. Node can be referenced by ID or label.",
)
def update_config(
    node_id: str,
    reasoning: str,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    use_deep_agents: Optional[bool] = None,
    description: Optional[str] = None,
    expression: Optional[str] = None,
    instruction: Optional[str] = None,
    options: Optional[List[str]] = None,
    template: Optional[str] = None,
) -> str:
    """
    Update node configuration.

    Args:
        node_id: Node ID or label reference (@label:Name)
        reasoning: Why this update is needed
        system_prompt: New system prompt (agent nodes)
        model: New model name (agent nodes)
        use_deep_agents: Enable/disable DeepAgents mode
        description: New description (DeepAgents nodes)
        expression: For condition nodes
        instruction: For condition_agent nodes
        options: For condition_agent nodes
        template: For direct_reply nodes

    Returns:
        JSON string with UPDATE_CONFIG action.
    """
    try:
        # Resolve semantic reference to actual ID
        registry = get_node_registry()
        resolved_id = registry.resolve(node_id)

        config: Dict[str, Any] = {}

        if system_prompt is not None:
            config["systemPrompt"] = system_prompt
        if model is not None:
            config["model"] = model
        if use_deep_agents is not None:
            config["useDeepAgents"] = use_deep_agents
        if description is not None:
            config["description"] = description
        if expression is not None:
            config["expression"] = expression
        if instruction is not None:
            config["instruction"] = instruction
        if options is not None:
            config["options"] = options
        if template is not None:
            config["template"] = template

        action = {
            "type": "UPDATE_CONFIG",
            "payload": {
                "id": resolved_id,
                "config": config,
            },
            "reasoning": reasoning,
        }
        return json.dumps(action, ensure_ascii=False)
    except Exception as e:
        from loguru import logger

        logger.error(f"update_config failed: {e}")
        return json.dumps({"type": "ERROR", "error": str(e), "message": "Failed to update config"}, ensure_ascii=False)
