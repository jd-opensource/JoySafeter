"""
Prompt Builder - System prompt construction for Copilot.

Builds the comprehensive system prompt that guides the AI in generating
graph actions based on user requests and current graph context.

OPTIMIZED VERSION: Modular prompt construction with direct value injection.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.copilot.graph_analyzer import (
    analyze_graph_topology,
    calculate_next_position,
    calculate_positions_for_deepagents,
    generate_topology_description,
    normalize_node,
)


def build_llm_messages(
    system_prompt: str,
    user_prompt: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """
    Build messages list for LLM API calls with conversation history.

    Args:
        system_prompt: System prompt content
        user_prompt: Current user prompt
        conversation_history: Optional list of previous messages in format
                             [{"role": "user"|"assistant", "content": "..."}, ...]
                             Can also include "actions" field for context

    Returns:
        List of message dictionaries ready for OpenAI API
    """
    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history if provided
    if conversation_history:
        for msg in conversation_history:
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                role = msg["role"]
                content = msg.get("content", "")
                actions_raw: Any = msg.get("actions", [])
                actions: List[Any] = actions_raw if isinstance(actions_raw, list) else []

                # Only include user and assistant messages, skip invalid roles
                if role in ("user", "assistant") and content:
                    # For assistant messages, append action summary if actions exist
                    if role == "assistant" and actions:
                        action_summary = _format_actions_summary(actions)
                        content = f"{content}\n\n[Previous Actions Created: {action_summary}]"
                    messages.append({"role": role, "content": content})

    # Add current user prompt
    messages.append({"role": "user", "content": user_prompt})

    return messages


def _format_actions_summary(actions: List[Dict[str, Any]]) -> str:
    """Format actions into a brief summary for conversation context."""
    if not actions:
        return "None"

    summaries = []
    for action in actions:
        action_type = action.get("type", "")
        payload = action.get("payload", {})

        if action_type == "CREATE_NODE":
            node_id = payload.get("id", "unknown")
            label = payload.get("label", "")
            node_type = payload.get("type", "")
            summaries.append(f"Created {node_type} '{label}' (id: {node_id})")
        elif action_type == "CONNECT_NODES":
            src = payload.get("source", "")
            tgt = payload.get("target", "")
            summaries.append(f"Connected {src} → {tgt}")
        elif action_type == "DELETE_NODE":
            summaries.append(f"Deleted node {payload.get('id', '')}")
        elif action_type == "UPDATE_CONFIG":
            summaries.append(f"Updated config for {payload.get('id', '')}")

    return "; ".join(summaries[:5])  # Limit to 5 actions for brevity


def build_copilot_system_prompt(
    graph_context: Dict[str, Any],
    available_models: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Build the comprehensive system prompt for Copilot.

    This prompt guides the AI in:
    - Understanding current graph structure
    - Making decisions about node creation/modification
    - Following best practices for workflow design
    - Selecting appropriate models for agent nodes

    Args:
        graph_context: Current graph state with nodes and edges
        available_models: Optional list of available models for model selection

    Returns:
        Complete system prompt string
    """
    # Extract nodes and edges from graph context
    nodes = graph_context.get("nodes", [])
    edges = graph_context.get("edges", [])

    # Normalize all nodes to extract data structure
    normalized_nodes = [normalize_node(node) for node in nodes]

    # Analyze graph topology
    topology = analyze_graph_topology(normalized_nodes, edges)

    # Build enhanced context data for each node (simplified)
    existing_nodes = _build_simplified_node_data(normalized_nodes, topology)

    # Pre-calculate next available position - DIRECT VALUES
    next_pos = calculate_next_position(normalized_nodes)

    # Build node map for topology description
    node_map = {node["id"]: node for node in normalized_nodes}

    # Generate structured topology description
    topology_description = generate_topology_description(normalized_nodes, topology, node_map)

    # Build available models summary for context
    models_summary = _build_models_summary(available_models or [])

    # Get current time for temporal context in search operations
    current_time = datetime.utcnow().isoformat()

    # Detect if graph has DeepAgents (to conditionally load those instructions)
    has_deep_agents = any(node.get("config", {}).get("useDeepAgents", False) for node in normalized_nodes)

    # Build optimized prompt with direct values
    return _get_optimized_system_prompt(
        topology_description=topology_description,
        existing_nodes=existing_nodes,
        edges=edges,
        topology=topology,
        next_position_x=next_pos["x"],
        next_position_y=next_pos["y"],
        models_summary=models_summary,
        current_time=current_time,
        has_deep_agents=has_deep_agents,
    )


