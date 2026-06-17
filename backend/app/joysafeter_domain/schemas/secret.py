import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class CreateSecretRequest(BaseModel):
    name: str
    provider: str = "custom"
    protocol: str = "custom"
    data: dict[str, str] = Field(default_factory=dict)
    is_default: bool = False


class UpdateSecretRequest(BaseModel):
    provider: Optional[str] = None
    protocol: Optional[str] = None
    data: dict[str, str]


class SecretListItem(BaseModel):
    id: str
    name: str
    provider: str = "custom"
    protocol: str = "custom"
    is_default: bool = False
    keys: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SecretResponse(BaseModel):
    id: str
    name: str
    provider: str = "custom"
    protocol: str = "custom"
    is_default: bool = False
    secret_data: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
