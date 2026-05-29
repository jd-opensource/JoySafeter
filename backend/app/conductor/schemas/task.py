import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class CreateTaskRequest(BaseModel):
    agent_id: Optional[uuid.UUID] = None
    agent_name: Optional[str] = None
    prompt: str
    system_prompt: Optional[str] = None
    chat_session_id: Optional[uuid.UUID] = None
    environment_ref: Optional[str] = None
    timeout_sec: int = Field(default=7200, ge=1)
    max_retries: int = Field(default=2, ge=0)


class CreateTaskResponse(BaseModel):
    id: uuid.UUID
    status: str


class TaskResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    chat_session_id: Optional[uuid.UUID] = None
    status: str
    prompt: str
    system_prompt: Optional[str] = None
    sandbox_id: Optional[uuid.UUID] = None
    output: str = ""
    error: Optional[str] = None
    usage: Optional[dict] = None
    timeout_sec: int
    retry_count: int
    max_retries: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"task_{v}"
