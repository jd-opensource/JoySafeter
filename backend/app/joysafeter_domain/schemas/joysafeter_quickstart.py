"""Response schema for the quickstart recommendation endpoint.

Mirrors ``backend/contracts/quickstart_recommendation_contract.json`` (frozen by
``tests/test_quickstart_recommendation_contract.py``). The frontend keeps a
hand-written ``as const`` mirror asserted for parity against the same JSON.

The response contains recommendation inputs only. Enforcement and authorization
are derived from the Environment, Agent MCP configuration, and Credential Group
members that actually exist.
"""

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.joysafeter_domain.quickstart.flow import QuickstartPhase
from app.joysafeter_domain.schemas.joysafeter_agent import (
    AgentTool,
    JoySafeterModelConfig,
    McpServerConfig,
    SkillRef,
)

QuickstartEngineReadiness = Literal["ready", "setup_required", "unavailable"]
QuickstartHostReason = Literal["explicitHosts", "knownServices", "none"]
QuickstartExternalToolsReason = Literal["mcpServers", "credentialIntent"]
QuickstartMcpAuthRequirement = Literal["required", "optional"]


class QuickstartAgentContext(BaseModel):
    """Canonical bounded Agent draft accepted across Quickstart phases."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    model: Optional[Union[str, JoySafeterModelConfig]] = None
    engine_kind: Optional[str] = Field(default=None, max_length=50)
    system: Optional[str] = Field(default=None, max_length=5000)
    tools: Optional[list[AgentTool]] = Field(default=None, max_length=10)
    mcp_servers: Optional[list[McpServerConfig]] = Field(default=None, max_length=10)
    skills: Optional[list[SkillRef]] = Field(default=None, max_length=20)
    metadata: Optional[dict[str, Any]] = None
    blueprint: Optional[dict[str, Any]] = None

    @property
    def model_id(self) -> Optional[str]:
        if isinstance(self.model, JoySafeterModelConfig):
            return self.model.id
        return self.model


class QuickstartEngineOptionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine_id: str = Field(..., min_length=1)
    readiness: QuickstartEngineReadiness
    compatible_connection_count: int = Field(..., ge=0)


class QuickstartEngineRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommended_engine_id: Optional[str]
    options: list[QuickstartEngineOptionOut] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_recommended_engine(self) -> "QuickstartEngineRecommendation":
        option_ids = [option.engine_id for option in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("engine option IDs must be unique")
        if self.recommended_engine_id is None:
            return self
        matching = next(
            (option for option in self.options if option.engine_id == self.recommended_engine_id),
            None,
        )
        if matching is None:
            raise ValueError("recommended engine must reference an option")
        if matching.readiness == "unavailable":
            raise ValueError("recommended engine must be available")
        return self


class QuickstartEnvironmentRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_hosts: list[str]
    host_reason: QuickstartHostReason

    @field_validator("allowed_hosts")
    @classmethod
    def validate_allowed_hosts(cls, hosts: list[str]) -> list[str]:
        normalized = [host.strip() for host in hosts]
        if any(not host for host in normalized):
            raise ValueError("allowed hosts must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowed hosts must be unique")
        return normalized


class QuickstartCredentialGroupRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mcp_servers: list["QuickstartMcpServerRecommendation"]
    external_tools_reason: QuickstartExternalToolsReason

    @model_validator(mode="after")
    def validate_reason(self) -> "QuickstartCredentialGroupRecommendation":
        if self.external_tools_reason == "mcpServers" and not self.mcp_servers:
            raise ValueError("mcpServers reason requires at least one MCP server")
        if self.mcp_servers and self.external_tools_reason != "mcpServers":
            raise ValueError("MCP server recommendations require mcpServers reason")
        return self


class QuickstartMcpServerRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    auth_requirement: QuickstartMcpAuthRequirement

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        from app.joysafeter_shared.security.ssrf_guard import validate_url_scheme

        validated = validate_url_scheme(value)
        assert validated is not None
        return validated


class QuickstartUnderstandRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: Literal[QuickstartPhase.UNDERSTAND]
    engine: QuickstartEngineRecommendation


class QuickstartSecureRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: Literal[QuickstartPhase.SECURE]
    environment: QuickstartEnvironmentRecommendation
    credential_group: Optional[QuickstartCredentialGroupRecommendation]


QuickstartRecommendation = Annotated[
    Union[QuickstartUnderstandRecommendation, QuickstartSecureRecommendation],
    Field(discriminator="phase"),
]
