# backend/app/core/observation/model.py
"""Trace and Observation persistence models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.joysafeter_shared.database import Base


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="running")

    input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    meta: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    environment: Mapped[str] = mapped_column(String(50), server_default="debug")
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), server_default="{}")
    release: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bookmarked: Mapped[bool] = mapped_column(Boolean, server_default="false")
    public: Mapped[bool] = mapped_column(Boolean, server_default="false")

    total_observations: Mapped[int] = mapped_column(Integer, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("traces.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_observation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False, server_default="DEFAULT")
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    environment: Mapped[str] = mapped_column(String(50), server_default="debug")

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    meta: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_parameters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    usage_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cost_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    prompt_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    tool_definitions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_calls: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
