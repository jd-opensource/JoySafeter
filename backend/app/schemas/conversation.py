"""
Conversation Pydantic schemas

Request and response validation for conversation management.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.validators import EnhancedBaseModel


class ConversationCreate(EnhancedBaseModel):
    """Create conversation request."""

    # user_id is obtained from authentication; no longer needed in the request
    title: str = Field(default="New Conversation", min_length=1, max_length=200, description="conversation title")
    metadata: dict[str, Any] = Field(default_factory=dict, description="metadata")


class ConversationUpdate(EnhancedBaseModel):
    """Update conversation request."""

    title: str | None = Field(None, min_length=1, max_length=200, description="conversation title")
    metadata: dict[str, Any] | None = Field(None, description="metadata")


class ConversationResponse(BaseModel):
    """Conversation response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="conversation ID")
    thread_id: str = Field(..., description="thread ID")
    user_id: str = Field(..., description="user ID (text)")
    title: str = Field(..., description="conversation title")
    metadata: dict[str, Any] = Field(default_factory=dict, description="metadata")
    created_at: datetime = Field(..., description="creation time")
    updated_at: datetime = Field(..., description="update time")
    message_count: int = Field(default=0, description="message count")


class ConversationDetailResponse(BaseModel):
    """Conversation detail response."""

    conversation: ConversationResponse
    messages: list[dict[str, Any]] = Field(default_factory=list, description="message list")


class ConversationExportResponse(BaseModel):
    """Conversation export response."""

    conversation: dict[str, Any]
    messages: list[dict[str, Any]]
    state: dict[str, Any] | None = None


class ConversationImportRequest(BaseModel):
    """Conversation import request."""

    # user_id is obtained from authentication; no longer needed in the request
    data: dict[str, Any] = Field(..., description="import data")


class CheckpointResponse(BaseModel):
    """Checkpoint response."""

    thread_id: str
    checkpoints: list[dict[str, Any]]


class SearchRequest(BaseModel):
    """Search request."""

    # user_id is obtained from authentication; no longer needed in the request
    query: str = Field(..., description="search keyword")
    skip: int = Field(default=0, ge=0, description="number to skip")
    limit: int = Field(default=20, ge=1, le=100, description="number to return")


class SearchResponse(BaseModel):
    """Search response."""

    query: str
    results: list[dict[str, Any]]


class UserStatsResponse(BaseModel):
    """User statistics response."""

    user_id: str
    total_conversations: int
    total_messages: int
    recent_conversations: list[dict[str, Any]]


class ConversationMessageResponse(BaseModel):
    """Conversation message response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="message ID")
    role: str = Field(..., description="message role")
    content: str = Field(..., description="message content")
    metadata: dict[str, Any] = Field(default_factory=dict, description="metadata")
    created_at: datetime = Field(..., description="creation time")
