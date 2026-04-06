"""
Execution trace model

Modeled after Langfuse Trace / Observation for persisting LangGraph execution data.
Support hierarchical observations via parent_observation_id self-reference.
"""

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.utils.datetime import utc_now

# ============ Enums ============


class TraceStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class ObservationType(str, enum.Enum):
    SPAN = "SPAN"  # Node execution (wraps children)
    GENERATION = "GENERATION"  # LLM call
    TOOL = "TOOL"  # Tool invocation
    EVENT = "EVENT"  # Singular events (thoughts, logs)


class ObservationLevel(str, enum.Enum):
    DEBUG = "DEBUG"
    DEFAULT = "DEFAULT"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ObservationStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


# ============ ExecutionTrace ============


class ExecutionTrace(Base):
    """
    Execution trace table -- represents a single complete Graph execution.
    Analogous to a Langfuse Trace.
    """

    __tablename__ = "execution_traces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # associations
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True, comment="workspace ID"
    )
    graph_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True, comment="Graph ID"
    )
    thread_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True, comment="conversation thread ID"
    )
    user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True, comment="user ID")

    # basic info
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="Graph / Trace name")
    status: Mapped[TraceStatus] = mapped_column(
        Enum(TraceStatus), default=TraceStatus.RUNNING, nullable=False, comment="execution status"
    )

    # input / output
    input: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="execution input")
    output: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="execution output")

    # timing
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, comment="start time"
    )
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="end time")
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="duration in milliseconds")

    # token / cost aggregates
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="total token count")
    total_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="total cost")

    # metadata
    metadata_: Mapped[Optional[dict]] = mapped_column(
        "metadata", JSON, nullable=True, comment="custom metadata (tags, etc.)"
    )
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, comment="tag list")

    # timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), onupdate=utc_now, nullable=False
    )

    # relationship
    observations: Mapped[list["ExecutionObservation"]] = relationship(
        "ExecutionObservation",
        back_populates="trace",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="noload",
    )

    __table_args__ = (
        Index("ix_execution_traces_graph_thread", "graph_id", "thread_id"),
        Index("ix_execution_traces_start_time", "start_time"),
    )

    def __repr__(self) -> str:
        return f"<ExecutionTrace(id={self.id}, name={self.name}, status={self.status})>"


# ============ ExecutionObservation ============


class ExecutionObservation(Base):
    """
    Execution observation table -- represents a single Observation (Span / Generation / Tool / Event).
    Support N-level nesting via parent_observation_id.
    Analogous to a Langfuse Observation.
    """

    __tablename__ = "execution_observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # associations
    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_traces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="foreign key to execution trace",
    )
    parent_observation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_observations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="parent observation ID (hierarchical nesting)",
    )

    # type and identity
    type: Mapped[ObservationType] = mapped_column(Enum(ObservationType), nullable=False, comment="observation type")
    name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="name (node name, tool name, model name)"
    )
    level: Mapped[ObservationLevel] = mapped_column(
        Enum(ObservationLevel), default=ObservationLevel.DEFAULT, nullable=False, comment="log level"
    )
    status: Mapped[ObservationStatus] = mapped_column(
        Enum(ObservationStatus), default=ObservationStatus.RUNNING, nullable=False, comment="execution status"
    )
    status_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="status / error message")

    # timing
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, comment="start time"
    )
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="end time")
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="duration in milliseconds")
    completion_start_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="time to first token (GENERATION)"
    )

    # input / output
    input: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="input data")
    output: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="output data")

    # model info (GENERATION type)
    model_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="model name")
    model_provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="model provider")
    model_parameters: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="model parameters (temperature, etc.)"
    )

    # token usage
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="prompt token count")
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="completion token count")
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="total token count")

    # cost
    input_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="input cost")
    output_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="output cost")
    total_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="total cost")

    # metadata
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True, comment="custom metadata")
    version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="code / model version")

    # timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )

    # relationships
    trace: Mapped["ExecutionTrace"] = relationship(
        "ExecutionTrace",
        back_populates="observations",
        lazy="raise",
    )
    children: Mapped[list["ExecutionObservation"]] = relationship(
        "ExecutionObservation",
        back_populates="parent",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="noload",
    )
    parent: Mapped[Optional["ExecutionObservation"]] = relationship(
        "ExecutionObservation",
        back_populates="children",
        remote_side=[id],
        lazy="noload",
    )

    __table_args__ = (
        Index("ix_execution_observations_trace_start", "trace_id", "start_time"),
        Index("ix_execution_observations_type", "type"),
    )

    def __repr__(self) -> str:
        return f"<ExecutionObservation(id={self.id}, type={self.type}, name={self.name})>"
