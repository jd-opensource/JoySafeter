"""Skill Collaborator API routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.schemas.skill_collaborator import (
    CollaboratorCreate,
    CollaboratorSchema,
    CollaboratorUpdate,
    TransferOwnershipRequest,
)
from app.services.skill_collaborator_service import SkillCollaboratorService

router = APIRouter(prefix="/v1/skills", tags=["Skill Collaborators"])


@router.get("/{skill_id}/collaborators")
async def list_collaborators(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SkillCollaboratorService(db)
    collaborators = await service.list_collaborators(
        skill_id=skill_id,
        current_user_id=current_user.id,
        is_superuser=current_user.is_superuser,
    )
    return {
        "success": True,
        "data": [CollaboratorSchema.model_validate(c).model_dump() for c in collaborators],
    }


@router.post("/{skill_id}/collaborators")
async def add_collaborator(
    skill_id: uuid.UUID,
    payload: CollaboratorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SkillCollaboratorService(db)
    collaborator = await service.add_collaborator(
        skill_id=skill_id,
        current_user_id=current_user.id,
        target_user_id=payload.user_id,
        role=payload.role,
        is_superuser=current_user.is_superuser,
    )
    return {
        "success": True,
        "data": CollaboratorSchema.model_validate(collaborator).model_dump(),
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
        "data": CollaboratorSchema.model_validate(collaborator).model_dump(),
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
