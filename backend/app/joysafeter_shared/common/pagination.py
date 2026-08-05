"""
Pagination utilities.
"""

from typing import Any, Callable, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Pagination parameters."""

    page: int = Field(default=1, ge=1, description="page number")
    page_size: int = Field(default=20, ge=1, le=100, description="items per page")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class ConversationMessagesPaginationParams(PaginationParams):
    """Conversation message pagination parameters, allowing longer history reads."""

    page_size: int = Field(default=20, ge=1, le=200, description="items per page")


class PageResult(BaseModel, Generic[T]):
    """Paginated result."""

    model_config = {"arbitrary_types_allowed": True}

    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int


class Paginator:
    """Paginator."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def paginate(
        self,
        query: Select,
        params: PaginationParams,
        transformer: Optional[Callable[[Any], Any]] = None,
    ) -> PageResult:
        """
        Execute a paginated query.

        Args:
            query: SQLAlchemy query
            params: pagination parameters
            transformer: optional result transformation function

        Returns:
            Paginated result
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
