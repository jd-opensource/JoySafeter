"""
Model usage statistics service.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.model import ModelType
from app.models.enums import ModelUsageSource
from app.repositories.model_usage_log import ModelUsageLogRepository

from .base import BaseService


class ModelUsageService(BaseService):
    """Model usage statistics service."""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.repo = ModelUsageLogRepository(db)

    async def log_usage(
        self,
        provider_name: str,
        model_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_time_ms: float = 0.0,
        ttft_ms: Optional[float] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        user_id: Optional[str] = None,
        model_type: str = ModelType.CHAT,
        source: str = ModelUsageSource.CHAT,
    ) -> None:
        """Record a model invocation log; on failure only log a warning, do not raise."""
        try:
            await self.repo.create(
                {
                    "provider_name": provider_name,
                    "model_name": model_name,
                    "model_type": model_type,
                    "user_id": user_id,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_time_ms": total_time_ms,
                    "ttft_ms": ttft_ms,
                    "status": status,
                    "error_message": error_message,
                    "source": source,
                }
            )
            await self.db.commit()
        except Exception as e:
            from loguru import logger

            logger.warning(f"[ModelUsageService] Failed to log usage: {e}")

    async def get_stats(
        self,
        period: str = "24h",
        granularity: str = "hour",
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get usage statistics."""
        period_map = {
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
        }
        delta = period_map.get(period, timedelta(hours=24))
        since = datetime.now(timezone.utc) - delta

        summary = await self.repo.get_summary(since, provider_name, model_name)
        timeline = await self.repo.get_timeline(since, granularity, provider_name, model_name)
        by_model = await self.repo.get_by_model(since, provider_name)

        return {
            "summary": summary,
            "timeline": timeline,
            "by_model": by_model,
        }

    async def cleanup(self, days: int = 90) -> int:
        """Clean up old logs."""
        count = await self.repo.cleanup_old_logs(days)
        await self.db.commit()
        return count
