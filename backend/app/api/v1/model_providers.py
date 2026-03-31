"""模型供应商管理API"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.response import success_response
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.model_provider_service import ModelProviderService

router = APIRouter(prefix="/v1/model-providers", tags=["ModelProviders"])


class ProviderDefaultsUpdate(BaseModel):
    """更新 Provider 默认参数请求"""

    default_parameters: Dict[str, Any] = Field(
        description="Provider 级默认参数，如 {temperature: 0.7, max_tokens: 2000}"
    )


@router.get("")
async def list_providers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有供应商列表"""
    service = ModelProviderService(db)
    providers = await service.get_all_providers()
    return success_response(data=providers, message="获取供应商列表成功")


class CustomProviderCreate(BaseModel):
    """添加自定义 Provider 请求"""

    model_name: str = Field(description="模型名称", examples=["gpt-4o"])
    credentials: Dict[str, Any] = Field(description="凭据字典（明文）")
    display_name: Optional[str] = Field(default=None, description="自定义显示名称")
    model_parameters: Optional[Dict[str, Any]] = Field(default=None, description="模型参数")
    validate_credentials: bool = Field(default=True, description="是否验证凭据")


@router.post("/custom")
async def add_custom_provider(
    payload: CustomProviderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """添加自定义 Provider（一步创建 provider + credential + model_instance）"""
    service = ModelProviderService(db)
    result = await service.add_custom_provider(
        user_id=current_user.id,
        credentials=payload.credentials,
        model_name=payload.model_name,
        display_name=payload.display_name,
        model_parameters=payload.model_parameters,
        validate=payload.validate_credentials,
    )
    return success_response(data=result, message="添加自定义供应商成功")


@router.get("/{provider_name}")
async def get_provider(
    provider_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取单个供应商详情"""
    service = ModelProviderService(db)
    provider = await service.get_provider(provider_name)

    if not provider:
        from app.common.exceptions import NotFoundException

        raise NotFoundException(f"供应商不存在: {provider_name}")

    return success_response(data=provider, message="获取供应商详情成功")


@router.patch("/{provider_name}/defaults")
async def update_provider_defaults(
    provider_name: str,
    payload: ProviderDefaultsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新 Provider 级默认参数"""
    service = ModelProviderService(db)
    provider = await service.update_provider_defaults(provider_name, payload.default_parameters)
    return success_response(data=provider, message="更新供应商默认参数成功")


@router.post("/sync")
async def sync_providers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """同步供应商、模型信息到数据库"""
    service = ModelProviderService(db)
    result = await service.sync_all()
    return success_response(data=result, message="同步完成")


@router.delete("/{provider_name}")
async def delete_provider(
    provider_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除供应商（仅限自定义供应商）"""
    service = ModelProviderService(db)
    await service.delete_provider(provider_name)
    return success_response(message=f"删除供应商 {provider_name} 成功")
