"""模型供应商管理API"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import success_response

# from app.common.dependencies import get_current_user
# from app.models.auth import AuthUser as User
from app.core.database import get_db
from app.services.model_provider_service import ModelProviderService

router = APIRouter(prefix="/v1/model-providers", tags=["ModelProviders"])


@router.get("")
async def list_providers(
    db: AsyncSession = Depends(get_db),
    # current_user: User = Depends(get_current_user),
):
    """
    获取所有供应商列表

    Returns:
        供应商列表，包含：
        - provider_name: 供应商名称
        - display_name: 显示名称
        - supported_model_types: 支持的模型类型列表
        - credential_schema: 凭据表单规则
        - config_schemas: 配置规则（按模型类型）
        - is_enabled: 是否启用
    """
    service = ModelProviderService(db)
    providers = await service.get_all_providers()
    return success_response(data=providers, message="获取供应商列表成功")


@router.get("/{provider_name}")
async def get_provider(
    provider_name: str,
    db: AsyncSession = Depends(get_db),
    # current_user: User = Depends(get_current_user),
):
    """
    获取单个供应商详情

    Args:
        provider_name: 供应商名称

    Returns:
        供应商详情
    """
    service = ModelProviderService(db)
    provider = await service.get_provider(provider_name)

    if not provider:
        from app.common.exceptions import NotFoundException

        raise NotFoundException(f"供应商不存在: {provider_name}")

    return success_response(data=provider, message="获取供应商详情成功")


@router.post("/sync")
async def sync_providers(
    db: AsyncSession = Depends(get_db),
    # current_user: User = Depends(get_current_user),
):
    """
    同步供应商、模型和认证信息到数据库

    功能:
    - 同步供应商信息（从工厂同步）
    - 同步模型信息（从工厂同步到 model_instance 表，全局记录）

    Returns:
        同步结果统计
    """
    service = ModelProviderService(db)
    result = await service.sync_all()
    return success_response(data=result, message="同步完成")
