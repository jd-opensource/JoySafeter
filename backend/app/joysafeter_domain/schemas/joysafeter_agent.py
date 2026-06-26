"""
Pydantic schemas for the JoySafeter Agent API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Dict, Literal, Optional, Union

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


class JoySafeterEngineKind(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    NATIVE = "native"


class JoySafeterModelConfig(BaseModel):
    id: str
    speed: str = "standard"

    @field_validator("id", "speed")
    @classmethod
    def trim_model_config(cls, v: str) -> str:
        return v.strip()


class PermissionPolicy(BaseModel):
    type: Literal["always_allow", "always_ask"] = "always_allow"

    def to_mode_str(self) -> str:
        if self.type == "always_allow":
            return "bypassPermissions"
        return "default"


class ToolDefaultConfig(BaseModel):
    permission_policy: PermissionPolicy = Field(default_factory=PermissionPolicy)
    enabled: bool = True


class ToolItemConfig(BaseModel):
    name: str
    enabled: bool = True
    permission_policy: Optional[PermissionPolicy] = None


class AgentToolsetTool(BaseModel):
    type: Literal["agent_toolset_20260401"] = "agent_toolset_20260401"
    default_config: Optional[ToolDefaultConfig] = None
    configs: list[ToolItemConfig] = Field(default_factory=list)


class McpToolsetTool(BaseModel):
    type: Literal["mcp_toolset"] = "mcp_toolset"
    mcp_server_name: str
    default_config: Optional[ToolDefaultConfig] = None
    configs: list[ToolItemConfig] = Field(default_factory=list)


class CustomTool(BaseModel):
    type: Literal["custom"] = "custom"
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


AgentTool = Union[AgentToolsetTool, McpToolsetTool, CustomTool]


class McpServerConfig(BaseModel):
    type: str = "url"
    name: str
    url: str

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        from app.joysafeter_shared.security.ssrf_guard import validate_url_scheme
        return validate_url_scheme(v)


class PackedItem(BaseModel):
    name: str
    tar_gz_b64: str


class SkillRef(BaseModel):
    type: Literal["custom", "anthropic"] = "custom"
    skill_id: str
    version: Optional[str] = "latest"


def _parse_skill_entry(v):
    if isinstance(v, (SkillRef, PackedItem)):
        return v
    if isinstance(v, dict):
        if "skill_id" in v:
            return SkillRef(**{k: v[k] for k in ("type", "skill_id", "version") if k in v})
        if "tar_gz_b64" in v:
            return PackedItem(**{k: v[k] for k in ("name", "tar_gz_b64") if k in v})
    raise ValueError("Skill entry must have 'skill_id' or 'tar_gz_b64'")


SkillEntry = Annotated[Union[SkillRef, PackedItem], BeforeValidator(_parse_skill_entry)]


class JoySafeterCreateAgentRequest(BaseModel):
    name: str
    engine_kind: JoySafeterEngineKind = JoySafeterEngineKind.CLAUDE
    model: Union[str, JoySafeterModelConfig, None] = None
    system: Optional[str] = Field(default=None, alias="system_prompt")
    description: Optional[str] = None
    metadata: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    mcp_servers: list[McpServerConfig] = Field(default_factory=list)
    skills: list[SkillEntry] = Field(default_factory=list)
    agents: list[PackedItem] = Field(default_factory=list)
    commands: list[PackedItem] = Field(default_factory=list)
    tools: list[AgentTool] = Field(default_factory=list)
    multiagent: Optional[Dict[str, Any]] = None
    environment_ref: Optional[str] = None
    secret_ref: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("name", "description", "environment_ref", "secret_ref")
    @classmethod
    def trim_config_value(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v is not None else v

    @model_validator(mode="before")
    @classmethod
    def normalize_model(cls, data: Any) -> Any:
        if isinstance(data, dict):
            m = data.get("model")
            if isinstance(m, str):
                data["model"] = {"id": m.strip(), "speed": "standard"}
        return data


class JoySafeterUpdateAgentRequest(BaseModel):
    version: Optional[int] = None
    name: Optional[str] = None
    engine_kind: Optional[JoySafeterEngineKind] = None
    model: Union[str, JoySafeterModelConfig, None] = None
    system: Optional[str] = Field(default=None, alias="system_prompt")
    description: Optional[str] = None
    metadata: Optional[dict[str, str]] = None
    env: Optional[dict[str, str]] = None
    mcp_servers: Optional[list[McpServerConfig]] = None
    skills: Optional[list[SkillEntry]] = None
    agents: Optional[list[PackedItem]] = None
    commands: Optional[list[PackedItem]] = None
    tools: Optional[list[AgentTool]] = None
    multiagent: Optional[Dict[str, Any]] = None
    environment_ref: Optional[str] = None
    secret_ref: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("name", "description", "environment_ref", "secret_ref")
    @classmethod
    def trim_config_value(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v is not None else v

    @model_validator(mode="before")
    @classmethod
    def normalize_model(cls, data: Any) -> Any:
        if isinstance(data, dict):
            m = data.get("model")
            if isinstance(m, str):
                data["model"] = {"id": m.strip(), "speed": "standard"}
        return data


class JoySafeterAgentResponse(BaseModel):
    id: uuid.UUID
    type: str = "agent"
    name: str
    engine_kind: str
    model: Optional[JoySafeterModelConfig] = None
    system: Optional[str] = None
    description: Optional[str] = None
    metadata: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)
    mcp_servers: list[McpServerConfig] = Field(default_factory=list)
    skills: list[SkillEntry] = Field(default_factory=list)
    agents: list[PackedItem] = Field(default_factory=list)
    commands: list[PackedItem] = Field(default_factory=list)
    tools: list[AgentTool] = Field(default_factory=list)
    multiagent: Optional[Dict[str, Any]] = None
    version: int
    environment_ref: Optional[str] = None
    secret_ref: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"agent_{v}"


class AgentVersionResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    version: int
    snapshot: Dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InjectConfig(BaseModel):
    name: str
    target: str
    tar_gz_b64: str


def extract_permission_mode(tools: list[dict]) -> str:
    for tool in tools:
        tool_type = tool.get("type", "")
        if tool_type in ("agent_toolset_20260401", "mcp_toolset"):
            dc = tool.get("default_config", {})
            pp = dc.get("permission_policy", {})
            if pp.get("type") == "always_ask":
                return "default"
    return "bypassPermissions"
