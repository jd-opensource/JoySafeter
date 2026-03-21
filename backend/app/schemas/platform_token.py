"""Pydantic schemas for PlatformToken API."""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class TokenCreate(BaseModel):
    name: str = Field(..., max_length=255)
    scopes: List[str] = Field(..., description="e.g. ['skills:read', 'skills:write']")
    resource_type: Optional[str] = Field(None, max_length=50)
    resource_id: Optional[uuid.UUID] = None
    expires_at: Optional[datetime] = None


class TokenCreateResponse(BaseModel):
    """Returned only once at creation — contains plaintext token."""

    id: str
    name: str
    token: str  # plaintext, shown only once
    token_prefix: str
    scopes: List[str]
    expires_at: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    @field_validator("expires_at", mode="before")
    @classmethod
    def convert_datetime_to_str(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v


class TokenSchema(BaseModel):
    """List view — never contains plaintext token."""

    id: str
    name: str
    token_prefix: str
    scopes: List[str]
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    expires_at: Optional[str] = None
    last_used_at: Optional[str] = None
    is_active: bool
    created_at: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    @field_validator("resource_id", mode="before")
    @classmethod
    def convert_resource_id(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    @field_validator("expires_at", "last_used_at", "created_at", mode="before")
    @classmethod
    def convert_datetime_to_str(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    class Config:
        from_attributes = True
