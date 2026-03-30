"""
ModelUsageLog Repository
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_usage_log import ModelUsageLog

from .base import BaseRepository


class ModelUsageLogRepository(BaseRepository[ModelUsageLog]):
    def __init__(self, db: AsyncSession):
        super().__init__(ModelUsageLog, db)

    async def get_summary(
        self,
        since: datetime,
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """聚合统计：调用次数、token数、平均响应时间、错误率"""
        query = select(
            func.count().label("total_calls"),
            func.sum(ModelUsageLog.input_tokens).label("total_input_tokens"),
            func.sum(ModelUsageLog.output_tokens).label("total_output_tokens"),
            func.avg(ModelUsageLog.total_time_ms).label("avg_response_time_ms"),
            func.sum(case((ModelUsageLog.status == "error", 1), else_=0)).label("error_count"),
        ).where(ModelUsageLog.created_at >= since)

        if provider_name:
            query = query.where(ModelUsageLog.provider_name == provider_name)
        if model_name:
            query = query.where(ModelUsageLog.model_name == model_name)

        result = await self.db.execute(query)
        row = result.one()

        total_calls = row.total_calls or 0
        error_count = row.error_count or 0

        return {
            "total_calls": total_calls,
            "total_input_tokens": row.total_input_tokens or 0,
            "total_output_tokens": row.total_output_tokens or 0,
            "avg_response_time_ms": round(float(row.avg_response_time_ms or 0), 1),
            "error_rate": round(error_count / total_calls, 4) if total_calls > 0 else 0.0,
        }

    async def get_timeline(
        self,
        since: datetime,
        granularity: str = "hour",
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按时间粒度分桶的调用数据"""
        trunc = func.date_trunc(granularity, ModelUsageLog.created_at)

        query = (
            select(
                trunc.label("timestamp"),
                func.count().label("calls"),
                func.sum(ModelUsageLog.input_tokens + ModelUsageLog.output_tokens).label("tokens"),
                func.avg(ModelUsageLog.total_time_ms).label("avg_time_ms"),
            )
            .where(ModelUsageLog.created_at >= since)
            .group_by(trunc)
            .order_by(trunc)
        )

        if provider_name:
            query = query.where(ModelUsageLog.provider_name == provider_name)
        if model_name:
            query = query.where(ModelUsageLog.model_name == model_name)

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "calls": row.calls or 0,
                "tokens": row.tokens or 0,
                "avg_time_ms": round(float(row.avg_time_ms or 0), 1),
            }
            for row in rows
        ]

    async def get_by_model(
        self,
        since: datetime,
        provider_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按模型分组统计，按调用次数降序"""
        query = (
            select(
                ModelUsageLog.model_name,
                func.count().label("calls"),
                func.sum(ModelUsageLog.input_tokens + ModelUsageLog.output_tokens).label("tokens"),
            )
            .where(ModelUsageLog.created_at >= since)
            .group_by(ModelUsageLog.model_name)
            .order_by(func.count().desc())
        )

        if provider_name:
            query = query.where(ModelUsageLog.provider_name == provider_name)

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "model_name": row.model_name,
                "calls": row.calls or 0,
                "tokens": row.tokens or 0,
            }
            for row in rows
        ]

    async def cleanup_old_logs(self, days: int = 90) -> int:
        """删除超过指定天数的旧日志"""
        from datetime import timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.db.execute(
            delete(ModelUsageLog).where(ModelUsageLog.created_at < cutoff)
        )
        await self.db.flush()
        return result.rowcount
