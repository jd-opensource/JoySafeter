import uuid
from datetime import datetime
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_serializer


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
    id: uuid.UUID
    version: int
    name: str
    description: Optional[str] = None
    model: Optional[dict[str, Any]] = None
    system: Optional[str] = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)
    multiagent: Optional[dict[str, Any]] = None

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"agent_{v}"

    @classmethod
    def from_agent(cls, agent) -> "SessionAgent":
        return cls(
            id=agent.id,
            version=agent.version,
            name=agent.name,
            description=agent.description,
            model=agent.model,
            system=agent.system_prompt,
            tools=agent.tools or [],
            skills=agent.skills or [],
            mcp_servers=agent.mcp_configs or [],
            multiagent=agent.multiagent,
        )


class ContentBlock(BaseModel):
    type: Literal["text", "image", "document"]
    text: Optional[str] = None
    source: Optional[dict[str, Any]] = None

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


StopReason = Union[EndTurnStopReason, RequiresActionStopReason, RetriesExhaustedStopReason]


class AgentRef(BaseModel):
    """Agent reference supporting pinned versions: {type, id, version}."""
    type: str = "agent"
    id: uuid.UUID
    version: Optional[int] = None


class SessionResourceRequest(BaseModel):
    memory_store_id: uuid.UUID
    access: str = "read_write"
    instructions: Optional[str] = None
    mount_name: Optional[str] = None


MAX_MEMORY_STORE_RESOURCES = 8


class CreateSessionRequest(BaseModel):
    agent: Optional[AgentRef] = None
    agent_id: Optional[uuid.UUID] = None
    agent_name: Optional[str] = None
    title: Optional[str] = None
    metadata: dict[str, str] = Field(default_factory=dict)
    vault_ids: list[str] = Field(default_factory=list)
    environment_id: str
    resources: list[SessionResourceRequest] = Field(default_factory=list)


class SessionResourceResponse(BaseModel):
    memory_store_id: uuid.UUID
    access: str = "read_write"
    instructions: Optional[str] = None
    mount_name: str = ""

    @field_serializer("memory_store_id")
    def serialize_store_id(self, v: uuid.UUID) -> str:
        return f"memstore_{v}"


class SessionResponse(BaseModel):
    id: uuid.UUID
    type: str = "session"
    agent: SessionAgent
    environment_id: Optional[str] = None
    status: str
    stop_reason: Optional[dict[str, Any]] = None
    title: Optional[str] = None
    metadata: dict[str, str] = Field(default_factory=dict)
    vault_ids: list[str] = Field(default_factory=list)
    resources: list[SessionResourceResponse] = Field(default_factory=list)
    usage: SessionUsage = Field(default_factory=SessionUsage)
    stats: SessionStats = Field(default_factory=SessionStats)
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"sess_{v}"


class SingleEventRequest(BaseModel):
    type: str
    content: Optional[str] = None
    tool_use_id: Optional[str] = None
    custom_tool_use_id: Optional[str] = None
    tool_use_event_id: Optional[str] = None
    result: Optional[str] = None
    approved: Optional[bool] = None
    deny_message: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def resolved_tool_use_id(self) -> Optional[str]:
        return self.tool_use_id or self.custom_tool_use_id or self.tool_use_event_id

    def resolved_approved(self) -> Optional[bool]:
        if self.result is not None:
            return self.result == "allow"
        return self.approved


class SendEventRequest(BaseModel):
    type: Optional[str] = None
    events: Optional[list[SingleEventRequest]] = None
    content: Optional[str] = None
    tool_use_id: Optional[str] = None
    custom_tool_use_id: Optional[str] = None
    tool_use_event_id: Optional[str] = None
    result: Optional[str] = None
    approved: Optional[bool] = None
    deny_message: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_single_events(self) -> list[SingleEventRequest]:
        if self.events:
            return self.events
        if self.type:
            return [SingleEventRequest(
                type=self.type,
                content=self.content,
                tool_use_id=self.tool_use_id,
                custom_tool_use_id=self.custom_tool_use_id,
                tool_use_event_id=self.tool_use_event_id,
                result=self.result,
                approved=self.approved,
                deny_message=self.deny_message,
                payload=self.payload,
            )]
        return []


class SessionEventResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    seq: int
    processed_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"evt_{v}"


class EventListParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    after_seq: Optional[int] = None
