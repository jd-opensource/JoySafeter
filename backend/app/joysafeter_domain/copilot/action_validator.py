"""
Action Validator - Validates Copilot-generated actions before execution.

Provides validation for:
- Node ID references (existing + newly created)
- Graph topology (orphan nodes, connectivity)
- Action consistency
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger


class ActionValidationResult:
    """Result of action validation."""

    def __init__(self):
        self.is_valid: bool = True
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.fixed_actions: Optional[List[Dict[str, Any]]] = None

    def add_error(self, message: str):
        """Add an error (validation failed)."""
        self.is_valid = False
        self.errors.append(message)

    def add_warning(self, message: str):
        """Add a warning (validation passed with issues)."""
        self.warnings.append(message)


def validate_actions(
    actions: List[Dict[str, Any]],
    existing_node_ids: Set[str],
) -> ActionValidationResult:
    """
    Validate a list of actions for consistency and correctness.

    Checks:
    1. All node references in CONNECT_NODES, DELETE_NODE, UPDATE_CONFIG exist
    2. No duplicate node IDs are created
    3. Graph connectivity (warns about orphan nodes)

    Args:
        actions: List of action dicts from Copilot
        existing_node_ids: Set of node IDs already in the graph

    Returns:
        ActionValidationResult with validation status and details
    """
    result = ActionValidationResult()

    # Track nodes created in this batch
    created_node_ids: Set[str] = set()
    created_node_labels: Dict[str, str] = {}  # id -> label

    # Track connections
    connections: List[Tuple[str, str]] = []

    # All valid IDs (existing + newly created)
    all_valid_ids = existing_node_ids.copy()

    for i, action in enumerate(actions):
        action_type = action.get("type", "")
        payload = action.get("payload", {})

        if action_type == "CREATE_NODE":
            node_id = payload.get("id", "")
            label = payload.get("label", "")

            if not node_id:
                result.add_error(f"Action {i}: CREATE_NODE missing node ID")
                continue

            # Check for duplicate ID
            if node_id in all_valid_ids:
                result.add_warning(f"Action {i}: Duplicate node ID '{node_id}' - may overwrite existing node")

            created_node_ids.add(node_id)
            created_node_labels[node_id] = label
            all_valid_ids.add(node_id)

        elif action_type == "CONNECT_NODES":
            source = payload.get("source", "")
            target = payload.get("target", "")

            if not source:
                result.add_error(f"Action {i}: CONNECT_NODES missing source ID")
            elif source not in all_valid_ids:
                result.add_error(f"Action {i}: CONNECT_NODES source '{source}' not found")

            if not target:
                result.add_error(f"Action {i}: CONNECT_NODES missing target ID")
            elif target not in all_valid_ids:
                result.add_error(f"Action {i}: CONNECT_NODES target '{target}' not found")

            if source and target:
                connections.append((source, target))

        elif action_type == "DELETE_NODE":
            node_id = payload.get("id", "")

            if not node_id:
                result.add_error(f"Action {i}: DELETE_NODE missing node ID")
            elif node_id not in all_valid_ids:
                result.add_error(f"Action {i}: DELETE_NODE node '{node_id}' not found")
            else:
                # Remove from valid IDs (node will be deleted)
                all_valid_ids.discard(node_id)

        elif action_type == "UPDATE_CONFIG":
            node_id = payload.get("id", "")

            if not node_id:
                result.add_error(f"Action {i}: UPDATE_CONFIG missing node ID")
            elif node_id not in all_valid_ids:
                result.add_error(f"Action {i}: UPDATE_CONFIG node '{node_id}' not found")

    # Check for orphan nodes (newly created nodes not connected to anything)
    if created_node_ids:
        connected_nodes: Set[str] = set()
        for src, tgt in connections:
            connected_nodes.add(src)
            connected_nodes.add(tgt)

        # Include existing nodes as potentially connected
        connected_nodes.update(existing_node_ids)

        orphan_nodes = created_node_ids - connected_nodes

        # Only warn if multiple nodes were created (single node is fine without connections)
        if orphan_nodes and len(created_node_ids) > 1:
            for node_id in orphan_nodes:
                label = created_node_labels.get(node_id, node_id)
                result.add_warning(f"Orphan node: '{label}' ({node_id}) is not connected to the workflow")

    logger.info(
        f"[ActionValidator] Validation complete: valid={result.is_valid}, errors={len(result.errors)}, warnings={len(result.warnings)}"
    )

    return result


def extract_existing_node_ids(graph_context: Dict[str, Any]) -> Set[str]:
    """
    Extract existing node IDs from graph context.

    Args:
        graph_context: Graph context dict with nodes

    Returns:
        Set of existing node IDs
    """
    node_ids: Set[str] = set()

    nodes = graph_context.get("nodes", [])
    for node in nodes:
        # Handle ReactFlow format
        node_id = node.get("id")
        if node_id:
            node_ids.add(node_id)

    return node_ids


def filter_invalid_actions(
    actions: List[Dict[str, Any]],
    existing_node_ids: Set[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Filter out invalid actions and return valid ones with removal reasons.

    Args:
        actions: List of action dicts
        existing_node_ids: Set of existing node IDs

    Returns:
        Tuple of (valid_actions, removed_reasons)
    """
    valid_actions: List[Dict[str, Any]] = []
    removed_reasons: List[str] = []

    # Track nodes as we process
    all_valid_ids = existing_node_ids.copy()

    for i, action in enumerate(actions):
        action_type = action.get("type", "")
        payload = action.get("payload", {})
        keep = True
        reason = ""

        if action_type == "CREATE_NODE":
            node_id = payload.get("id", "")
            if node_id:
                all_valid_ids.add(node_id)
            else:
                keep = False
                reason = f"Action {i}: CREATE_NODE has no ID"

        elif action_type == "CONNECT_NODES":
            source = payload.get("source", "")
            target = payload.get("target", "")

            if source not in all_valid_ids:
                keep = False
                reason = f"Action {i}: CONNECT_NODES source '{source}' not found"
            elif target not in all_valid_ids:
                keep = False
                reason = f"Action {i}: CONNECT_NODES target '{target}' not found"

        elif action_type == "DELETE_NODE":
            node_id = payload.get("id", "")
            if node_id not in all_valid_ids:
                keep = False
                reason = f"Action {i}: DELETE_NODE node '{node_id}' not found"
            else:
                all_valid_ids.discard(node_id)

        elif action_type == "UPDATE_CONFIG":
            node_id = payload.get("id", "")
            if node_id not in all_valid_ids:
                keep = False
                reason = f"Action {i}: UPDATE_CONFIG node '{node_id}' not found"

        if keep:
            valid_actions.append(action)
        else:
            removed_reasons.append(reason)
            logger.warning(f"[ActionValidator] Removing invalid action: {reason}")

    return valid_actions, removed_reasons