def _build_simplified_node_data(normalized_nodes: List[Dict], topology: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build simplified context data for each node.
    Only includes essential information for decision making.
    """
    existing_nodes = []

    for node in normalized_nodes:
        node_id = node["id"]
        config = node.get("config", {})

        # Check if DeepAgents is enabled
        is_deep_agent = config.get("useDeepAgents", False) is True

        # Get DeepAgents role from topology analysis
        deep_agent_info = topology["deepAgentsHierarchy"].get(node_id, {})
        role = deep_agent_info.get("role") if is_deep_agent else None

        # Simplified node data - only essential fields
        node_data = {
            "id": node_id,
            "type": node.get("type", "agent"),
            "label": node.get("label", ""),
        }

        # Only add optional fields if they exist and are meaningful
        if is_deep_agent:
            node_data["isDeepAgent"] = True
            node_data["role"] = role

        if config.get("description"):
            node_data["description"] = config["description"]

        existing_nodes.append(node_data)

    return existing_nodes


def _build_models_summary(models: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build a summary of available models for the context.

    Args:
        models: List of model info dicts from ModelService

    Returns:
        Summarized model info for prompt context
    """
    if not models:
        return {"count": 0, "models": [], "defaultModel": None}

    # Filter to only available models
    available = [m for m in models if m.get("is_available", False)]

    # Find default model
    default_model = next((m.get("name") for m in available if m.get("is_default")), None)

    # Build simplified model list
    model_list = [
        {
            "name": m.get("name"),
            "displayName": m.get("display_name"),
            "provider": m.get("provider_name"),
            "isDefault": m.get("is_default", False),
        }
        for m in available
    ]

    return {
        "count": len(model_list),
        "models": model_list,
        "defaultModel": default_model,
    }


def _get_optimized_system_prompt(
    topology_description: str,
    existing_nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    topology: Dict[str, Any],
    next_position_x: float,
    next_position_y: float,
    models_summary: Dict[str, Any],
    current_time: str,
    has_deep_agents: bool,
) -> str:
    """
    Build an optimized system prompt with direct value injection.

    Key optimizations:
    1. Direct position values (no JSON parsing needed)
    2. Modular sections based on context
    3. Condensed instructions
    4. Semantic ID support for node references
    """
    # Build node list string (simplified)
    nodes_str = json.dumps(existing_nodes, indent=2, ensure_ascii=False) if existing_nodes else "[]"
    edges_str = (
        json.dumps([{"source": e.get("source"), "target": e.get("target")} for e in edges], indent=2) if edges else "[]"
    )

    # Build model list (simplified)
    model_names = [m["name"] for m in models_summary.get("models", [])][:5]
    default_model = models_summary.get("defaultModel", "system default")

    # Base prompt (always included) - Optimized with XML structure
    prompt = f"""You are an AI Agent Builder Copilot that creates professional workflow graphs.

<system-reminder>
Decision Rule:
- DeepAgents (DEFAULT): Multi-step tasks, research, analysis, complex workflows (2+ steps)
- Single Agent: ONLY for trivial single-step tasks (translation, formatting, simple classification)
</system-reminder>

<tools>
- create_node: Create nodes, returns ID. Parameters: use_deep_agents (True for Manager, False for SubAgents), description (REQUIRED for DeepAgents). See <deepagents-architecture> for rules.
- connect_nodes: Connect nodes by ID or label (@label:Name). For DeepAgents: Star topology (Manager → ALL SubAgents).
- delete_node / update_config: Modify existing nodes.
- think: Self-reflection at planning (before creating) and validation (after completion) stages (use in <step2-deepagents> workflow).
- tavily_search: Research unfamiliar domains before creating agents.
- auto_layout: Rearrange nodes (horizontal/vertical/tree/grid layouts).
- analyze_workflow: Analyze graph structure and suggest optimizations.
- list_models: Query available LLM models for agent configuration.
</tools>

<context>
Next Position: x={next_position_x}, y={next_position_y}
Default Model: {default_model}
Available Models: {", ".join(model_names[:3]) if model_names else "system default"}
Note: For DeepAgents workflows, use pre-calculated positions from <position-calculation> section below.
</context>

<current-graph>
{topology_description}
Nodes: {nodes_str}
Edges: {edges_str}
</current-graph>
"""

    # DeepAgents guidance - Optimized and structured
    prompt += """
<deepagents-architecture>
Structure: 1 Manager (use_deep_agents=True) + 3-8 SubAgents (use_deep_agents=False)
Topology: Star pattern - Manager connects to ALL SubAgents directly (NOT chain)
Note: Parameter name in create_node tool is "use_deep_agents" (maps to useDeepAgents in config)

<role-allocation>
1. Decompose task into phases: Information Gathering → Processing → Synthesis → Quality Control
2. Design roles by expertise: Researcher, Analyst, Synthesizer, Validator, Specialist
3. Single responsibility: Each SubAgent does ONE thing. If role has "and", SPLIT IT.
</role-allocation>

<manager-requirements>
- use_deep_agents=True (REQUIRED in create_node tool)
- description: "[Team Name]-team: [One-sentence goal]" (REQUIRED)
- systemPrompt MUST list ALL SubAgents with their capabilities
- Use task() tool to delegate to subagents
- DO NOT perform specialist tasks yourself
- DO NOT add tools_builtin or tools_mcp (Manager uses internal task() only)
</manager-requirements>

<subagent-requirements>
- use_deep_agents=False (REQUIRED in create_node tool)
- description: "[Action verb] [what] [output format]" (REQUIRED)
- systemPrompt: Role definition, single task, output format, quality standards
- Specialized tools allowed (tools_builtin, tools_mcp) - NOT for Manager
</subagent-requirements>
</deepagents-architecture>
"""

    # Pre-calculate DeepAgents positions using unified function (1 Manager + 3 SubAgents example)
    deepagents_positions = calculate_positions_for_deepagents(
        base_x=next_position_x, base_y=next_position_y, manager_count=1, subagent_count=3, x_spacing=250, y_spacing=150
    )

    # Extract calculated positions (use unified function results, no hardcoded fallbacks)
    manager_pos = (
        deepagents_positions["manager"][0]
        if deepagents_positions["manager"]
        else {"x": next_position_x, "y": next_position_y}
    )
    subagent1_pos = (
        deepagents_positions["subagents"][0]
        if len(deepagents_positions["subagents"]) > 0
        else {"x": next_position_x + 250, "y": next_position_y}
    )
    subagent2_pos = (
        deepagents_positions["subagents"][1]
        if len(deepagents_positions["subagents"]) > 1
        else {"x": next_position_x + 250, "y": next_position_y + 150}
    )
    subagent3_pos = (
        deepagents_positions["subagents"][2]
        if len(deepagents_positions["subagents"]) > 2
        else {"x": next_position_x + 250, "y": next_position_y + 300}
    )

    # Execution workflow - Optimized with clear algorithms
    prompt += f"""
<execution-workflow>
<step1-analyze>
Apply decision rule from <system-reminder>:
- Simple single-step? → Single agent
- Multi-step/complex? → DeepAgents (DEFAULT)
</step1-analyze>

<step2-deepagents>
1. think(stage="planning", nodes=[...]) - 验证角色和数量
2. create_node(Manager) - Coordinator first, use_deep_agents=True
3. create_node(SubAgent1, SubAgent2, ...) - Specialists, use_deep_agents=False
4. connect_nodes(Manager → each SubAgent) - Star topology
5. think(stage="validation", nodes=[...], connections=[...]) - 验证连线和拓扑
</step2-deepagents>

<position-calculation>
Pre-calculated positions for DeepAgents workflow (1 Manager + 3 SubAgents example):
Manager: x={manager_pos["x"]}, y={manager_pos["y"]}
SubAgent1: x={subagent1_pos["x"]}, y={subagent1_pos["y"]}
SubAgent2: x={subagent2_pos["x"]}, y={subagent2_pos["y"]}
SubAgent3: x={subagent3_pos["x"]}, y={subagent3_pos["y"]}
Pattern: Additional SubAgents continue vertically: y + 150 for each next SubAgent (x remains {subagent1_pos["x"]})
For single nodes (non-DeepAgents): Use nextPosition from <context> section above.
</position-calculation>

<systemprompt-checklist>
For EVERY agent node:
- [ ] Clear ROLE definition
- [ ] Specific TASK description
- [ ] OUTPUT FORMAT specification
- [ ] DO NOT / constraints section
- [ ] Manager lists ALL SubAgents
- [ ] SubAgents have single responsibility
</systemprompt-checklist>

<common-mistakes>
❌ Generic prompts ("You are a helpful assistant")
❌ Missing output format
❌ Chain topology (SubAgent1 → SubAgent2 → SubAgent3)
❌ Manager without SubAgent list
❌ SubAgent with multiple responsibilities
</common-mistakes>
</execution-workflow>

<simple-mode>
Single agent mode: ONLY for translation, formatting, simple classification (trivial single-step tasks).
All other tasks → Use DeepAgents (see <system-reminder>).
</simple-mode>

<conversational>
If user is asking questions or chatting, respond helpfully without tools.
</conversational>
"""

    return prompt


def _should_suggest_deep_agents(topology_description: str) -> bool:
    """Check if current context suggests DeepAgents might be useful."""
    # Include DeepAgents section if graph mentions it or is complex enough
    keywords = ["DeepAgents", "Manager", "SubAgent", "deep", "complex workflow"]
    return any(kw.lower() in topology_description.lower() for kw in keywords)


# Legacy function for backward compatibility (will be removed in future)
def _get_system_prompt_template(topology_description: str, context_str: str, current_time: str) -> str:
    """
    Legacy function - redirects to optimized version.
    Kept for backward compatibility during transition.
    """
    # Parse context_str to extract needed values
    try:
        context_data = json.loads(context_str)
        next_pos = context_data.get("nextAvailablePosition", {"x": 100, "y": 100})
        models_summary = context_data.get("availableModels", {})
        existing_nodes = context_data.get("existingNodes", [])
        edges = context_data.get("edges", [])
        topology = context_data.get("graphTopology", {})
        has_deep_agents = bool(topology.get("deepAgentsHierarchy", {}))
    except (json.JSONDecodeError, TypeError):
        next_pos = {"x": 100, "y": 100}
        models_summary = {}
        existing_nodes = []
        edges = []
        topology = {}
        has_deep_agents = False

    return _get_optimized_system_prompt(
        topology_description=topology_description,
        existing_nodes=existing_nodes,
        edges=edges,
        topology=topology,
        next_position_x=next_pos.get("x", 100),
        next_position_y=next_pos.get("y", 100),
        models_summary=models_summary,
        current_time=current_time,
        has_deep_agents=has_deep_agents,
    )
