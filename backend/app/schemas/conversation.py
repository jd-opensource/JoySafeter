"""
会话相关的 Pydantic Schema

用于会话管理的请求和响应数据验证
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.validators import EnhancedBaseModel


class ConversationCreate(EnhancedBaseModel):
    """创建会话请求"""

    # user_id 从认证中获取，不再需要在请求中提供
    title: str = Field(default="New Conversation", min_length=1, max_length=200, description="会话标题")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")


class ConversationUpdate(EnhancedBaseModel):
    """更新会话请求"""

    title: str | None = Field(None, min_length=1, max_length=200, description="会话标题")
    metadata: dict[str, Any] | None = Field(None, description="元数据")


class ConversationResponse(BaseModel):
    """会话响应"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="会话ID")
    thread_id: str = Field(..., description="线程ID")
    user_id: str = Field(..., description="用户ID(text)")
    title: str = Field(..., description="会话标题")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    message_count: int = Field(default=0, description="消息数量")


class ConversationDetailResponse(BaseModel):
    """会话详情响应"""

    conversation: ConversationResponse
    messages: list[dict[str, Any]] = Field(default_factory=list, description="消息列表")


class ConversationExportResponse(BaseModel):
    """会话导出响应"""

    conversation: dict[str, Any]
    messages: list[dict[str, Any]]
    state: dict[str, Any] | None = None


class ConversationImportRequest(BaseModel):
    """会话导入请求"""

    # user_id 从认证中获取，不再需要在请求中提供
    data: dict[str, Any] = Field(..., description="导入数据")


class CheckpointResponse(BaseModel):
    """检查点响应"""

    thread_id: str
    checkpoints: list[dict[str, Any]]


class SearchRequest(BaseModel):
    """搜索请求"""

    # user_id 从认证中获取，不再需要在请求中提供
    query: str = Field(..., description="搜索关键词")
    skip: int = Field(default=0, ge=0, description="跳过数量")
    limit: int = Field(default=20, ge=1, le=100, description="返回数量")


class SearchResponse(BaseModel):
    """搜索响应"""

    query: str
    results: list[dict[str, Any]]


class UserStatsResponse(BaseModel):
    """用户统计响应"""

    user_id: str
    total_conversations: int
    total_messages: int
    recent_conversations: list[dict[str, Any]]


class ConversationMessageResponse(BaseModel):
    """会话消息响应"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="消息ID")
    role: str = Field(..., description="消息角色")
    content: str = Field(..., description="消息内容")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")
    created_at: datetime = Field(..., description="创建时间")
