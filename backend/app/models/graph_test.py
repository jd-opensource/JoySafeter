"""
Graph Unit Test Model
"""

import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .graph import AgentGraph


class GraphTestCase(BaseModel):
    """
    Unit Test Case for Agent Graph.

    Stores input/expected-output pairs to verify graph behavior.
    """

    __tablename__ = "graph_test_cases"

    graph_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("graphs.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Validation inputs
    inputs: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Expected outputs (subset match)
    expected_outputs: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Advanced assertions (e.g., [{"path": "agent.response", "operator": "contains", "value": "hello"}])
    assertions: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    # Relationships
    graph: Mapped["AgentGraph"] = relationship("AgentGraph", back_populates="test_cases")

    def __repr__(self) -> str:
        return f"<GraphTestCase(id={self.id}, name={self.name}, graph_id={self.graph_id})>"
