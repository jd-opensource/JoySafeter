"""
模型凭据管理API
"""

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.response import success_response
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.model_credential_service import ModelCredentialService

router = APIRouter(prefix="/v1/model-credentials", tags=["ModelCredentials"])


class CredentialCreate(BaseModel):
    """创建凭据请求"""

    provider_name: str = Field(description="供应商名称", examples=["openaiapicompatible"])
    credentials: Dict[str, Any] = Field(..., description="凭据字典（明文）")
    workspace_id: Optional[uuid.UUID] = Field(default=None, alias="workspaceId", description="工作空间ID（可选）")
    should_validate: bool = Field(default=True, alias="validate", description="是否验证凭据")


class CredentialValidateResponse(BaseModel):
    """凭据验证响应"""

    is_valid: bool
    error: Optional[str] = None
    last_validated_at: Optional[str] = None


@router.post("")
async def create_or_update_credential(
    payload: CredentialCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    创建或更新模型凭据

    Args:
        payload: 凭据创建请求

    Returns:
        创建的凭据信息
    """
    service = ModelCredentialService(db)
    user_id = current_user.id
    credential = await service.create_or_update_credential(
        user_id=user_id,
        provider_name=payload.provider_name,
        credentials=payload.credentials,
        workspace_id=payload.workspace_id,
        validate=payload.should_validate,
    )
    return success_response(data=credential, message="创建/更新凭据成功")


@router.get("")
async def list_credentials(
    workspace_id: Optional[uuid.UUID] = Query(default=None, alias="workspaceId"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取用户的所有凭据列表

    Args:
        workspace_id: 工作空间ID（可选）

    Returns:
        凭据列表
    """
    service = ModelCredentialService(db)
    user_id = current_user.id
    credentials = await service.list_credentials(
        user_id=user_id,
        workspace_id=workspace_id,
    )
    return success_response(data=credentials, message="获取凭据列表成功")


@router.get("/{credential_id}")
async def get_credential(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取凭据详情

    Args:
        credential_id: 凭据ID

    Returns:
        凭据详情（不包含解密后的凭据）
    """
    service = ModelCredentialService(db)
    credential = await service.get_credential(credential_id, include_credentials=True)
    return success_response(data=credential, message="获取凭据详情成功")


@router.post("/{credential_id}/validate")
async def validate_credential(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    验证凭据

    Args:
        credential_id: 凭据ID

    Returns:
        验证结果
    """
    service = ModelCredentialService(db)
    result = await service.validate_credential(credential_id)
    return success_response(data=result, message="验证凭据完成")


@router.delete("/{credential_id}")
async def delete_credential(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    删除凭据

    Args:
        credential_id: 凭据ID
    """
    service = ModelCredentialService(db)
    await service.delete_credential(credential_id)
    return success_response(message="删除凭据成功")
