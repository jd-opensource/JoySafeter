"""
模型凭据管理API
"""

import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.response import success_response
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.model_credential_service import ModelCredentialService

router = APIRouter(prefix="/v1/model-credentials", tags=["ModelCredentials"])


class CredentialCreate(BaseModel):
    """创建/更新凭据请求（仅限内置 provider）"""

    provider_name: str = Field(description="供应商名称", examples=["openaiapicompatible"])
    credentials: Dict[str, Any] = Field(..., description="凭据字典（明文）")
    should_validate: bool = Field(default=True, alias="validate", description="是否验证凭据")


@router.post("")
async def create_or_update_credential(
    payload: CredentialCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建或更新内置 provider 的凭据"""
    service = ModelCredentialService(db)
    credential = await service.upsert_credential(
        user_id=current_user.id,
        provider_name=payload.provider_name,
        credentials=payload.credentials,
        validate=payload.should_validate,
    )
    return success_response(data=credential, message="创建/更新凭据成功")


@router.get("")
async def list_credentials(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取凭据列表（全局，与 workspace 无关）
    """
    service = ModelCredentialService(db)
    credentials = await service.list_credentials()
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
