"""
Graph Schema — Declarative graph definition as data.

Provides Pydantic models that represent a graph's structure (state fields,
nodes, edges) as a portable, versionable, serializable schema.  This is the
single source of truth from which both the LangGraph StateGraph and
standalone Python code can be generated.

Key design decisions
--------------------
* **State-centric**: State fields are first-class citizens; nodes declare
  which fields they read/write.
* **DB-agnostic**: ``GraphSchema.from_db()`` bridges the database models to
  the schema layer, but the schema itself has no DB dependency.
* **Backward-compatible**: Existing graphs that lack schema metadata fall
  back to the full ``GraphState`` and wildcard reads/writes.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class StateFieldType(str, Enum):
    """Supported state field data types."""

    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    LIST = "list"
    DICT = "dict"
    MESSAGES = "messages"  # LangChain BaseMessage list
    ANY = "any"


class ReducerType(str, Enum):
    """Built-in reducer functions for state field updates."""

    REPLACE = "replace"  # Default: new value replaces old
    ADD = "add"  # operator.add (lists, ints)
    APPEND = "append"  # Append to list
    MERGE = "merge"  # Deep-merge dicts
    ADD_MESSAGES = "add_messages"  # LangChain message merging
    CUSTOM = "custom"  # User-provided reducer string


class EdgeType(str, Enum):
    """Edge classification."""

    NORMAL = "normal"
    CONDITIONAL = "conditional"
    LOOP_BACK = "loop_back"


# ---------------------------------------------------------------------------
# State field schema
# ---------------------------------------------------------------------------


class StateFieldSchema(BaseModel):
    """Describes a single field in the graph's state.

    Example::

        StateFieldSchema(
            name="intent",
            field_type=StateFieldType.STRING,
            description="Classified user intent",
            default=None,
        )
    """

    name: str = Field(..., min_length=1, description="Unique field name")
    field_type: StateFieldType = Field(
        default=StateFieldType.ANY,
        description="Data type of the field",
    )
    description: Optional[str] = Field(
        default=None,
        description="Human-readable description",
    )
    default: Any = Field(
        default=None,
        description="Default value when not set",
    )
    reducer: ReducerType = Field(
        default=ReducerType.REPLACE,
        description="Reducer function for concurrent/partial updates",
    )
    required: bool = Field(
        default=False,
        description="Whether the field must be present in initial state",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.isidentifier():
            raise ValueError(f"State field name must be a valid Python identifier, got: {v!r}")
        return v


# ---------------------------------------------------------------------------
# Node schema
# ---------------------------------------------------------------------------


class NodeSchema(BaseModel):
    """Describes a single node in the graph.

    ``reads`` and ``writes`` declare which state fields the node accesses.
    A value of ``["*"]`` means "all fields" (wildcard) — this is the default
    for backward compatibility with existing nodes.
    """

    id: str = Field(..., description="Unique node identifier (typically a UUID string)")
    type: str = Field(..., min_length=1, description="Node type key, e.g. 'agent', 'condition'")
    label: str = Field(default="", description="Display label")
    config: Dict[str, Any] = Field(default_factory=dict, description="Node configuration")
    position: Optional[Dict[str, float]] = Field(
        default=None,
        description="Canvas position {x, y}",
    )
    reads: List[str] = Field(
        default_factory=lambda: ["*"],
        description="State fields this node reads",
    )
    writes: List[str] = Field(
        default_factory=lambda: ["*"],
        description="State fields this node writes",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata (prompt, tools, LLM settings, etc.)",
    )

    # -- HiL (Human-in-the-Loop) -------------------------------------------
    interrupt_before: bool = Field(default=False)
    interrupt_after: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Edge schema
# ---------------------------------------------------------------------------


class EdgeSchema(BaseModel):
    """Describes an edge between two nodes."""

    source: str = Field(..., description="Source node id")
    target: str = Field(..., description="Target node id")
    edge_type: EdgeType = Field(default=EdgeType.NORMAL)
    route_key: Optional[str] = Field(
        default=None,
        description="Route key for conditional edges",
    )
    source_handle_id: Optional[str] = Field(
        default=None,
        description="React Flow source handle ID",
    )
    label: Optional[str] = Field(default=None, description="Display label")
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional edge metadata (waypoints, offsets, etc.)",
    )


# ---------------------------------------------------------------------------
# Graph schema (top-level)
# ---------------------------------------------------------------------------


class GraphSchema(BaseModel):
    """Complete, serializable description of a graph.

    This is the **single source of truth**.  A ``GraphSchema`` can be:

    * Persisted as JSON
    * Used to compile a LangGraph ``StateGraph``
    * Used to generate standalone Python code
    * Versioned for deployment snapshots
    """

    # -- Identity -----------------------------------------------------------
    name: str = Field(default="Untitled Graph")
    description: Optional[str] = Field(default=None)
    version: str = Field(default="1.0.0")

    # -- State definition ---------------------------------------------------
    state_fields: List[StateFieldSchema] = Field(
        default_factory=list,
        description="Custom state fields defined by the user",
    )
    use_default_state: bool = Field(
        default=True,
        description="If True, extend the built-in GraphState; otherwise use only custom fields",
    )

    # -- Graph structure ----------------------------------------------------
    nodes: List[NodeSchema] = Field(default_factory=list)
    edges: List[EdgeSchema] = Field(default_factory=list)
    fallback_node_id: Optional[str] = Field(
        default=None,
        description="Node ID to jump to if an unhandled exception occurs in any node",
    )

    # -- Metadata -----------------------------------------------------------
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata (color, variables, etc.)",
    )
    created_at: Optional[datetime] = Field(default=None)
    updated_at: Optional[datetime] = Field(default=None)

    # -----------------------------------------------------------------------
    # Validators
    # -----------------------------------------------------------------------

    @model_validator(mode="after")
    def validate_edge_references(self) -> "GraphSchema":
        """Ensure every edge references existing nodes."""
        node_ids: Set[str] = {n.id for n in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids:
                raise ValueError(f"Edge references unknown source node: {edge.source!r}")
            if edge.target not in node_ids:
                raise ValueError(f"Edge references unknown target node: {edge.target!r}")

        if self.fallback_node_id and self.fallback_node_id not in node_ids:
            raise ValueError(f"Fallback node ID {self.fallback_node_id!r} not found in nodes")

        return self

    @model_validator(mode="after")
    def validate_unique_state_field_names(self) -> "GraphSchema":
        """State field names must be unique."""
        names = [f.name for f in self.state_fields]
        if len(names) != len(set(names)):
            dupes = [n for n in names if names.count(n) > 1]
            raise ValueError(f"Duplicate state field names: {set(dupes)}")
        return self

    # -----------------------------------------------------------------------
    # Factory: DB models → Schema
    # -----------------------------------------------------------------------

    @classmethod
    def from_db(
        cls,
        graph: Any,
        nodes: List[Any],
        edges: List[Any],
    ) -> "GraphSchema":
        """Convert SQLAlchemy DB models to a ``GraphSchema``.

        Parameters
        ----------
        graph : AgentGraph
            The graph model instance.
        nodes : list[GraphNode]
            Node model instances belonging to *graph*.
        edges : list[GraphEdge]
            Edge model instances belonging to *graph*.
        """
        node_schemas: List[NodeSchema] = []
        for n in nodes:
            data = n.data or {}
            config = data.get("config", {})
            node_type = data.get("type") or n.type or "agent"
            label = data.get("label") or data.get("name") or node_type

            node_schemas.append(
                NodeSchema(
                    id=str(n.id),
                    type=node_type,
                    label=label,
                    config=config,
                    position={"x": float(n.position_x), "y": float(n.position_y)},
                    reads=config.get("reads", ["*"]),
                    writes=config.get("writes", ["*"]),
                    metadata={
                        "prompt": n.prompt,
                        "tools": n.tools,
                        "memory": n.memory,
                        "width": float(n.width) if n.width else None,
                        "height": float(n.height) if n.height else None,
                    },
                    interrupt_before=config.get("interrupt_before", False),
                    interrupt_after=config.get("interrupt_after", False),
                )
            )

        edge_schemas: List[EdgeSchema] = []
        for e in edges:
            e_data = e.data or {}
            edge_type_str = e_data.get("edge_type", "normal")
            try:
                edge_type = EdgeType(edge_type_str)
            except ValueError:
                edge_type = EdgeType.NORMAL

            edge_schemas.append(
                EdgeSchema(
                    source=str(e.source_node_id),
                    target=str(e.target_node_id),
                    edge_type=edge_type,
                    route_key=e_data.get("route_key"),
                    source_handle_id=e_data.get("source_handle_id"),
                    label=e_data.get("label"),
                    data={
                        k: v
                        for k, v in e_data.items()
                        if k
                        not in {
                            "edge_type",
                            "route_key",
                            "source_handle_id",
                            "label",
                            "condition",
                        }
                    },
                )
            )

        # Extract custom state fields from graph variables (if present)
        variables = getattr(graph, "variables", {}) or {}
        state_field_defs = variables.get("state_fields", [])
        state_fields = []
        for sf in state_field_defs:
            try:
                state_fields.append(StateFieldSchema(**sf))
            except Exception:
                pass  # Skip malformed definitions

        return cls(
            name=getattr(graph, "name", "Untitled Graph"),
            description=getattr(graph, "description", None),
            state_fields=state_fields,
            use_default_state=True,
            nodes=node_schemas,
            edges=edge_schemas,
            metadata={
                "graph_id": str(graph.id) if hasattr(graph, "id") else None,
                "color": getattr(graph, "color", None),
                "variables": variables,
            },
            created_at=getattr(graph, "created_at", None),
            updated_at=getattr(graph, "updated_at", None),
        )

    # -----------------------------------------------------------------------
    # Convenience helpers
    # -----------------------------------------------------------------------

    def get_node_by_id(self, node_id: str) -> Optional[NodeSchema]:
        """Look up a node by its ID."""
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def get_node_ids(self) -> Set[str]:
        return {n.id for n in self.nodes}

    def get_edges_from(self, node_id: str) -> List[EdgeSchema]:
        """Return all edges originating from *node_id*."""
        return [e for e in self.edges if e.source == node_id]

    def get_edges_to(self, node_id: str) -> List[EdgeSchema]:
        """Return all edges targeting *node_id*."""
        return [e for e in self.edges if e.target == node_id]

    def get_start_nodes(self) -> List[NodeSchema]:
        """Nodes with no incoming edges (except loop-back edges)."""
        targets = {e.target for e in self.edges if e.edge_type != EdgeType.LOOP_BACK}
        return [n for n in self.nodes if n.id not in targets]

    def get_end_nodes(self) -> List[NodeSchema]:
        """Nodes with no outgoing edges."""
        sources = {e.source for e in self.edges}
        return [n for n in self.nodes if n.id not in sources]

    def get_conditional_node_ids(self) -> Set[str]:
        """Node IDs that have conditional or loop-back outgoing edges."""
        return {e.source for e in self.edges if e.edge_type in (EdgeType.CONDITIONAL, EdgeType.LOOP_BACK)}

    def get_state_field_names(self) -> Set[str]:
        """Return all custom state field names."""
        return {f.name for f in self.state_fields}

    def validate_state_dependencies(self) -> List[str]:
        """Check that every node's reads/writes reference declared state fields.

        Returns a list of warning messages (empty if everything is fine).
        Nodes with wildcard ``["*"]`` are always valid.
        """
        warnings: List[str] = []
        if not self.state_fields:
            return warnings  # No custom fields → nothing to check

        declared = self.get_state_field_names()
        for node in self.nodes:
            for direction, fields in [("reads", node.reads), ("writes", node.writes)]:
                if fields == ["*"]:
                    continue
                for f in fields:
                    if f not in declared:
                        warnings.append(f"Node '{node.label}' ({node.id}) {direction} " f"undeclared state field '{f}'")
        return warnings
