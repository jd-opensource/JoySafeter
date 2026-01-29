"""
Pydantic models for Task Execution Tracking.

This module defines the data models used for task execution tracking,
including Task, ExecutionStep, and related schemas.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Task execution status."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ExecutionStepStatus(str, Enum):
    """Execution step status."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ExecutionStepType(str, Enum):
    """Type of execution step."""

    TOOL = "TOOL"
    AGENT = "AGENT"
    CHAIN = "CHAIN"
    THOUGHT = "THOUGHT"
    LLM = "LLM"


class ExecutionStepBase(BaseModel):
    """Base model for ExecutionStep."""

    step_type: ExecutionStepType
    name: str = Field(..., min_length=1, max_length=255)
    input_data: dict = Field(default_factory=dict)
    output_data: Optional[dict] = None
    status: ExecutionStepStatus = ExecutionStepStatus.RUNNING
    error_message: Optional[str] = None
    agent_trace: Optional[dict] = None


class ExecutionStepCreate(ExecutionStepBase):
    """Model for creating an ExecutionStep."""

    task_id: UUID
    start_time: datetime = Field(default_factory=datetime.utcnow)


class ExecutionStepUpdate(BaseModel):
    """Model for updating an ExecutionStep."""

    status: Optional[ExecutionStepStatus] = None
    output_data: Optional[dict] = None
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None


class ExecutionStepResponse(ExecutionStepBase):
    """Response model for ExecutionStep."""

    id: UUID
    task_id: UUID
    parent_step_id: Optional[UUID] = None  # Parent step ID for step hierarchy
    start_time: datetime
    end_time: Optional[datetime] = None
    created_at: datetime
    children: List["ExecutionStepResponse"] = Field(default_factory=list)  # Nested children for tree structure

    class Config:
        """Pydantic config."""

        from_attributes = True


class TaskBase(BaseModel):
    """Base model for Task."""

    user_input: str = Field(..., min_length=1)
    status: TaskStatus = TaskStatus.PENDING
    result_summary: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    message_id: Optional[int] = None
    parent_id: Optional[UUID] = None  # Parent task ID for subtasks
    created_by_step_id: Optional[UUID] = None  # Step that created this task (for agent_tool)
    level: int = 1  # Task hierarchy level (1 = root, 2 = child, 3 = grandchild, etc.)


class TaskCreate(TaskBase):
    """Model for creating a Task."""

    session_id: UUID


class TaskUpdate(BaseModel):
    """Model for updating a Task."""

    status: Optional[TaskStatus] = None
    result_summary: Optional[str] = None
    completed_at: Optional[datetime] = None


class TaskResponse(TaskBase):
    """Response model for Task."""

    id: UUID
    parent_id: Optional[UUID] = None  # Parent task ID for subtasks
    session_id: UUID
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        """Pydantic config."""

        from_attributes = True


class TaskWithStepsResponse(TaskResponse):
    """Response model for Task with all execution steps."""

    steps: List[ExecutionStepResponse] = Field(default_factory=list)


# Update forward references
ExecutionStepResponse.model_rebuild()
