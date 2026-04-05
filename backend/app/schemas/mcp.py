"""
MCP Pydantic Schemas

Responsibilities:
- McpServerCreate/Update: input DTO
- McpServerResponse: output DTO
- ToolInfo/ToolResponse: tool information
- ConnectionTestResult: connection test result
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

# ==================== MCP Server ====================


class McpServerCreate(BaseModel):
    """Create MCP server (user level)."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    transport: str = "streamable-http"
    url: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    timeout: int = Field(default=30000, ge=1000, le=300000)
    retries: int = Field(default=3, ge=0, le=10)
    enabled: bool = True


class McpServerUpdate(BaseModel):
    """Update MCP server."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    transport: Optional[str] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    timeout: Optional[int] = Field(None, ge=1000, le=300000)
    retries: Optional[int] = Field(None, ge=0, le=10)
    enabled: Optional[bool] = None


class McpServerResponse(BaseModel):
    """MCP server response."""

    id: str
    name: str
    description: Optional[str] = None
    transport: str
    url: Optional[str] = None
    headers: dict = Field(default_factory=dict)
    timeout: int
    retries: int
    enabled: bool
    connection_status: Optional[str] = None
    last_connected: Optional[str] = None
    last_error: Optional[str] = None
    tool_count: int = 0
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, server) -> "McpServerResponse":
        """Create from database model."""
        return cls(
            id=str(server.id),
            name=server.name,
            description=server.description,
            transport=server.transport,
            url=server.url,
            headers=server.headers or {},
            timeout=server.timeout or 30000,
            retries=server.retries or 3,
            enabled=server.enabled,
            connection_status=server.connection_status,
            last_connected=server.last_connected.isoformat() if server.last_connected else None,
            last_error=server.last_error,
            tool_count=server.tool_count or 0,
            created_at=server.created_at.isoformat() if server.created_at else "",
            updated_at=server.updated_at.isoformat() if server.updated_at else "",
        )


# ==================== Connection Test ====================


class ConnectionTestResult(BaseModel):
    """Connection test result."""

    success: bool
    message: str = ""
    tool_count: int = 0
    tools: List[str] = Field(default_factory=list)
    latency_ms: Optional[float] = None


# ==================== Tool Info ====================


class ToolInfo(BaseModel):
    """
    Tool information (Service layer).

    Include ownership info for permission control.
    """

    id: str
    name: str
    label_name: Optional[str] = None
    description: str = ""
    tool_type: str  # builtin, mcp, custom
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    mcp_server: Optional[str] = None
    mcp_tool_name: Optional[str] = None
    owner_user_id: Optional[str] = None
    owner_workspace_id: Optional[str] = None
    enabled: bool = True

    def to_response(self) -> "ToolResponse":
        """Convert to API response."""
        # use label_name as display name
        display_name = self.label_name or self.name
        return ToolResponse(
            id=self.id,  # label_name (used for management and display)
            label=display_name.replace("_", " ").title(),
            name=self.name,
            labelName=self.label_name or self.name,
            description=self.description,
            tool_type=self.tool_type,
            category=self.category,
            tags=self.tags,
            mcp_server=self.mcp_server,
            mcp_tool_name=self.mcp_tool_name,
            enabled=self.enabled,
        )


class ToolResponse(BaseModel):
    """Tool response (API layer)."""

    id: str
    label: str
    name: str
    labelName: Optional[str] = None
    description: str = ""
    tool_type: str
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    mcp_server: Optional[str] = None
    mcp_tool_name: Optional[str] = None
    enabled: bool = True
