"""Pydantic schemas for Skill Collaborator API."""

from pydantic import BaseModel, Field

from app.models.skill_collaborator import CollaboratorRole
from app.schemas.base import ISODatetime, UUIDStr


class CollaboratorCreate(BaseModel):
    user_id: str = Field(..., description="User ID to add as collaborator")
    role: CollaboratorRole = Field(..., description="Role to assign")


class CollaboratorUpdate(BaseModel):
    role: CollaboratorRole = Field(..., description="New role")


class CollaboratorSchema(BaseModel):
    id: UUIDStr
    skill_id: UUIDStr
    user_id: str
    role: CollaboratorRole
    invited_by: str
    created_at: ISODatetime = None

    class Config:
        from_attributes = True


class TransferOwnershipRequest(BaseModel):
    new_owner_id: str = Field(..., description="User ID of new owner")
