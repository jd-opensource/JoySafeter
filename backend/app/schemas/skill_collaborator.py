"""Pydantic schemas for Skill Collaborator API."""

from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.models.skill_collaborator import CollaboratorRole
from app.schemas.base import ISODatetime, UUIDStr


class CollaboratorCreate(BaseModel):
    user_id: Optional[str] = Field(None, description="User ID to add as collaborator")
    email: Optional[str] = Field(None, description="Email to find user and add as collaborator")
    role: CollaboratorRole = Field(..., description="Role to assign")

    @model_validator(mode="after")
    def require_user_id_or_email(self):
        if not self.user_id and not self.email:
            raise ValueError("Either user_id or email must be provided")
        return self


class CollaboratorUpdate(BaseModel):
    role: CollaboratorRole = Field(..., description="New role")


class CollaboratorSchema(BaseModel):
    id: UUIDStr
    skill_id: UUIDStr
    user_id: str
    role: CollaboratorRole
    invited_by: str
    created_at: ISODatetime = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None

    class Config:
        from_attributes = True


class TransferOwnershipRequest(BaseModel):
    new_owner_id: str = Field(..., description="User ID of new owner")
