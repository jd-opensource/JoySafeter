"""
Pydantic schemas for Sandbox API (JoySafeter).
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.joysafeter_shared.ids import SessionId
from app.joysafeter_shared.utils.id_utils import format_task_id


class SandboxStatus(str, Enum):
    CREATING = "creating"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    IDLE = "idle"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    DESTROYED = "destroyed"
    POOLED = "pooled"


class SandboxProvisionStatus(BaseModel):
    stage: str = ""
    progress: int = 0
    message: str = ""
    complete: bool = False
    error: bool = False
    error_message: Optional[str] = None


class MemoryMount(BaseModel):
    store_id: uuid.UUID
    mount_name: str
    host_path: str
    access: str = "read_write"


class SandboxConfig(BaseModel):
    image: str
    env: dict[str, str] = Field(default_factory=dict)
    cpu: Optional[float] = None
    memory_mb: Optional[int] = None
    disk_mb: Optional[int] = None
    timeout: int = 7200
    workspace_host_path: Optional[str] = None
    networking: Optional[dict] = None
    memory_mounts: list[MemoryMount] = Field(default_factory=list)


class SandboxResponse(BaseModel):
    id: uuid.UUID
    external_id: str = ""
    provider: str
    status: str
    config: dict[str, Any] = Field(default_factory=dict)
    chat_session_id: Optional[SessionId] = None
    image: str
    last_task_id: Optional[uuid.UUID] = None
    last_used_at: datetime
    created_at: datetime
    destroyed_at: Optional[datetime] = None
    workspace_path: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("last_task_id")
    def serialize_last_task_id(self, value: Optional[uuid.UUID]) -> Optional[str]:
        return format_task_id(value) if value is not None else None
