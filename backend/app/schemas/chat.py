import uuid
from typing import Any

from pydantic import BaseModel as PydanticBaseModel
from pydantic import Field


class ChatRequest(PydanticBaseModel):
    """对话请求"""

    message: str = Field(..., description="用户消息")
    thread_id: str | None = Field(None, description="会话线程ID，不提供则创建新会话")
    graph_id: uuid.UUID | None = Field(None, description="图ID，使用指定的图进行对话")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")
    # user_id 从认证中获取，不再需要在请求中提供


class ChatResponse(PydanticBaseModel):
    """对话响应"""

    thread_id: str = Field(..., description="会话线程ID")
    response: str = Field(..., description="助手回复")
    duration_ms: int = Field(..., description="执行时长(毫秒)")
