"""
Pydantic Schemas
"""

from .base import BaseResponse
from .chat import ChatRequest, ChatResponse
from .common import PaginatedResponse
from .mcp import (
    ConnectionTestResult,
    McpServerCreate,
    McpServerResponse,
    McpServerUpdate,
    ToolInfo,
    ToolResponse,
)
from .user import UserResponse

__all__ = [
    "BaseResponse",
    "PaginatedResponse",
    "UserResponse",
    "ChatRequest",
    "ChatResponse",
    # MCP Schemas
    "McpServerCreate",
    "McpServerUpdate",
    "McpServerResponse",
    "ConnectionTestResult",
    "ToolInfo",
    "ToolResponse",
]
