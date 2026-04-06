"""Skill Collaborator API routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.exceptions import NotFoundException
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.schemas.skill_collaborator import (
    CollaboratorCreate,
    CollaboratorSchema,
    CollaboratorUpdate,
    TransferOwnershipRequest,
)
from app.services.skill_collaborator_service import SkillCollaboratorService
from app.services.user_service import UserService

router = APIRouter(prefix="/v1/skills", tags=["Skill Collaborators"])


def _serialize_collaborator(c) -> dict:
    """Serialize a SkillCollaborator with related user name/email."""
    data = CollaboratorSchema.model_validate(c).model_dump()
    data["user_name"] = c.user.name if c.user else None
    data["user_email"] = c.user.email if c.user else None
    return data


@router.get("/{skill_id}/collaborators")
async def list_collaborators(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SkillCollaboratorService(db)
    collaborators, skill = await service.list_collaborators(
        skill_id=skill_id,
        current_user_id=current_user.id,
        is_superuser=current_user.is_superuser,
    )

    user_service = UserService(db)
    owner = await user_service.get_user_by_id(skill.owner_id) if skill.owner_id else None

    return {
        "success": True,
        "data": {
            "collaborators": [_serialize_collaborator(c) for c in collaborators],
            "owner": {
                "id": owner.id,
                "name": owner.name,
                "email": owner.email,
            }
            if owner
            else {"id": skill.owner_id, "name": None, "email": None},
        },
    }


@router.post("/{skill_id}/collaborators")
async def add_collaborator(
    skill_id: uuid.UUID,
    payload: CollaboratorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Resolve user_id from email if needed
    target_user_id = payload.user_id
    if not target_user_id and payload.email:
        user_service = UserService(db)
        user = await user_service.get_user_by_email(payload.email.strip())
        if not user:
            raise NotFoundException("User not found")
        target_user_id = user.id

    if not target_user_id:
        raise NotFoundException("User not found")

    service = SkillCollaboratorService(db)
    collaborator = await service.add_collaborator(
        skill_id=skill_id,
        current_user_id=current_user.id,
        target_user_id=target_user_id,
        role=payload.role,
        is_superuser=current_user.is_superuser,
    )
    return {
        "success": True,
        "data": _serialize_collaborator(collaborator),
    }


@router.put("/{skill_id}/collaborators/{target_user_id}")
async def update_collaborator(
    skill_id: uuid.UUID,
    target_user_id: str,
    payload: CollaboratorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SkillCollaboratorService(db)
    collaborator = await service.update_collaborator_role(
        skill_id=skill_id,
        current_user_id=current_user.id,
        target_user_id=target_user_id,
        new_role=payload.role,
        is_superuser=current_user.is_superuser,
    )
    return {
        "success": True,
        "data": _serialize_collaborator(collaborator),
    }


@router.delete("/{skill_id}/collaborators/{target_user_id}")
async def remove_collaborator(
    skill_id: uuid.UUID,
    target_user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SkillCollaboratorService(db)
    await service.remove_collaborator(
        skill_id=skill_id,
        current_user_id=current_user.id,
        target_user_id=target_user_id,
        is_superuser=current_user.is_superuser,
    )
    return {"success": True}


@router.post("/{skill_id}/transfer")
async def transfer_ownership(
    skill_id: uuid.UUID,
    payload: TransferOwnershipRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SkillCollaboratorService(db)
    await service.transfer_ownership(
        skill_id=skill_id,
        current_user_id=current_user.id,
        new_owner_id=payload.new_owner_id,
    )
    return {"success": True}
