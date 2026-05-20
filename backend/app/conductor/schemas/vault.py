import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class CredentialType(str, Enum):
    STATIC_BEARER = "static_bearer"
    MCP_OAUTH = "mcp_oauth"


class OAuthConfigSchema(BaseModel):
    client_id: str
    client_secret: str = ""
    refresh_token: str = ""
    token_endpoint: str
    expires_at: Optional[datetime] = None
    scopes: list[str] = Field(default_factory=list)

    def is_expired_or_near_expiry(self, buffer_seconds: int = 300) -> bool:
        if not self.expires_at:
            return True
        return self.expires_at < datetime.now(timezone.utc) + timedelta(seconds=buffer_seconds)


class CreateVaultRequest(BaseModel):
    name: str
    description: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)


class UpdateVaultRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict[str, str]] = None


class VaultResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"vault_{v}"


class CreateCredentialRequest(BaseModel):
    name: str
    credential_type: str = "static_bearer"
    mcp_server_url: str
    token_value: str
    oauth_config: Optional[OAuthConfigSchema] = None


class UpdateCredentialRequest(BaseModel):
    name: Optional[str] = None
    token_value: Optional[str] = None
    oauth_config: Optional[OAuthConfigSchema] = None


class VaultCredentialResponse(BaseModel):
    id: uuid.UUID
    vault_id: uuid.UUID
    name: str
    credential_type: str
    mcp_server_url: str
    oauth_config: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"cred_{v}"

    @field_serializer("vault_id")
    def serialize_vault_id(self, v: uuid.UUID) -> str:
        return f"vault_{v}"

    @field_serializer("oauth_config")
    def redact_oauth_secrets(self, v: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not v:
            return v
        redacted = dict(v)
        for key in ("client_secret", "refresh_token"):
            if key in redacted:
                redacted[key] = "***"
        return redacted
