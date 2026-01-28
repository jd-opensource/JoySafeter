"""
分页工具
"""

from typing import Any, Callable, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

T = TypeVar("T")


class PaginationParams(BaseModel):
    """分页参数"""

    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PageResult(BaseModel, Generic[T]):
    """分页结果"""

    model_config = {"arbitrary_types_allowed": True}

    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int


class Paginator:
    """分页器"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def paginate(
        self,
        query: Select,
        params: PaginationParams,
        transformer: Optional[Callable[[Any], Any]] = None,
    ) -> PageResult:
        """
        执行分页查询

        Args:
            query: SQLAlchemy 查询
            params: 分页参数
            transformer: 可选的结果转换函数

        Returns:
            分页结果
        """
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        pages = (total + params.page_size - 1) // params.page_size if params.page_size > 0 else 0

        paginated_query = query.offset(params.offset).limit(params.limit)
        result = await self.db.execute(paginated_query)
        items = result.scalars().all()

        if transformer is not None:
            items = [transformer(item) for item in items]

        return PageResult(
            items=list(items),
            total=total,
            page=params.page,
            page_size=params.page_size,
            pages=pages,
        )
