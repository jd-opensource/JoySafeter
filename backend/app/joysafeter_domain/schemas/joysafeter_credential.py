"""Request/response schemas for the unified CredentialService (P0).

`data` is a flat ``dict[str, str]`` for every credential kind. The service is the
authoritative validator (it raises the string error codes the API catalog knows
about); these Pydantic models only do shape normalization (trim names, forbid
extra fields) so malformed input is rejected before it reaches the service.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.joysafeter_shared.ids import CredentialGroupId

# --- data contract limits (flat dict[str, str]) ---------------------------------
# Named constants for the size bounds the service enforces on every credential's
# `data` payload. Chosen to comfortably fit real credentials (multiple keys, long
# base64/JWT values) while bounding storage + encryption cost per row.
CREDENTIAL_DATA_MAX_FIELDS = 50
CREDENTIAL_DATA_MAX_KEY_LENGTH = 128
CREDENTIAL_DATA_MAX_VALUE_LENGTH = 8192


class CredentialKind(StrEnum):
    MODEL = "model"
    MCP = "mcp"
    SERVICE = "service"


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("Credential name must not be blank")
    return normalized


class CreateCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: CredentialKind
    name: str
    data: dict[str, str] = Field(default_factory=dict)
    # kind=model
    provider: Optional[str] = None
    protocol: Optional[str] = None
    is_default: bool = False
    # kind=mcp
    mcp_server_url: Optional[str] = None
    group_id: Optional[CredentialGroupId] = None

    @field_validator("name")
    @classmethod
    def _norm_name(cls, v: str) -> str:
        return _normalize_name(v)


class UpdateCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # kind is IMMUTABLE and therefore intentionally absent here. Immutable
    # identity fields (provider/protocol/mcp_server_url/group_id) are also absent;
    # if a caller sends them, extra="forbid" rejects the request at the schema
    # boundary. Only name/data/is_default may change (is_default only for model).
    name: Optional[str] = None
    data: Optional[dict[str, str]] = None
    is_default: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def _norm_name(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_name(v) if v is not None else None
