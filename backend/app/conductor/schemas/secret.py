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
    id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SecretResponse(BaseModel):
    id: uuid.UUID
    name: str
    data: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
