"""Request/response schemas for the unified CredentialService (P0).

`data` is a flat ``dict[str, str]`` for every credential kind. The service is the
authoritative validator (it raises the string error codes the API catalog knows
about); these Pydantic models only do shape normalization (trim names, forbid
extra fields) so malformed input is rejected before it reaches the service.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.joysafeter_shared.ids import CredentialGroupId, CredentialId

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


# --- credential groups (mcp) -----------------------------------------------------
# An mcp credential is BORN INTO a group (group_id NOT NULL), so "membership" is an
# mcp credential row whose group_id is this group. There is no separate cred↔group
# join. These schemas describe the group resource itself and the mcp fields used to
# add a member; the group service is the authoritative validator.


class CreateCredentialGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""

    @field_validator("name")
    @classmethod
    def _norm_name(cls, v: str) -> str:
        return _normalize_name(v)


# --- test-connection request/response (ported from the secrets API) -------------
# A model credential's provider/protocol/data are validated against the LLM
# catalog and a ping request is issued to the upstream API. The request never
# touches the store, so it carries the fields inline (no stored credential id).


class TestCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    protocol: str
    data: dict[str, str] = Field(default_factory=dict)


class CredentialTestResponse(BaseModel):
    ok: bool
    provider: str
    protocol: str
    message: str
    endpoint: Optional[str] = None
    status: Optional[int] = None
    error_detail: Optional[str] = None


# --- responses (masked; never raw secret material) ------------------------------
# Reads mask every non-display-safe `data` value via CredentialService.get_masked
# before shaping these, so a project reader can never recover raw secret material
# through GET/list.


class CredentialResponse(BaseModel):
    id: CredentialId
    kind: CredentialKind
    name: str
    data: dict[str, str] = Field(default_factory=dict)
    provider: Optional[str] = None
    protocol: Optional[str] = None
    is_default: bool = False
    mcp_server_url: Optional[str] = None
    group_id: Optional[CredentialGroupId] = None
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CredentialGroupResponse(BaseModel):
    id: CredentialGroupId
    name: str
    description: str = ""
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class UpdateCredentialGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _norm_name(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_name(v) if v is not None else None


class AddGroupCredentialRequest(BaseModel):
    """The mcp-credential fields for adding a member to a group.

    ``kind`` and ``group_id`` are supplied by the group service (the member is
    born into the group), so they are intentionally absent here; extra="forbid"
    rejects a caller trying to smuggle them in.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    mcp_server_url: str
    data: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _norm_name(cls, v: str) -> str:
        return _normalize_name(v)
