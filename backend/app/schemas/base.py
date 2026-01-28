from typing import Generic, Optional, TypeVar

from pydantic import BaseModel as PydanticBaseModel

T = TypeVar("T")


class BaseResponse(PydanticBaseModel, Generic[T]):
    """所有API响应的基类"""

    success: bool
    code: int  # 状态码 (200=成功, 其他=错误码)
    msg: str  # 用户友好的消息
    data: Optional[T] = None
    err: Optional[T] = None
