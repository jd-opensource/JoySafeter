"""
统一响应格式
"""

from datetime import datetime
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应格式"""

    success: bool = True
    code: int = 200
    message: str = "Success"
    data: Optional[T] = None
    timestamp: str = ""

    def __init__(self, **data):
        if "timestamp" not in data or not data["timestamp"]:
            data["timestamp"] = datetime.utcnow().isoformat() + "Z"
        super().__init__(**data)


class PaginatedData(BaseModel, Generic[T]):
    """分页数据"""

    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int


def success_response(
    data: Any = None,
    message: str = "Success",
    code: int = 200,
) -> dict:
    """成功响应"""
    return {
        "success": True,
        "code": code,
        "message": message,
        "data": data,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def error_response(
    message: str = "Error",
    code: int = 400,
    data: Any = None,
) -> dict:
    """错误响应"""
    return {
        "success": False,
        "code": code,
        "message": message,
        "data": data,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def paginated_response(
    items: List[Any],
    total: int,
    page: int = 1,
    page_size: int = 20,
    message: str = "Success",
) -> dict:
    """分页响应"""
    pages = (total + page_size - 1) // page_size if page_size > 0 else 0
    return success_response(
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        },
        message=message,
    )
