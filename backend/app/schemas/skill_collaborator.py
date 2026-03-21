"""Pydantic schemas for Skill Collaborator API."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.skill_collaborator import CollaboratorRole


class CollaboratorCreate(BaseModel):
    user_id: str = Field(..., description="User ID to add as collaborator")
    role: CollaboratorRole = Field(..., description="Role to assign")


class CollaboratorUpdate(BaseModel):
    role: CollaboratorRole = Field(..., description="New role")


class CollaboratorSchema(BaseModel):
    id: str
    skill_id: str
    user_id: str
    role: CollaboratorRole
    invited_by: str
    created_at: Optional[str] = None

    @field_validator("id", "skill_id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_datetime_to_str(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    class Config:
        from_attributes = True


class TransferOwnershipRequest(BaseModel):
    new_owner_id: str = Field(..., description="User ID of new owner")
