"""Skill Version API routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.auth_dependency import AuthContext, get_current_user_or_token
from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.schemas.skill import SkillSchema
from app.schemas.skill_version import (
    VersionPublishRequest,
    VersionRestoreRequest,
    VersionSchema,
    VersionSummarySchema,
)
from app.services.skill_version_service import SkillVersionService

router = APIRouter(prefix="/v1/skills", tags=["Skill Versions"])


@router.post("/{skill_id}/versions")
async def publish_version(
    skill_id: uuid.UUID,
    payload: VersionPublishRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user_or_token),
):
    service = SkillVersionService(db)
    version = await service.publish_version(
        skill_id=skill_id,
        current_user_id=auth.user.id,
        version_str=payload.version,
        release_notes=payload.release_notes,
        is_superuser=auth.user.is_superuser,
        token_scopes=auth.scopes,
    )
    return {
        "success": True,
        "data": VersionSchema.model_validate(version).model_dump(),
    }


@router.get("/{skill_id}/versions")
async def list_versions(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user_or_token),
):
    service = SkillVersionService(db)
    versions = await service.list_versions(
        skill_id=skill_id,
        current_user_id=auth.user.id,
        is_superuser=auth.user.is_superuser,
        token_scopes=auth.scopes,
    )
    return {
        "success": True,
        "data": [VersionSummarySchema.model_validate(v).model_dump() for v in versions],
    }


@router.get("/{skill_id}/versions/latest")
async def get_latest_version(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user_or_token),
):
    service = SkillVersionService(db)
    version = await service.get_latest_version(
        skill_id=skill_id,
        current_user_id=auth.user.id,
        is_superuser=auth.user.is_superuser,
        token_scopes=auth.scopes,
    )
    return {
        "success": True,
        "data": VersionSchema.model_validate(version).model_dump(),
    }


@router.get("/{skill_id}/versions/{version}")
async def get_version(
    skill_id: uuid.UUID,
    version: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user_or_token),
):
    service = SkillVersionService(db)
    ver = await service.get_version(
        skill_id=skill_id,
        version_str=version,
        current_user_id=auth.user.id,
        is_superuser=auth.user.is_superuser,
        token_scopes=auth.scopes,
    )
    return {
        "success": True,
        "data": VersionSchema.model_validate(ver).model_dump(),
    }


@router.delete("/{skill_id}/versions/{version}")
async def delete_version(
    skill_id: uuid.UUID,
    version: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SkillVersionService(db)
    await service.delete_version(
        skill_id=skill_id,
        version_str=version,
        current_user_id=current_user.id,
        is_superuser=current_user.is_superuser,
    )
    return {"success": True}


@router.post("/{skill_id}/restore")
async def restore_version(
    skill_id: uuid.UUID,
    payload: VersionRestoreRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SkillVersionService(db)
    skill = await service.restore_draft(
        skill_id=skill_id,
        version_str=payload.version,
        current_user_id=current_user.id,
        is_superuser=current_user.is_superuser,
    )
    return {
        "success": True,
        "data": SkillSchema.model_validate(skill).model_dump(),
    }
