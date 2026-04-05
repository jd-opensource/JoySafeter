"""
Base service.
"""

from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

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
