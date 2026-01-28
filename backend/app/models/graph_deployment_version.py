"""
Graph 部署版本模型
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .graph import AgentGraph


def utc_now():
    return datetime.now(timezone.utc)


class GraphDeploymentVersion(BaseModel):
    """Agent Graph 部署版本

    - 每次部署创建新版本，版本号自动递增
    - 同时只有一个活跃版本 (is_active=True)
    - 存储完整的图状态快照 (nodes + edges + variables)
    """

    __tablename__ = "graph_deployment_version"

    graph_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("graphs.id", ondelete="CASCADE"),
        nullable=False,
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False)

    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    state: Mapped[dict] = mapped_column(JSONB, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    graph: Mapped["AgentGraph"] = relationship(
        "AgentGraph",
        back_populates="deployment_versions",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("graph_id", "version", name="graph_deployment_version_graph_version_unique"),
        Index("graph_deployment_version_graph_active_idx", "graph_id", "is_active"),
        Index("graph_deployment_version_created_at_idx", "created_at"),
    )
