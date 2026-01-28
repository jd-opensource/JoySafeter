"""
Graph Analyzer - Utility functions for analyzing graph topology.

Provides functions to normalize nodes, analyze topology, and extract
node configurations for the Copilot system prompt.
"""

from typing import Any, Dict, List, Optional


def normalize_node(node: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize node format from ReactFlow format.

    Frontend sends complete ReactFlow format:
    {
      "id": "...",
      "type": "custom",
      "position": {...},
      "data": {
        "type": "agent",
        "label": "...",
        "config": {...},
        "tools": {...}  // optional
      }
    }

    Consistent with base_builder._get_node_type logic:
    - Priority: data.type -> node.type -> default "agent"
    """
    data = node.get("data", {})
    if isinstance(data, dict):
        node_type = data.get("type") or node.get("type") or "agent"
        return {
            "id": node.get("id"),
            "type": node_type,
            "label": data.get("label", ""),
            "position": node.get("position", {}),
            "config": data.get("config", {}),
            "tools": data.get("tools"),
            "prompt": node.get("prompt"),
        }
    else:
        # Fallback: if data doesn't exist or is malformed
        return {
            "id": node.get("id"),
            "type": node.get("type", "agent"),
            "label": node.get("label", ""),
            "position": node.get("position", {}),
            "config": node.get("config", {}),
            "tools": node.get("tools"),
            "prompt": node.get("prompt"),
        }


def extract_system_prompt(normalized_node: Dict[str, Any]) -> Optional[str]:
    """
    Extract system prompt from node configuration.

    Extraction order (consistent with base_builder._get_system_prompt_from_node):
    1. node.prompt (GraphNode.prompt, if exists)
    2. data.config.systemPrompt
    3. data.config.prompt
    4. None
    """
    prompt = normalized_node.get("prompt")
    if prompt:
        return str(prompt) if not isinstance(prompt, str) else prompt

    config = normalized_node.get("config", {})
    if isinstance(config, dict):
        return config.get("systemPrompt", "") or config.get("prompt", "") or None
    return None


def extract_tools_config(normalized_node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract tools configuration from node.

    Tools config format:
    {
        "builtin": ["tool_id1", "tool_id2", ...],
        "mcp": ["uuid_or_url1", "uuid_or_url2", ...]
    }

    Tools may be stored in:
    1. data.config.tools (primary location)
    2. data.tools (some nodes may define here)

    Returns tools config dict or None if not found.
    """
    config = normalized_node.get("config", {})
    if isinstance(config, dict):
        config_tools = config.get("tools")
        if isinstance(config_tools, dict):
            return config_tools

    node_tools = normalized_node.get("tools")
    if isinstance(node_tools, dict):
        return node_tools

    return None


def format_tools_summary(tools_config: Optional[Dict[str, Any]]) -> str:
    """
    Format tools configuration as a readable summary string.

    Used in system prompt to display tool information.
    """
    if not tools_config:
        return "None"

    parts = []
    builtin = tools_config.get("builtin", [])
    mcp = tools_config.get("mcp", [])

    if builtin:
        parts.append(f"builtin: {', '.join(builtin)}")
    if mcp:
        parts.append(f"mcp: {len(mcp)} tool(s)")

    return "; ".join(parts) if parts else "None"


def analyze_graph_topology(normalized_nodes: List[Dict], edges: List[Dict]) -> Dict[str, Any]:
    """
    Analyze graph topology structure.

    Topology analysis includes:
    1. Build connection relationships (incoming/outgoing edges)
    2. Identify root nodes (in-degree 0) and leaf nodes (out-degree 0)
    3. Analyze DeepAgents hierarchy (Manager/Worker roles)

    DeepAgents role logic (consistent with _build_recursive):
    - Worker: no children (leaf node)
    - Manager: has children (non-leaf node)
    """
    node_ids = {n["id"] for n in normalized_nodes}

    # Build connection relationships
    incoming: Dict[str, List[str]] = {node_id: [] for node_id in node_ids}
    outgoing: Dict[str, List[str]] = {node_id: [] for node_id in node_ids}

    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if (
            source is not None
            and target is not None
            and isinstance(source, str)
            and isinstance(target, str)
            and source in node_ids
            and target in node_ids
        ):
            outgoing[source].append(target)
            incoming[target].append(source)

    # Find root nodes (in-degree 0) and leaf nodes (out-degree 0)
    root_nodes = [n["id"] for n in normalized_nodes if len(incoming.get(n["id"], [])) == 0]
    leaf_nodes = [n["id"] for n in normalized_nodes if len(outgoing.get(n["id"], [])) == 0]

    # Analyze DeepAgents hierarchy
    deep_agents_hierarchy: Dict[str, Dict[str, Any]] = {}
    for node in normalized_nodes:
        node_id = node["id"]
        config = node.get("config", {})

        if config.get("useDeepAgents", False) is True:
            children = outgoing.get(node_id, [])

            # Role determination:
            # - No children = Worker (Leaf Node)
            # - Has children = Manager (DeepAgent)
            if not children:
                role = "Worker"
            else:
                role = "Manager"

            deep_agents_hierarchy[node_id] = {
                "role": role,
                "children": children,
                "description": config.get("description", ""),
            }

    return {
        "rootNodes": root_nodes,
        "leafNodes": leaf_nodes,
        "deepAgentsHierarchy": deep_agents_hierarchy,
        "incoming": incoming,
        "outgoing": outgoing,
    }


def generate_topology_description(
    normalized_nodes: List[Dict], topology: Dict[str, Any], node_map: Dict[str, Dict]
) -> str:
    """
    Generate structured topology description text showing graph flow structure.

    Example output:
    "Current Flow: [Start: Support Agent] -> [Condition: Sentiment Check] -> [Branch A: Thank You] / [Branch B: Human Escalation]"

    For DeepAgents:
    "DeepAgents Hierarchy: [Manager: Research Coordinator] -> [Worker: Research SubAgent]"
    """
    if not normalized_nodes:
        return "Current Flow: (Empty graph - no nodes yet)"

    root_nodes = topology.get("rootNodes", [])
    outgoing = topology.get("outgoing", {})
    deep_agents_hierarchy = topology.get("deepAgentsHierarchy", {})

    # Build node ID to node info mapping
    node_id_to_info: Dict[str, Dict[str, Any]] = {}
    for node in normalized_nodes:
        node_id = node["id"]
        node_type = node.get("type", "agent")
        label = node.get("label", "") or node_id[:8]
        config = node.get("config", {})
        is_deep_agent = config.get("useDeepAgents", False) is True

        # Generate node display name
        type_abbr = {
            "agent": "Agent",
            "condition": "Condition",
            "condition_agent": "AI Decision",
            "http": "HTTP",
            "custom_function": "Custom",
            "direct_reply": "Reply",
            "human_input": "Human",
            "execute_flow": "SubFlow",
            "iteration": "Loop",
        }.get(node_type, node_type)

        display_name = f"{type_abbr}: {label}"
        if is_deep_agent:
            role = deep_agents_hierarchy.get(node_id, {}).get("role", "")
            if role:
                display_name += f" [{role}]"

        node_id_to_info[node_id] = {
            "display": display_name,
            "type": node_type,
            "label": label,
            "is_deep_agent": is_deep_agent,
            "role": deep_agents_hierarchy.get(node_id, {}).get("role"),
        }

    # Generate main flow description
    flow_parts: List[str] = []

    # If there are DeepAgents, describe hierarchy first
    if deep_agents_hierarchy:
        flow_parts.append("DeepAgents Hierarchy:")
        for node_id, info in deep_agents_hierarchy.items():
            node_info = node_id_to_info.get(node_id, {})
            role = info.get("role", "")
            children = info.get("children", [])

            if role == "Manager":
                manager_name = node_info.get("display", node_id[:8])
                child_displays = []
                for cid in children:
                    child_info = node_id_to_info.get(cid, {})
                    child_display = child_info.get("display", cid[:8])
                    child_displays.append(f"[{child_display}]")

                if child_displays:
                    flow_parts.append(f"  [{role}: {manager_name}] -> {', '.join(child_displays)}")
                else:
                    flow_parts.append(f"  [{role}: {manager_name}] (no subagents)")

    # Generate main flow path
    if root_nodes:
        flow_parts.append("Current Flow:")

        def traverse_path(node_id: str, visited: set, depth: int = 0) -> List[str]:
            """Recursively traverse path, handle branches"""
            if node_id in visited or depth > 20:
                return ["[...]"]

            visited.add(node_id)
            node_info = node_id_to_info.get(node_id, {})
            display = node_info.get("display", node_id[:8])

            children = outgoing.get(node_id, [])

            if not children:
                return [f"[{display}]"]

            if len(children) == 1:
                child_path = traverse_path(children[0], visited.copy(), depth + 1)
                return [f"[{display}]"] + child_path
            else:
                branch_paths = []
                for i, child_id in enumerate(children):
                    child_path = traverse_path(child_id, visited.copy(), depth + 1)
                    branch_label = chr(65 + i)  # A, B, C...
                    if len(child_path) == 1:
                        branch_paths.append(f"[Branch {branch_label}: {child_path[0]}]")
                    else:
                        branch_paths.append(f"[Branch {branch_label}: {child_path[0]} -> ...]")

                return [f"[{display}]"] + [f" -> {' / '.join(branch_paths)}"]

        # Traverse from each root node
        all_paths = []
        for root_id in root_nodes[:3]:  # Show max 3 root nodes
            path = traverse_path(root_id, set())
            all_paths.append(" -> ".join(path))

        if all_paths:
            if len(all_paths) == 1:
                flow_parts.append(f"  {all_paths[0]}")
            else:
                flow_parts.append(f"  {' | '.join(all_paths)}")
    else:
        flow_parts.append("Current Flow: (No clear entry point - disconnected nodes)")

    return "\n".join(flow_parts)


def build_enhanced_node_data(normalized_nodes: List[Dict], topology: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build enhanced context data for each node.

    Returns a list of node data with extracted configurations
    for the system prompt.
    """
    existing_nodes = []

    for normalized_node in normalized_nodes:
        node_id = normalized_node["id"]
        config = normalized_node.get("config", {})

        # Extract system prompt
        system_prompt = extract_system_prompt(normalized_node)

        # Extract model information
        model = config.get("model_name") or config.get("model") or None

        # Extract tools configuration
        tools_config = extract_tools_config(normalized_node)
        tools_summary = format_tools_summary(tools_config)

        # Check if DeepAgents is enabled
        is_deep_agent = config.get("useDeepAgents", False) is True

        # Get DeepAgents role and children from topology analysis
        deep_agent_info = topology["deepAgentsHierarchy"].get(node_id, {})
        role = deep_agent_info.get("role") if is_deep_agent else None
        children = topology["outgoing"].get(node_id, [])

        node_data = {
            "id": node_id,
            "type": normalized_node.get("type", "agent"),
            "label": normalized_node.get("label", ""),
            "position": normalized_node.get("position", {}),
            "systemPrompt": system_prompt,
            "model": model,
            "tools": tools_summary,
            "config": config,
            "isDeepAgent": is_deep_agent,
            "role": role,
            "children": children,
        }

        existing_nodes.append(node_data)

    return existing_nodes


def calculate_positions_for_nodes(
    base_x: float,
    base_y: float,
    node_count: int,
    layout_type: str = "deepagents",
    x_spacing: float = 250,
    y_spacing: float = 150,
) -> List[Dict[str, float]]:
    """
    Unified function to calculate positions for multiple nodes.

    Supports different layout patterns:
    - "deepagents": Manager on left, SubAgents on right (vertical stack)
    - "horizontal": All nodes in a horizontal row
    - "vertical": All nodes in a vertical column

    Args:
        base_x: Base X coordinate
        base_y: Base Y coordinate
        node_count: Total number of nodes to calculate positions for
        layout_type: Layout pattern ("deepagents", "horizontal", "vertical")
        x_spacing: Horizontal spacing between nodes
        y_spacing: Vertical spacing between nodes

    Returns:
        List of position dicts, each with {"x": float, "y": float}
    """
    positions: List[Dict[str, float]] = []

    if layout_type == "deepagents":
        # DeepAgents layout: First node (Manager) on left, rest (SubAgents) on right
        if node_count == 0:
            return positions

        # First node (Manager) at base position
        positions.append({"x": base_x, "y": base_y})

        # Remaining nodes (SubAgents) on the right, stacked vertically
        for i in range(1, node_count):
            positions.append({"x": base_x + x_spacing, "y": base_y + (i - 1) * y_spacing})

    elif layout_type == "horizontal":
        # Horizontal layout: All nodes in a row
        for i in range(node_count):
            positions.append({"x": base_x + i * x_spacing, "y": base_y})

    elif layout_type == "vertical":
        # Vertical layout: All nodes in a column
        for i in range(node_count):
            positions.append({"x": base_x, "y": base_y + i * y_spacing})

    else:
        # Default to horizontal if unknown layout type
        for i in range(node_count):
            positions.append({"x": base_x + i * x_spacing, "y": base_y})

    return positions


def calculate_positions_for_deepagents(
    base_x: float,
    base_y: float,
    manager_count: int = 1,
    subagent_count: int = 5,
    x_spacing: float = 250,
    y_spacing: float = 150,
) -> Dict[str, List[Dict[str, float]]]:
    """
    Calculate positions for DeepAgents workflow (Manager + SubAgents).

    This is a convenience wrapper around calculate_positions_for_nodes()
    that separates Manager and SubAgent positions.

    Args:
        base_x: Base X coordinate
        base_y: Base Y coordinate
        manager_count: Number of Manager nodes (typically 1)
        subagent_count: Number of SubAgent nodes
        x_spacing: Horizontal spacing from Manager to SubAgents
        y_spacing: Vertical spacing between SubAgents

    Returns:
        {
            "manager": [{"x": float, "y": float}, ...],
            "subagents": [{"x": float, "y": float}, ...]
        }
    """
    result: Dict[str, List[Dict[str, float]]] = {"manager": [], "subagents": []}

    # Calculate Manager positions (on the left)
    if manager_count > 0:
        manager_positions = calculate_positions_for_nodes(
            base_x=base_x,
            base_y=base_y,
            node_count=manager_count,
            layout_type="vertical",
            x_spacing=0,
            y_spacing=y_spacing,
        )
        result["manager"] = manager_positions

    # Calculate SubAgent positions (on the right, vertical stack)
    if subagent_count > 0:
        subagent_positions = calculate_positions_for_nodes(
            base_x=base_x + x_spacing,
            base_y=base_y,
            node_count=subagent_count,
            layout_type="vertical",
            x_spacing=0,
            y_spacing=y_spacing,
        )
        result["subagents"] = subagent_positions

    return result


def calculate_next_position(normalized_nodes: List[Dict]) -> Dict[str, float]:
    """
    Calculate the next available position for a single new node.

    Primary flow: 250px to the right, same Y
    Empty graph: default starting position (100, 100)

    This function uses calculate_positions_for_nodes() internally for consistency.
    """
    if not normalized_nodes:
        return {"x": 100, "y": 100}

    last_node = normalized_nodes[-1]
    last_position = last_node.get("position", {"x": 0, "y": 0})

    # Use unified function for consistency
    positions = calculate_positions_for_nodes(
        base_x=last_position.get("x", 0),
        base_y=last_position.get("y", 100),
        node_count=1,
        layout_type="horizontal",
        x_spacing=250,
        y_spacing=150,
    )
    return positions[0] if positions else {"x": 100, "y": 100}
