"""
API Key 管理
- GET /api/v1/api-keys            列表（personal 默认，workspace 需 admin+）
- POST /api/v1/api-keys           创建（personal 或 workspace admin+）
- DELETE /api/v1/api-keys/{id}    删除（personal 仅本人，workspace admin+）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.api_key_service import ApiKeyService

router = APIRouter(prefix="/api-keys", tags=["ApiKeys"])


class ApiKeyCreate(BaseModel):
    name: str = Field(..., max_length=255)
    type: str = Field(default="personal", description="personal|workspace")
    workspaceId: Optional[uuid.UUID] = Field(default=None)
    expiresAt: Optional[datetime] = Field(default=None)


@router.get("")
async def list_api_keys(
    workspace_id: Optional[uuid.UUID] = Query(default=None, alias="workspaceId"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 注意：workspace_id 可能为 None（personal API key）

    service = ApiKeyService(db)
    data = await service.list_keys(current_user_id=uuid.UUID(current_user.id), workspace_id=workspace_id)
    return {"success": True, "data": data}


@router.post("")
async def create_api_key(
    payload: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 注意：workspace_id 可能为 None（personal API key）
    workspace_id = payload.workspaceId if payload.type == "workspace" else None

    service = ApiKeyService(db)
    # workspace 类型的权限在 service 内校验（admin+）；personal 仅本人
    data = await service.create_key(
        current_user_id=uuid.UUID(current_user.id),
        name=payload.name,
        type=payload.type,
        workspace_id=workspace_id,
        expires_at=payload.expiresAt,
    )
    return {"success": True, "data": data}


@router.delete("/{key_id}")
async def delete_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ApiKeyService(db)
    await service.delete_key(key_id=key_id, current_user_id=uuid.UUID(current_user.id))
    return {"success": True}
