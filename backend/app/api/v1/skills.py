"""
Skill CRUD API
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user, get_current_user_optional
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.schemas.skill import (
    SkillCreate,
    SkillFileCreate,
    SkillFileSchema,
    SkillFileUpdate,
    SkillSchema,
    SkillUpdate,
)
from app.services.skill_service import SkillService

router = APIRouter(prefix="/v1/skills", tags=["Skills"])


@router.get("")
async def list_skills(
    include_public: bool = Query(True, description="Include public skills"),
    tags: Optional[List[str]] = Query(None, description="Filter by tags"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """获取 Skills 列表"""
    service = SkillService(db)
    user_id = current_user.id if current_user else None
    skills = await service.list_skills(
        current_user_id=user_id,
        include_public=include_public,
        tags=tags,
    )
    return {
        "success": True,
        "data": [SkillSchema.model_validate(skill).model_dump() for skill in skills],
    }


@router.post("")
async def create_skill(
    payload: SkillCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建 Skill"""
    service = SkillService(db)

    files_data = None
    if payload.files:
        files_data = [f.dict() for f in payload.files]

    skill = await service.create_skill(
        created_by_id=current_user.id,
        name=payload.name,
        description=payload.description,
        content=payload.content,
        tags=payload.tags,
        source_type=payload.source_type,
        source_url=payload.source_url,
        root_path=payload.root_path,
        owner_id=payload.owner_id,
        is_public=payload.is_public,
        license=payload.license,
        files=files_data,
    )

    # 重新加载以获取文件
    skill = await service.get_skill(skill.id, current_user.id)
    return {
        "success": True,
        "data": SkillSchema.model_validate(skill).model_dump(),
    }


@router.get("/{skill_id}")
async def get_skill(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """获取 Skill 详情"""
    service = SkillService(db)
    user_id = current_user.id if current_user else None
    skill = await service.get_skill(skill_id, user_id)
    return {
        "success": True,
        "data": SkillSchema.model_validate(skill).model_dump(),
    }


@router.put("/{skill_id}")
async def update_skill(
    skill_id: uuid.UUID,
    payload: SkillUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新 Skill"""
    service = SkillService(db)

    # Convert files to dict format if provided
    files_data = None
    if payload.files is not None:
        files_data = [f.model_dump() for f in payload.files]

    skill = await service.update_skill(
        skill_id,
        current_user.id,
        name=payload.name,
        description=payload.description,
        content=payload.content,
        tags=payload.tags,
        source_type=payload.source_type,
        source_url=payload.source_url,
        root_path=payload.root_path,
        owner_id=payload.owner_id,
        is_public=payload.is_public,
        license=payload.license,
        files=files_data,
    )
    # 重新加载以获取文件
    skill = await service.get_skill(skill.id, current_user.id)
    return {
        "success": True,
        "data": SkillSchema.model_validate(skill).model_dump(),
    }


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除 Skill"""
    service = SkillService(db)
    await service.delete_skill(skill_id, current_user.id)
    return {"success": True}


@router.post("/{skill_id}/files")
async def add_file(
    skill_id: uuid.UUID,
    file: SkillFileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """添加文件到 Skill"""
    service = SkillService(db)
    file_obj = await service.add_file(
        skill_id=skill_id,
        current_user_id=current_user.id,
        path=file.path,
        file_name=file.file_name,
        file_type=file.file_type,
        content=file.content,
        storage_type=file.storage_type,
        storage_key=file.storage_key,
        size=file.size,
    )
    return {
        "success": True,
        "data": SkillFileSchema.model_validate(file_obj).model_dump(),
    }


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除文件"""
    service = SkillService(db)
    await service.delete_file(file_id, current_user.id)
    return {"success": True}


@router.put("/files/{file_id}")
async def update_file(
    file_id: uuid.UUID,
    payload: SkillFileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新文件内容或重命名文件"""
    service = SkillService(db)
    file_obj = await service.update_file(
        file_id=file_id,
        current_user_id=current_user.id,
        content=payload.content,
        path=payload.path,
        file_name=payload.file_name,
    )
    return {
        "success": True,
        "data": SkillFileSchema.model_validate(file_obj).model_dump(),
    }
