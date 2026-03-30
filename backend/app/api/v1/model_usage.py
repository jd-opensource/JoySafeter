"""
模型使用统计 API
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.response import success_response
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.model_usage_service import ModelUsageService

router = APIRouter(prefix="/v1/models", tags=["Model Usage"])


@router.get("/usage/stats")
async def get_usage_stats(
    period: str = Query(default="24h", description="时间范围: 24h/7d/30d"),
    granularity: str = Query(default="hour", description="时间粒度: hour/day"),
    provider_name: Optional[str] = Query(default=None, description="按供应商过滤"),
    model_name: Optional[str] = Query(default=None, description="按模型过滤"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取模型使用统计数据"""
    service = ModelUsageService(db)
    stats = await service.get_stats(
        period=period,
        granularity=granularity,
        provider_name=provider_name,
        model_name=model_name,
    )
    return success_response(data=stats, message="获取使用统计成功")
