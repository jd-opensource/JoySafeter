"""
Model usage statistics API
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
    period: str = Query(default="24h", description="Time range: 24h/7d/30d"),
    granularity: str = Query(default="hour", description="Time granularity: hour/day"),
    provider_name: Optional[str] = Query(default=None, description="Filter by provider"),
    model_name: Optional[str] = Query(default=None, description="Filter by model"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get model usage statistics."""
    service = ModelUsageService(db)
    stats = await service.get_stats(
        period=period,
        granularity=granularity,
        provider_name=provider_name,
        model_name=model_name,
    )
    return success_response(data=stats, message="Usage statistics retrieved")
