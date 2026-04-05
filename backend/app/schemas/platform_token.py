"""Pydantic schemas for PlatformToken API."""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.base import ISODatetime, UUIDStr


class TokenCreate(BaseModel):
    name: str = Field(..., max_length=255)
    scopes: List[str] = Field(..., description="e.g. ['skills:read', 'skills:write']")
    resource_type: Optional[str] = Field(None, max_length=50)
    resource_id: Optional[uuid.UUID] = None
    expires_at: Optional[datetime] = None


class TokenCreateResponse(BaseModel):
    """Returned only once at creation — contains plaintext token."""

    id: UUIDStr
    name: str
    token: str  # plaintext, shown only once
    token_prefix: str
    scopes: List[str]
    resource_type: Optional[str] = None
    expires_at: ISODatetime = None
    created_at: ISODatetime = None


class TokenSchema(BaseModel):
    """List view — never contains plaintext token."""

    id: UUIDStr
    name: str
    token_prefix: str
    scopes: List[str]
    resource_type: Optional[str] = None
    resource_id: Optional[UUIDStr] = None
    expires_at: ISODatetime = None
    last_used_at: ISODatetime = None
    is_active: bool
    created_at: ISODatetime = None

    class Config:
        from_attributes = True
