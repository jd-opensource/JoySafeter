import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel as PydanticBaseModel
from pydantic import Field


class ChatRequest(PydanticBaseModel):
    """对话请求"""

    message: str = Field(..., description="用户消息")
    thread_id: Optional[str] = Field(None, description="会话线程ID，不提供则创建新会话")
    graph_id: Optional[uuid.UUID] = Field(None, description="图ID，使用指定的图进行对话")
    mode: Optional[Literal["skill_creator"]] = Field(None, description="可选的对话模式")
    edit_skill_id: Optional[str] = Field(None, description="编辑已有 Skill 时的 Skill ID")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")
    # user_id 从认证中获取，不再需要在请求中提供


class ChatResponse(PydanticBaseModel):
    """对话响应"""

    thread_id: str = Field(..., description="会话线程ID")
    response: str = Field(..., description="助手回复")
    duration_ms: int = Field(..., description="执行时长(毫秒)")
