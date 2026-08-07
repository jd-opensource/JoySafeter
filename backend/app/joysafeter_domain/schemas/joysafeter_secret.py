from datetime import datetime
from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.joysafeter_shared.ids import SecretId


def _is_trimmed_secret_key(key: str) -> bool:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in key).strip("_").upper()
    return (
        normalized in {"URL", "URI", "ENDPOINT", "API_KEY", "AUTH_TOKEN", "TOKEN", "SECRET", "MODEL"}
        or normalized.endswith("_URL")
        or normalized.endswith("_URI")
        or normalized.endswith("_ENDPOINT")
        or normalized.endswith("_API_KEY")
        or normalized.endswith("_AUTH_TOKEN")
        or normalized.endswith("_TOKEN")
        or normalized.endswith("_SECRET")
        or normalized.endswith("_MODEL")
    )


def _trim_secret_values(data: dict[str, str]) -> dict[str, str]:
    return {
        str(key): str(value).strip() if _is_trimmed_secret_key(str(key)) else str(value)
        for key, value in (data or {}).items()
    }


class SecretKind(StrEnum):
    LLM = "llm"
    GENERIC = "generic"


class CreateSecretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: SecretKind
    name: str
    provider: Optional[str] = None
    protocol: Optional[str] = None
    data: dict[str, str] = Field(default_factory=dict)
    is_default: bool = False

    @field_validator("data")
    @classmethod
    def _trim_url_values(cls, v: dict[str, str]) -> dict[str, str]:
        return _trim_secret_values(v)

    @model_validator(mode="after")
    def _validate_identity(self) -> "CreateSecretRequest":
        if self.kind is SecretKind.LLM:
            if not self.provider or not self.protocol:
                raise ValueError("LLM secrets require provider and protocol")
            return self
        if self.provider is not None or self.protocol is not None:
            raise ValueError("Generic secrets must not define provider or protocol")
        if self.is_default:
            raise ValueError("Generic secrets cannot be a default")
        return self


class UpdateSecretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: dict[str, str]

    @field_validator("data")
    @classmethod
    def _trim_url_values(cls, v: dict[str, str]) -> dict[str, str]:
        return _trim_secret_values(v)


class TestSecretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[SecretKind.LLM]
    provider: str
    protocol: str
    data: dict[str, str] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def _trim_url_values(cls, v: dict[str, str]) -> dict[str, str]:
        return _trim_secret_values(v)


class SecretTestResponse(BaseModel):
    ok: bool
    provider: str
    protocol: str
    message: str
    endpoint: Optional[str] = None
    status: Optional[int] = None
    error_detail: Optional[str] = None


class SecretListItem(BaseModel):
    id: SecretId
    name: str
    kind: SecretKind
    provider: Optional[str] = None
    protocol: Optional[str] = None
    model: Optional[str] = None
    compatible_engine_ids: list[str] = Field(default_factory=list)
    is_default: bool = False
    keys: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SecretResponse(BaseModel):
    id: SecretId
    name: str
    kind: SecretKind
    provider: Optional[str] = None
    protocol: Optional[str] = None
    model: Optional[str] = None
    compatible_engine_ids: list[str] = Field(default_factory=list)
    is_default: bool = False
    secret_data: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
