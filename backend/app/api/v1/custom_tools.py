"""
Custom Tool CRUD API (User-level)
- 读写：基于用户所有权
- 用户级配额限制（默认 100）
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.custom_tool_service import CustomToolService

router = APIRouter(prefix="/custom-tools", tags=["CustomTools"])


class CustomToolCreate(BaseModel):
    name: str = Field(..., max_length=255)
    code: str
    json_schema: Dict[str, Any] = Field(default_factory=dict, alias="schema")
    runtime: str = Field(default="python", max_length=50)
    enabled: bool = True

    model_config = ConfigDict(populate_by_name=True)


class CustomToolUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    code: Optional[str] = None
    json_schema: Optional[Dict[str, Any]] = Field(None, alias="schema")
    runtime: Optional[str] = Field(None, max_length=50)
    enabled: Optional[bool] = None

    model_config = ConfigDict(populate_by_name=True)


def _serialize(tool) -> Dict[str, Any]:
    return {
        "id": str(tool.id),
        "ownerId": str(tool.owner_id),
        "name": tool.name,
        "code": tool.code,
        "schema": tool.schema,
        "runtime": tool.runtime,
        "enabled": tool.enabled,
        "createdAt": tool.created_at,
        "updatedAt": tool.updated_at,
    }


@router.get("")
async def list_custom_tools(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的所有工具"""
    service = CustomToolService(db)
    tools = await service.list_tools(current_user.id)
    return {"success": True, "data": [_serialize(t) for t in tools]}


@router.post("")
async def create_custom_tool(
    payload: CustomToolCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建工具（用户级别）"""
    service = CustomToolService(db)
    tool = await service.create_tool(
        owner_id=current_user.id,
        name=payload.name,
        code=payload.code,
        schema=payload.json_schema,
        runtime=payload.runtime,
        enabled=payload.enabled,
    )
    return {"success": True, "data": _serialize(tool)}


@router.get("/{tool_id}")
async def get_custom_tool(
    tool_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工具详情（仅限所有者）"""
    service = CustomToolService(db)
    tool = await service.repo.get(tool_id)
    if not tool:
        return {"success": False, "error": "Not found"}
    # 验证所有权
    if tool.owner_id != current_user.id:
        return {"success": False, "error": "Forbidden"}
    return {"success": True, "data": _serialize(tool)}


@router.put("/{tool_id}")
async def update_custom_tool(
    tool_id: uuid.UUID,
    payload: CustomToolUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新工具（仅限所有者）"""
    service = CustomToolService(db)
    tool = await service.update_tool(
        tool_id,
        current_user.id,
        name=payload.name,
        code=payload.code,
        schema=payload.json_schema,
        runtime=payload.runtime,
        enabled=payload.enabled,
    )
    return {"success": True, "data": _serialize(tool)}


@router.delete("/{tool_id}")
async def delete_custom_tool(
    tool_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CustomToolService(db)
    await service.delete_tool(tool_id, current_user.id)
    return {"success": True}
