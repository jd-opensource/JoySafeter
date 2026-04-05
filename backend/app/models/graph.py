"""
Graph models
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel, SoftDeleteMixin

if TYPE_CHECKING:
    from .auth import AuthUser
    from .graph_deployment_version import GraphDeploymentVersion
    from .graph_test import GraphTestCase
    from .workspace import Workspace, WorkspaceFolder


def utc_now():
    return datetime.now(timezone.utc)


class AgentGraph(BaseModel, SoftDeleteMixin):
    """Agent graph model (supports soft-delete)."""

    __tablename__ = "graphs"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    user_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    folder_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_folder.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("graphs.id", ondelete="SET NULL"),
        nullable=True,
    )
    color: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    is_deployed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # deployment fields — correspond to the sim project's workflow table
    deployed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # relationships
    user: Mapped["AuthUser"] = relationship("AuthUser", lazy="selectin")
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace", lazy="selectin")
    folder: Mapped[Optional["WorkspaceFolder"]] = relationship(
        "WorkspaceFolder",
        lazy="selectin",
    )
    parent: Mapped[Optional["AgentGraph"]] = relationship(
        "AgentGraph",
        remote_side="AgentGraph.id",
        lazy="selectin",
    )
    nodes: Mapped[List["GraphNode"]] = relationship(
        "GraphNode",
        back_populates="graph",
        cascade="all, delete-orphan",
    )
    edges: Mapped[List["GraphEdge"]] = relationship(
        "GraphEdge",
        back_populates="graph",
        cascade="all, delete-orphan",
    )
    deployment_versions: Mapped[List["GraphDeploymentVersion"]] = relationship(
        "GraphDeploymentVersion",
        back_populates="graph",
        cascade="all, delete-orphan",
        order_by="GraphDeploymentVersion.version.desc()",
    )
    test_cases: Mapped[List["GraphTestCase"]] = relationship(
        "GraphTestCase",
        back_populates="graph",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("graphs_user_id_idx", "user_id"),
        Index("graphs_workspace_id_idx", "workspace_id"),
        Index("graphs_folder_id_idx", "folder_id"),
        Index("graphs_parent_id_idx", "parent_id"),
    )


class GraphNode(BaseModel):
    """Graph node model."""

    __tablename__ = "graph_nodes"

    graph_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("graphs.id", ondelete="CASCADE"),
        nullable=False,
    )
    position_x: Mapped[float] = mapped_column(Numeric, nullable=False)
    position_y: Mapped[float] = mapped_column(Numeric, nullable=False)
    position_absolute_x: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    position_absolute_y: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    width: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)
    height: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    type: Mapped[str] = mapped_column(String(50), nullable=False)

    # relationship
    graph: Mapped["AgentGraph"] = relationship("AgentGraph", back_populates="nodes", lazy="selectin")
    source_edges: Mapped[List["GraphEdge"]] = relationship(
        "GraphEdge",
        foreign_keys="GraphEdge.source_node_id",
        back_populates="source_node",
        cascade="all, delete-orphan",
    )
    target_edges: Mapped[List["GraphEdge"]] = relationship(
        "GraphEdge",
        foreign_keys="GraphEdge.target_node_id",
        back_populates="target_node",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("graph_nodes_graph_id_idx", "graph_id"),
        Index("graph_nodes_type_idx", "type"),
    )


class GraphEdge(BaseModel):
    """Graph edge model.

    Support conditional routing and complex flow patterns:
    - data.route_key: routing key for conditional routing (maps to RouterNodeExecutor return value)
    - data.source_handle_id: React Flow Handle ID (e.g. "Yes", "No", "Unknown")
    - data.condition_expression: edge-level condition expression (optional)
    - data.edge_type: edge type ("normal" | "conditional" | "loop_back") to distinguish edge kinds
    - data.label: display label for the edge (optional), used for logging and debugging
    """

    __tablename__ = "graph_edges"

    graph_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("graphs.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    # edge metadata storing routing info
    # structure: { "route_key": str, "source_handle_id": str, "condition_expression": str }
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # relationships
    graph: Mapped["AgentGraph"] = relationship("AgentGraph", back_populates="edges", lazy="selectin")
    source_node: Mapped["GraphNode"] = relationship(
        "GraphNode",
        foreign_keys=[source_node_id],
        back_populates="source_edges",
        lazy="selectin",
    )
    target_node: Mapped["GraphNode"] = relationship(
        "GraphNode",
        foreign_keys=[target_node_id],
        back_populates="target_edges",
        lazy="selectin",
    )

    __table_args__ = (
        Index("graph_edges_graph_id_idx", "graph_id"),
        Index("graph_edges_source_node_id_idx", "source_node_id"),
        Index("graph_edges_target_node_id_idx", "target_node_id"),
        Index("graph_edges_graph_source_idx", "graph_id", "source_node_id"),
        Index("graph_edges_graph_target_idx", "graph_id", "target_node_id"),
    )


class GraphNodeSecret(BaseModel):
    """Encrypted secrets for graph nodes (e.g. a2a_auth_headers). Not stored in node.data JSONB."""

    __tablename__ = "graph_node_secrets"

    graph_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("graphs.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    key_slug: Mapped[str] = mapped_column(String(64), nullable=False, default="a2a_auth_headers")
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("graph_node_secrets_graph_node_idx", "graph_id", "node_id"),)
