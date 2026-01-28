"""
Action Applier - Apply Copilot actions to graph state.

Converts Copilot actions (CREATE_NODE, CONNECT_NODES, etc.) to complete
graph state (nodes and edges) that can be saved to the database.

This module replicates the logic from frontend ActionProcessor to ensure
consistency between frontend and backend graph state.
"""

from typing import Any, Dict, List, Tuple

from loguru import logger

# Node type default configurations (matching frontend nodeRegistry)
NODE_DEFAULT_CONFIGS: Dict[str, Dict[str, Any]] = {
    "agent": {
        "model": "DeepSeek-Chat",
        "temp": 0.7,
        "systemPrompt": "",
        "enableMemory": False,
        "memoryModel": "DeepSeek-Chat",
        "memoryPrompt": "Summarize the interaction highlights and key facts learned about the user.",
        "useDeepAgents": False,
        "description": "",
    },
    "condition": {
        "expression": "",
        "trueLabel": "Yes",
        "falseLabel": "No",
    },
    "condition_agent": {
        "instruction": "Analyze and route",
        "options": ["Option A", "Option B"],
    },
    "http": {
        "method": "GET",
        "url": "https://api.example.com",
    },
    "custom_function": {
        "name": "my_tool",
        "description": "",
        "parameters": [],
    },
    "direct_reply": {
        "template": "Hello user",
    },
    "human_input": {
        "prompt": "Please approve",
    },
    "router_node": {
        "routes": [],
        "defaultRoute": "default",
    },
    "loop_condition_node": {
        "conditionType": "while",
        "listVariable": "items",
        "condition": "loop_count < 3",
        "maxIterations": 5,
    },
}

# Node type labels (matching frontend nodeRegistry)
NODE_LABELS: Dict[str, str] = {
    "agent": "Agent",
    "condition": "Condition",
    "condition_agent": "Condition Agent",
    "http": "HTTP Request",
    "custom_function": "Custom Tool",
    "direct_reply": "Direct Reply",
    "human_input": "Human Input",
    "router_node": "Router",
    "loop_condition_node": "Loop Condition",
}


def get_node_default_config(node_type: str) -> Dict[str, Any]:
    """Get default configuration for a node type."""
    return NODE_DEFAULT_CONFIGS.get(node_type, {}).copy()


def get_node_label(node_type: str) -> str:
    """Get default label for a node type."""
    return NODE_LABELS.get(node_type, "Node")


def apply_actions_to_graph_state(
    current_nodes: List[Dict[str, Any]],
    current_edges: List[Dict[str, Any]],
    actions: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Apply Copilot actions to current graph state and return updated nodes and edges.

    This function replicates the logic from frontend ActionProcessor.processActions
    to ensure consistency between frontend and backend.

    Args:
        current_nodes: Current nodes in the graph (from graph_context)
        current_edges: Current edges in the graph (from graph_context)
        actions: List of actions to apply (CREATE_NODE, CONNECT_NODES, etc.)

    Returns:
        Tuple of (updated_nodes, updated_edges) in format ready for GraphService.save_graph_state
    """
    # Clone current state to apply diffs
    processed_nodes: List[Dict[str, Any]] = [node.copy() for node in current_nodes]
    processed_edges: List[Dict[str, Any]] = [edge.copy() for edge in current_edges]

    for action in actions:
        action_type = action.get("type")
        payload = action.get("payload", {})

        try:
            if action_type == "CREATE_NODE":
                node_id = payload.get("id")
                node_type = payload.get("type", "agent")
                label = payload.get("label")
                position = payload.get("position", {"x": 0, "y": 0})
                config = payload.get("config", {})

                # Get default config and merge with action config
                base_config = get_node_default_config(node_type)
                merged_config = {**base_config, **config}

                # Use default label if not provided
                node_label = label or get_node_label(node_type)

                # Create node in format expected by GraphService.save_graph_state
                # Format matches frontend: { id, type: 'custom', position, data: { label, type, config } }
                new_node: Dict[str, Any] = {
                    "id": node_id or f"ai_{hash(str(action)) % 1000000}",
                    "type": "custom",  # React Flow node type (fixed)
                    "position": position,
                    "data": {
                        "label": node_label,
                        "type": node_type,  # Business type (agent, condition, etc.)
                        "config": merged_config,
                    },
                }

                processed_nodes.append(new_node)
                logger.debug(f"[ActionApplier] Created node: {node_id}, type: {node_type}, label: {node_label}")

            elif action_type == "CONNECT_NODES":
                source = payload.get("source")
                target = payload.get("target")

                if source and target:
                    # Check if edge already exists
                    edge_exists = any(e.get("source") == source and e.get("target") == target for e in processed_edges)

                    if not edge_exists:
                        # Create edge in format expected by GraphService.save_graph_state
                        # Format matches frontend: { id, source, target, data: {} }
                        new_edge: Dict[str, Any] = {
                            "id": f"e-{source}-{target}",
                            "source": source,
                            "target": target,
                            "animated": True,
                            "style": {"stroke": "#cbd5e1", "strokeWidth": 1.5},
                            "data": {},  # Must exist, even if empty (required by backend)
                        }

                        processed_edges.append(new_edge)
                        logger.debug(f"[ActionApplier] Created edge: {source} -> {target}")

            elif action_type == "DELETE_NODE":
                node_id = payload.get("id")

                if node_id:
                    # Remove node
                    processed_nodes = [n for n in processed_nodes if n.get("id") != node_id]

                    # Remove edges connected to this node
                    processed_edges = [
                        e for e in processed_edges if e.get("source") != node_id and e.get("target") != node_id
                    ]

                    logger.debug(f"[ActionApplier] Deleted node: {node_id}")

            elif action_type == "UPDATE_CONFIG":
                node_id = payload.get("id")
                config_updates = payload.get("config", {})

                if node_id and config_updates:
                    for node in processed_nodes:
                        if node.get("id") == node_id:
                            node_data = node.get("data", {})
                            if isinstance(node_data, dict):
                                existing_config = node_data.get("config", {})
                                if isinstance(existing_config, dict):
                                    # Merge config updates
                                    node_data["config"] = {**existing_config, **config_updates}
                                    logger.debug(f"[ActionApplier] Updated config for node: {node_id}")
                            break

            elif action_type == "UPDATE_POSITION":
                node_id = payload.get("id")
                position = payload.get("position")

                if node_id and position:
                    for node in processed_nodes:
                        if node.get("id") == node_id:
                            node["position"] = position
                            logger.debug(f"[ActionApplier] Updated position for node: {node_id}")
                            break

        except Exception as e:
            logger.error(f"[ActionApplier] Error processing action {action_type}: {e}", exc_info=True)
            # Continue processing other actions even if one fails

    # Deduplicate edges (based on source-target combination)
    seen_edges: Dict[Tuple[str, str], bool] = {}
    deduplicated_edges: List[Dict[str, Any]] = []

    for edge in processed_edges:
        source = edge.get("source")
        target = edge.get("target")

        if source and target:
            edge_key = (source, target)
            if edge_key not in seen_edges:
                seen_edges[edge_key] = True
                deduplicated_edges.append(edge)

    logger.info(
        f"[ActionApplier] Applied {len(actions)} actions: "
        f"nodes {len(current_nodes)} -> {len(processed_nodes)}, "
        f"edges {len(current_edges)} -> {len(deduplicated_edges)}"
    )

    return processed_nodes, deduplicated_edges
