"""
Base service.
"""

from typing import Generic, TypeVar

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.boundary_errors import log_boundary_failure_loguru

T = TypeVar("T")


class BaseService(Generic[T]):
    """
    Base service class.

    Provide common infrastructure for the business-logic layer.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def commit(self):
        """Commit the transaction."""
        await self.db.commit()

    async def rollback(self):
        """Roll back the transaction."""
        await self.db.rollback()

    async def safe_commit(self):
        """Commit with automatic rollback on failure."""
        try:
            await self.db.commit()
        except Exception as exc:
            log_boundary_failure_loguru(
                logger,
                boundary="domain_service",
                code="DOMAIN_DB_COMMIT_FAILED",
                message="DB commit failed, rolling back",
                operation="safe_commit",
                error=exc,
            )
            await self.db.rollback()
            raise
