"""
MCP 相关的 Pydantic Schemas

职责划分:
- McpServerCreate/Update: 输入 DTO
- McpServerResponse: 输出 DTO
- ToolInfo/ToolResponse: 工具信息
- ConnectionTestResult: 连接测试结果
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

# ==================== MCP Server ====================


class McpServerCreate(BaseModel):
    """创建 MCP 服务器（用户级别）"""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    transport: str = "streamable-http"
    url: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    timeout: int = Field(default=30000, ge=1000, le=300000)
    retries: int = Field(default=3, ge=0, le=10)
    enabled: bool = True


class McpServerUpdate(BaseModel):
    """更新 MCP 服务器"""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    transport: Optional[str] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    timeout: Optional[int] = Field(None, ge=1000, le=300000)
    retries: Optional[int] = Field(None, ge=0, le=10)
    enabled: Optional[bool] = None


class McpServerResponse(BaseModel):
    """MCP 服务器响应"""

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
        """从数据库模型创建"""
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
    """连接测试结果"""

    success: bool
    message: str = ""
    tool_count: int = 0
    tools: List[str] = Field(default_factory=list)
    latency_ms: Optional[float] = None


# ==================== Tool Info ====================


class ToolInfo(BaseModel):
    """
    工具信息 (Service 层)

    包含所有权信息，用于权限控制
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
        """转换为 API 响应"""
        # 使用 label_name 作为显示名称
        display_name = self.label_name or self.name
        return ToolResponse(
            id=self.id,  # label_name（用于管理和显示）
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
    """工具响应 (API 层)"""

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
