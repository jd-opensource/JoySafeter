"""
Base Repository -- generic CRUD operations
"""

import uuid
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """
    Base Repository providing generic CRUD operations.

    Usage:
        class UserRepository(BaseRepository[User]):
            def __init__(self, db: AsyncSession):
                super().__init__(User, db)
    """

    def __init__(self, model: Type[T], db: AsyncSession):
        self.model = model
        self.db = db

    async def get(self, id: uuid.UUID, relations: Optional[List[str]] = None) -> Optional[T]:
        """Get a record by ID."""
        query = select(self.model).where(self.model.id == id)  # type: ignore[attr-defined]

        if relations:
            for relation in relations:
                query = query.options(selectinload(getattr(self.model, relation)))

        result = await self.db.execute(query)
        return result.scalar_one_or_none()  # type: ignore[return-value]

    async def get_by(self, **kwargs) -> Optional[T]:
        """Get a single record by filter conditions."""
        query = select(self.model)
        for key, value in kwargs.items():
            query = query.where(getattr(self.model, key) == value)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def find(
        self,
        filters: Optional[Dict[str, Any]] = None,
        relations: Optional[List[str]] = None,
        order_by: Optional[str] = None,
        order_desc: bool = True,
    ) -> List[T]:
        """Query multiple records."""
        query = select(self.model)

        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    query = query.where(getattr(self.model, key) == value)

        if relations:
            for relation in relations:
                if hasattr(self.model, relation):
                    query = query.options(selectinload(getattr(self.model, relation)))

        if order_by and hasattr(self.model, order_by):
            column = getattr(self.model, order_by)
            query = query.order_by(column.desc() if order_desc else column.asc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(self, data: Dict[str, Any]) -> T:
        """Create a record."""
        instance = self.model(**data)
        self.db.add(instance)
        await self.db.flush()
        await self.db.refresh(instance)
        return instance

    async def update(self, id: uuid.UUID, data: Dict[str, Any]) -> Optional[T]:
        """Update a record."""
        instance = await self.get(id)
        if not instance:
            return None

        for key, value in data.items():
            if hasattr(instance, key):
                setattr(instance, key, value)

        await self.db.flush()
        await self.db.refresh(instance)
        return instance

    async def delete(self, id: uuid.UUID) -> bool:
        """Delete a record."""
        instance = await self.get(id)
        if not instance:
            return False

        await self.db.delete(instance)
        await self.db.flush()
        return True

    async def soft_delete(self, id: uuid.UUID) -> bool:
        """Soft-delete a record."""
        from datetime import datetime, timezone

        instance = await self.get(id)
        if not instance:
            return False

        if hasattr(instance, "deleted_at"):
            instance.deleted_at = datetime.now(timezone.utc)
            await self.db.flush()
            return True

        return await self.delete(id)

    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """Count records."""
        query = select(func.count()).select_from(self.model)

        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    query = query.where(getattr(self.model, key) == value)

        result = await self.db.execute(query)
        return result.scalar() or 0
