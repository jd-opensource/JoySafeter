"""
基础 Repository - 通用 CRUD 操作
"""

import uuid
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.pagination import PageResult, PaginationParams
from app.core.database import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """
    基础 Repository，提供通用 CRUD 操作

    Usage:
        class UserRepository(BaseRepository[User]):
            def __init__(self, db: AsyncSession):
                super().__init__(User, db)
    """

    def __init__(self, model: Type[T], db: AsyncSession):
        self.model = model
        self.db = db

    async def get(self, id: uuid.UUID, relations: Optional[List[str]] = None) -> Optional[T]:
        """根据 ID 获取记录"""
        query = select(self.model).where(self.model.id == id)  # type: ignore[attr-defined]

        if relations:
            for relation in relations:
                query = query.options(selectinload(getattr(self.model, relation)))

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by(self, **kwargs) -> Optional[T]:
        """根据条件获取单条记录"""
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
        """查询多条记录"""
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

    async def find_paginated(
        self,
        params: PaginationParams,
        filters: Optional[Dict[str, Any]] = None,
        relations: Optional[List[str]] = None,
        order_by: str = "created_at",
        order_desc: bool = True,
    ) -> PageResult[T]:
        """分页查询"""
        query = select(self.model)

        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    if value is None:
                        query = query.where(getattr(self.model, key).is_(None))
                    else:
                        query = query.where(getattr(self.model, key) == value)

        if relations:
            for relation in relations:
                if hasattr(self.model, relation):
                    query = query.options(selectinload(getattr(self.model, relation)))

        if order_by and hasattr(self.model, order_by):
            column = getattr(self.model, order_by)
            query = query.order_by(column.desc() if order_desc else column.asc())

        # 计算总数
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # 分页
        pages = (total + params.page_size - 1) // params.page_size if params.page_size > 0 else 0
        paginated_query = query.offset(params.offset).limit(params.limit)
        result = await self.db.execute(paginated_query)
        items = list(result.scalars().all())

        return PageResult(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
            pages=pages,
        )

    async def create(self, data: Dict[str, Any]) -> T:
        """创建记录"""
        instance = self.model(**data)
        self.db.add(instance)
        await self.db.flush()
        await self.db.refresh(instance)
        return instance

    async def update(self, id: uuid.UUID, data: Dict[str, Any]) -> Optional[T]:
        """更新记录"""
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
        """删除记录"""
        instance = await self.get(id)
        if not instance:
            return False

        await self.db.delete(instance)
        await self.db.flush()
        return True

    async def soft_delete(self, id: uuid.UUID) -> bool:
        """软删除记录"""
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
        """计数"""
        query = select(func.count()).select_from(self.model)

        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    query = query.where(getattr(self.model, key) == value)

        result = await self.db.execute(query)
        return result.scalar() or 0

    async def exists(self, **kwargs) -> bool:
        """检查是否存在"""
        return await self.get_by(**kwargs) is not None
