"""
Node ID Registry - Thread-safe registry for tracking created nodes.

Provides semantic reference resolution for Copilot tools, allowing nodes
to be referenced by label or sequence number in addition to their actual IDs.
"""

import contextvars
from typing import Any, Dict, List, Optional


class NodeIdRegistry:
    """
    Registry to track created nodes and their semantic references.

    Allows the model to reference nodes by:
    1. Actual UUID (e.g., "agent_abc12345")
    2. Label-based reference (e.g., "@Research Manager", "@label:Research Agent")
    """

    def __init__(self):
        self._nodes: Dict[str, Dict[str, Any]] = {}  # id -> {label, type, seq}
        self._by_label: Dict[str, str] = {}  # normalized_label -> id
        self._by_seq: Dict[int, str] = {}  # sequence_number -> id
        self._counter: int = 0

    def register(self, node_id: str, label: str, node_type: str) -> int:
        """Register a new node and return its sequence number."""
        self._counter += 1
        seq = self._counter

        self._nodes[node_id] = {
            "label": label,
            "type": node_type,
            "seq": seq,
        }

        # Register by normalized label for lookup
        normalized_label = label.lower().strip()
        self._by_label[normalized_label] = node_id
        self._by_seq[seq] = node_id

        return seq

    def resolve(self, ref: str) -> str:
        """
        Resolve a reference to an actual node ID.

        Supported formats:
        - Actual ID: "agent_abc12345" -> returns as-is
        - Label: "@Research Agent", "@label:Support" -> resolves by label
        """
        if not ref:
            return ref

        ref = ref.strip()

        # Check if it's already an actual ID (contains underscore with hex)
        if "_" in ref and not ref.startswith("@"):
            return ref

        # Check for label reference: @Label or @label:Label
        if ref.startswith("@label:"):
            label = ref[7:].lower().strip()
        elif ref.startswith("@"):
            label = ref[1:].lower().strip()
        else:
            return ref  # Not a reference, return as-is

        if label in self._by_label:
            return self._by_label[label]

        # Try partial match
        for stored_label, node_id in self._by_label.items():
            if label in stored_label or stored_label in label:
                return node_id

        return ref  # Return original if not found

    def get_last_id(self) -> Optional[str]:
        """Get the ID of the last created node."""
        if self._counter > 0 and self._counter in self._by_seq:
            return self._by_seq[self._counter]
        return None

    def get_all_ids(self) -> List[str]:
        """Get all registered node IDs."""
        return list(self._nodes.keys())

    def clear(self):
        """Clear the registry for a new session."""
        self._nodes.clear()
        self._by_label.clear()
        self._by_seq.clear()
        self._counter = 0


# Thread-safe context variable for node registry (per-request isolation)
_node_registry_context: contextvars.ContextVar[Optional[NodeIdRegistry]] = contextvars.ContextVar(
    "node_registry", default=None
)


def get_node_registry() -> NodeIdRegistry:
    """Get the current node registry from context, creating one if needed."""
    registry = _node_registry_context.get()
    if registry is None:
        registry = NodeIdRegistry()
        _node_registry_context.set(registry)
    return registry


def reset_node_registry():
    """Reset the node registry for a new request."""
    registry = get_node_registry()
    registry.clear()
