"""
Pydantic Schemas
"""

from .base import BaseResponse
from .chat import ChatRequest, ChatResponse
from .common import PaginatedResponse
from .conversation import (
    CheckpointResponse,
    ConversationCreate,
    ConversationDetailResponse,
    ConversationExportResponse,
    ConversationImportRequest,
    ConversationMessageResponse,
    ConversationResponse,
    ConversationUpdate,
    SearchRequest,
    SearchResponse,
    UserStatsResponse,
)
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
    "ConversationCreate",
    "ConversationUpdate",
    "ConversationResponse",
    "ConversationDetailResponse",
    "ConversationExportResponse",
    "ConversationImportRequest",
    "CheckpointResponse",
    "ChatRequest",
    "ChatResponse",
    "SearchRequest",
    "SearchResponse",
    "UserStatsResponse",
    "ConversationMessageResponse",
    # MCP Schemas
    "McpServerCreate",
    "McpServerUpdate",
    "McpServerResponse",
    "ConnectionTestResult",
    "ToolInfo",
    "ToolResponse",
    # TODO: Phase 5 cleanup - Graph Deployment Version Schemas removed
    # "GraphDeploymentVersionResponse",
    # "GraphDeploymentVersionResponseCamel",
    # "GraphDeploymentVersionListResponse",
    # "GraphDeployRequest",
    # "GraphDeployResponse",
    # "GraphRevertResponse",
    # "GraphRenameVersionRequest",
]
