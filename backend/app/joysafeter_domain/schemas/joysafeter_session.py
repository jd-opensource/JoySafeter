"""Pydantic schemas for the JoySafeter Session API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

from app.joysafeter_domain.schemas.joysafeter_agent import JoySafeterModelConfig
from app.joysafeter_domain.schemas.joysafeter_credential import ModelCredentialSummary
from app.joysafeter_domain.schemas.joysafeter_environment import MountResource
from app.joysafeter_shared.ids import (
    AgentId,
    CredentialGroupId,
    CredentialId,
    EventId,
    FileId,
    MemoryStoreId,
    SessionId,
    SessionResourceId,
    StorageVolumeId,
)
from app.joysafeter_shared.utils.datetime import utc_now

# ---------------------------------------------------------------------------
# JoySafeter Session Schemas
# ---------------------------------------------------------------------------


class ModelUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class SessionUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    by_model: dict[str, ModelUsage] = Field(default_factory=dict)


class SessionStats(BaseModel):
    active_seconds: Optional[float] = None
    duration_seconds: Optional[float] = None


class SessionAgent(BaseModel):
    type: str = "agent"
    id: AgentId
    version: int
    name: str
    engine_kind: Optional[str] = None
    description: Optional[str] = None
    model: Optional[JoySafeterModelConfig] = None
    system: Optional[str] = None
    tools: list[Dict[str, Any]] = Field(default_factory=list)
    skills: list[Dict[str, Any]] = Field(default_factory=list)
    mcp_servers: list[Dict[str, Any]] = Field(default_factory=list)
    multiagent: Optional[Dict[str, Any]] = None
    model_credential_id: Optional[CredentialId] = None
    model_connection: Optional[ModelCredentialSummary] = None

    @classmethod
    def from_agent(cls, agent) -> "SessionAgent":
        model = agent.model
        if isinstance(model, str):
            model = JoySafeterModelConfig(id=model)
        return cls(
            id=agent.id,
            version=agent.version,
            name=agent.name,
            engine_kind=getattr(agent, "engine_kind", None),
            description=agent.description,
            model=model,
            system=agent.system_prompt,
            tools=agent.tools or [],
            skills=agent.skills or [],
            mcp_servers=agent.mcp_servers or [],
            multiagent=agent.multiagent,
            model_credential_id=getattr(agent, "model_credential_id", None),
        )


class ContentBlock(BaseModel):
    type: Literal["text", "image", "document"]
    text: Optional[str] = None
    source: Optional[Dict[str, Any]] = None

    @classmethod
    def text_block(cls, text: str) -> "ContentBlock":
        return cls(type="text", text=text)


class EndTurnStopReason(BaseModel):
    type: Literal["end_turn"] = "end_turn"


class RequiresActionStopReason(BaseModel):
    type: Literal["requires_action"] = "requires_action"
    event_ids: list[str] = Field(default_factory=list)


class RetriesExhaustedStopReason(BaseModel):
    type: Literal["retries_exhausted"] = "retries_exhausted"


class InterruptedStopReason(BaseModel):
    type: Literal["interrupted"] = "interrupted"


class ErrorStopReason(BaseModel):
    type: Literal["error"] = "error"
    code: str = "UNKNOWN_ERROR"
    message: str
    data: Optional[Dict[str, Any]] = None
    source: str = "internal"
    retryable: bool = False
    user_action: Optional[str] = None
    detail: Optional[str] = None


class TimeoutStopReason(BaseModel):
    type: Literal["timeout"] = "timeout"


class CancelledStopReason(BaseModel):
    type: Literal["cancelled"] = "cancelled"


class SandboxDisconnectedStopReason(BaseModel):
    type: Literal["sandbox_disconnected"] = "sandbox_disconnected"


class SandboxFailedStopReason(BaseModel):
    type: Literal["sandbox_failed"] = "sandbox_failed"


StopReason = Union[
    EndTurnStopReason,
    RequiresActionStopReason,
    RetriesExhaustedStopReason,
    InterruptedStopReason,
    ErrorStopReason,
    TimeoutStopReason,
    CancelledStopReason,
    SandboxDisconnectedStopReason,
    SandboxFailedStopReason,
]


class AgentRef(BaseModel):
    """Agent reference supporting pinned versions: {type, id, version}."""

    type: str = "agent"
    id: AgentId
    version: Optional[int] = None


class SessionResourceRequest(BaseModel):
    memory_store_id: MemoryStoreId
    access: str = "read_write"
    instructions: Optional[str] = None
    mount_name: Optional[str] = None


class SessionFileResourceRequest(BaseModel):
    type: str = "file"
    file_id: FileId
    mount_path: Optional[str] = None

    @model_validator(mode="after")
    def validate_mount_path(self):
        if self.mount_path:
            import os

            normalized = os.path.normpath(self.mount_path)
            if ".." in normalized.split("/") or ".." in normalized.split("\\"):
                raise ValueError("mount_path must not contain path traversal")
            if not normalized.startswith("/workspace"):
                raise ValueError("mount_path must be under /workspace/")
            self.mount_path = normalized
        return self


class SessionRepoResourceRequest(BaseModel):
    """A git repository to clone into the sandbox — mirrors the official
    ``github_repository`` session resource. ``authorization_token`` is a
    clone-only credential, stored encrypted and never echoed in responses."""

    type: str = "github_repository"
    url: str
    branch: Optional[str] = None
    mount_path: Optional[str] = None
    mount_name: Optional[str] = None
    authorization_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None

    @field_validator("url", "authorization_token")
    @classmethod
    def trim_config_value(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v is not None else v

    @model_validator(mode="after")
    def validate_token_expiry(self):
        if self.token_expires_at is not None and not self.authorization_token:
            raise ValueError("token_expires_at requires authorization_token")
        if self.token_expires_at is not None and self.token_expires_at.utcoffset() is None:
            raise ValueError("token_expires_at must include a timezone")
        if self.token_expires_at is not None and self.token_expires_at <= utc_now():
            raise ValueError("token_expires_at must be in the future")
        return self

    @model_validator(mode="after")
    def validate_mount_path(self):
        if self.mount_path:
            import os

            normalized = os.path.normpath(self.mount_path)
            if ".." in normalized.split("/") or ".." in normalized.split("\\"):
                raise ValueError("mount_path must not contain path traversal")
            if not normalized.startswith("/workspace"):
                raise ValueError("mount_path must be under /workspace/")
            self.mount_path = normalized
        return self


class SessionStorageMountRequest(MountResource):
    type: str = "storage"


MAX_MEMORY_STORE_RESOURCES = 8
MAX_FILE_RESOURCES = 100
MAX_REPO_RESOURCES = 16
MAX_STORAGE_MOUNT_RESOURCES = 16


class CreateSessionRequest(BaseModel):
    agent: AgentRef | None = None
    agent_id: Optional[AgentId] = None
    agent_name: Optional[str] = None
    title: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    credential_group_ids: list[CredentialGroupId] = Field(default_factory=list)
    environment_id: Optional[str] = None
    resources: list[SessionResourceRequest] = Field(default_factory=list)
    file_resources: list[SessionFileResourceRequest] = Field(default_factory=list)
    repo_resources: list[SessionRepoResourceRequest] = Field(default_factory=list)
    storage_mounts: list[SessionStorageMountRequest] = Field(default_factory=list)

    @field_validator("metadata")
    @classmethod
    def reject_reserved_internal_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        if "agent_identity_context" in value:
            raise ValueError("metadata.agent_identity_context is reserved for internal use")
        return value

    @model_validator(mode="before")
    @classmethod
    def coerce_agent_string(cls, data: Any) -> Any:
        if isinstance(data, dict):
            agent = data.get("agent")
            if isinstance(agent, str):
                data["agent_id"] = agent
                data["agent"] = None
        return data


class SessionResourceResponse(BaseModel):
    memory_store_id: MemoryStoreId
    access: str = "read_write"
    instructions: Optional[str] = None
    mount_name: str = ""


class SessionRepoResourceResponse(BaseModel):
    """Repo resource as returned by the API. Deliberately omits the
    ``authorization_token`` — clone credentials are never echoed."""

    id: SessionResourceId
    type: str = "github_repository"
    url: str
    branch: str = ""
    mount_path: str = ""
    mount_name: str = ""
    has_authorization_token: bool
    token_status: Literal["none", "active", "expired", "erased"]
    token_expires_at: Optional[datetime] = None
    token_rotated_at: Optional[datetime] = None
    token_erased_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SessionFileResourceResponse(BaseModel):
    id: SessionResourceId
    type: str = "file"
    file_id: FileId
    mount_path: str
    access: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionStorageMountResponse(BaseModel):
    id: SessionResourceId
    type: str = "storage"
    name: str
    volume_ref: str
    volume_id: StorageVolumeId
    sub_path: str = ""
    mount_path: str
    access: str
    required: bool = True
    created_at: datetime


class UpdateRepoResourceRequest(BaseModel):
    """Rotate the clone credential on a github_repository resource."""

    authorization_token: str
    token_expires_at: Optional[datetime] = None

    @field_validator("authorization_token")
    @classmethod
    def trim_authorization_token(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_token_expiry(self):
        if self.token_expires_at is not None and not self.authorization_token:
            raise ValueError("token_expires_at requires authorization_token")
        if self.token_expires_at is not None and self.token_expires_at.utcoffset() is None:
            raise ValueError("token_expires_at must include a timezone")
        if self.token_expires_at is not None and self.token_expires_at <= utc_now():
            raise ValueError("token_expires_at must be in the future")
        return self


class SessionResponse(BaseModel):
    id: SessionId
    type: str = "session"
    agent: SessionAgent
    environment_id: Optional[str] = None
    status: str
    stop_reason: Optional[Dict[str, Any]] = None
    title: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    credential_group_ids: list[CredentialGroupId] = Field(default_factory=list)
    resources: list[SessionResourceResponse] = Field(default_factory=list)
    repo_resources: list[SessionRepoResourceResponse] = Field(default_factory=list)
    storage_mounts: list[SessionStorageMountResponse] = Field(default_factory=list)
    usage: SessionUsage = Field(default_factory=SessionUsage)
    stats: SessionStats = Field(default_factory=SessionStats)
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SingleEventRequest(BaseModel):
    type: str
    content: Optional[Union[str, list[Any]]] = None
    tool_use_id: Optional[str] = None
    custom_tool_use_id: Optional[str] = None
    tool_use_event_id: Optional[str] = None
    result: Optional[str] = None
    approved: Optional[bool] = None
    deny_message: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

    def resolved_tool_use_id(self) -> Optional[str]:
        return self.tool_use_id or self.custom_tool_use_id or self.tool_use_event_id

    def resolved_approved(self) -> Optional[bool]:
        if self.result is not None:
            return self.result == "allow"
        return self.approved


class SendEventRequest(BaseModel):
    type: Optional[str] = None
    events: Optional[list[SingleEventRequest]] = None
    content: Optional[Union[str, list[Any]]] = None
    tool_use_id: Optional[str] = None
    custom_tool_use_id: Optional[str] = None
    tool_use_event_id: Optional[str] = None
    result: Optional[str] = None
    approved: Optional[bool] = None
    deny_message: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

    def to_single_events(self) -> list[SingleEventRequest]:
        if self.events:
            return self.events
        if self.type:
            return [
                SingleEventRequest(
                    type=self.type,
                    content=self.content,
                    tool_use_id=self.tool_use_id,
                    custom_tool_use_id=self.custom_tool_use_id,
                    tool_use_event_id=self.tool_use_event_id,
                    result=self.result,
                    approved=self.approved,
                    deny_message=self.deny_message,
                    payload=self.payload,
                )
            ]
        return []


class SessionEventResponse(BaseModel):
    id: EventId
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    seq: int
    processed_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_serializer
    def _flatten(self) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "id": str(self.id),
            "type": self.event_type,
            "seq": self.seq,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if self.payload:
            _reserved = {"id", "type", "seq", "processed_at", "created_at"}
            for k, v in self.payload.items():
                if k not in _reserved:
                    base[k] = v
        return base


class EventListParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    after_seq: Optional[int] = None
