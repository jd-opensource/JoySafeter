from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_domain.models.base import JoySafeterModel
from app.joysafeter_shared.ids import EnvironmentId, ProjectId
from app.joysafeter_shared.sqlalchemy_ids import EntityIdType


class JoySafeterEnvironment(JoySafeterModel):
    __tablename__ = "joysafeter_environments"
    __table_args__ = (
        Index(
            "uq_joysafeter_environments_project_name",
            "project_id",
            "name",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL AND deleted_at IS NULL"),
            sqlite_where=text("project_id IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index(
            "uq_joysafeter_environments_global_name",
            "name",
            unique=True,
            postgresql_where=text("project_id IS NULL AND deleted_at IS NULL"),
            sqlite_where=text("project_id IS NULL AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[EnvironmentId] = mapped_column(  # type: ignore[assignment]
        EntityIdType(EnvironmentId), primary_key=True
    )

    project_id: Mapped[Optional[ProjectId]] = mapped_column(
        EntityIdType(ProjectId),
        ForeignKey("joysafeter_organization_projects.id"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    image_tag: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
