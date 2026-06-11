import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class CreateSecretRequest(BaseModel):
    name: str
    data: dict[str, str] = Field(default_factory=dict)


class UpdateSecretRequest(BaseModel):
    data: dict[str, str]


class SecretListItem(BaseModel):
    id: str
    name: str
    keys: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SecretResponse(BaseModel):
    id: str
    name: str
    secret_data: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
