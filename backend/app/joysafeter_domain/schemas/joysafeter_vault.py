from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.joysafeter_shared.ids import CredentialId, VaultId


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
    description: Optional[str] = None
    metadata: Optional[dict[str, str]] = None


class VaultResponse(BaseModel):
    id: VaultId
    name: str
    description: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class CreateCredentialRequest(BaseModel):
    name: Optional[str] = Field(
        default=None,
        description="Optional display name; omitted, null, or blank values use the normalized MCP server URL.",
    )
    credential_type: str = "static_bearer"
    mcp_server_url: str
    token_value: str
    oauth_config: Optional[OAuthConfigSchema] = None

    @field_validator("mcp_server_url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        from app.joysafeter_shared.security.ssrf_guard import validate_url_scheme

        validated = validate_url_scheme(v)
        assert validated is not None  # v is a non-None str, so result is non-None
        return validated


class UpdateCredentialRequest(BaseModel):
    name: Optional[str] = None
    token_value: Optional[str] = None
    oauth_config: Optional[OAuthConfigSchema] = None


class VaultCredentialResponse(BaseModel):
    id: CredentialId
    vault_id: VaultId
    name: str
    credential_type: str
    mcp_server_url: str
    token_value: str = ""
    oauth_config: Optional[dict[str, Any]] = None
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("token_value")
    def redact_token(self, v: str) -> str:
        # Default-deny: never echo any part of a stored token. The previous
        # first-6-chars fallback leaked plaintext prefixes (and whole short
        # tokens) whenever a value was not enc:-prefixed.
        return "********" if v else v

    @field_serializer("oauth_config")
    def redact_oauth_secrets(self, v: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not v:
            return v
        redacted = dict(v)
        for key in ("client_secret", "refresh_token"):
            if key in redacted and redacted[key]:
                redacted[key] = "********"
        return redacted
