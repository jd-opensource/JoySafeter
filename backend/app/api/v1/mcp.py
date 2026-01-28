"""
MCP Server API - MCP 服务器管理

遵循项目规范:
- Query 参数: snake_case (alias 支持 camelCase)
- 响应体: camelCase (前端兼容)
- 返回格式: {"success": True, "data": ...}
"""

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.exceptions import BadRequestException, NotFoundException
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.mcp_client_service import McpConnectionConfig, get_mcp_client
from app.services.tool_service import ToolService

router = APIRouter(prefix="/v1/mcp", tags=["MCP Servers"])


# ==================== Request Schemas ====================


class McpServerCreateRequest(BaseModel):
    """创建 MCP 服务器"""

    model_config = {"populate_by_name": True}

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    transport: str = "streamable-http"
    url: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    timeout: int = Field(default=30000, ge=1000, le=300000)
    retries: int = Field(default=3, ge=0, le=10)
    enabled: bool = True


class McpServerUpdateRequest(BaseModel):
    """更新 MCP 服务器"""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    transport: Optional[str] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    timeout: Optional[int] = Field(None, ge=1000, le=300000)
    retries: Optional[int] = Field(None, ge=0, le=10)
    enabled: Optional[bool] = None


class ToggleRequest(BaseModel):
    enabled: bool


class McpTestRequest(BaseModel):
    """连接测试请求"""

    transport: str = "streamable-http"
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    timeout: int = 30000


class McpToolExecuteRequest(BaseModel):
    """工具执行请求

    使用 serverName 查找服务器（每个用户唯一）。
    """

    serverName: str = Field(..., description="Server name (unique per user)")
    toolName: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


# ==================== Serialization (camelCase for frontend) ====================


def _serialize_server(server) -> Dict[str, Any]:
    """序列化服务器为 camelCase 响应"""
    return {
        "id": str(server.id),
        "name": server.name,
        "description": server.description,
        "transport": server.transport,
        "url": server.url,
        "headers": server.headers or {},
        "timeout": server.timeout or 30000,
        "retries": server.retries or 3,
        "enabled": server.enabled,
        "connectionStatus": server.connection_status,
        "lastConnected": server.last_connected.isoformat() if server.last_connected else None,
        "lastError": server.last_error,
        "toolCount": server.tool_count or 0,
        "createdAt": server.created_at.isoformat() if server.created_at else None,
        "updatedAt": server.updated_at.isoformat() if server.updated_at else None,
    }


def _serialize_tool(tool_info) -> Dict[str, Any]:
    """序列化工具为 camelCase 响应"""
    display_name = tool_info.label_name or tool_info.name
    return {
        "id": tool_info.id,
        "name": tool_info.name,
        "labelName": display_name,
        "label": display_name.replace("_", " ").title(),
        "description": tool_info.description,
        "toolType": tool_info.tool_type,
        "category": tool_info.category,
        "tags": tool_info.tags,
        "mcpServer": tool_info.mcp_server,
        "mcpToolName": tool_info.mcp_tool_name,
        "enabled": tool_info.enabled,
    }


# ==================== Server CRUD ====================


@router.get("/servers")
async def list_mcp_servers(
    enabled_only: bool = Query(False, alias="enabledOnly"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的 MCP 服务器列表（用户级别）"""
    service = ToolService(db)
    servers = await service.list_mcp_servers(
        user_id=current_user.id,
        enabled_only=enabled_only,
    )

    return {"success": True, "data": {"servers": [_serialize_server(s) for s in servers]}}


@router.post("/servers")
async def create_mcp_server(
    request: McpServerCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建 MCP 服务器"""
    from loguru import logger

    from app.schemas.mcp import McpServerCreate

    logger.info(f"[MCP] Creating server - user_id={current_user.id}, name={request.name}")

    service = ToolService(db)

    server = await service.create_mcp_server(
        user_id=current_user.id,
        data=McpServerCreate(
            name=request.name,
            description=request.description,
            transport=request.transport,
            url=request.url,
            headers=request.headers,
            timeout=request.timeout,
            retries=request.retries,
            enabled=request.enabled,
        ),
    )

    logger.info(f"[MCP] Server created - id={server.id}, name={server.name}")
    return {"success": True, "data": {"serverId": str(server.id)}}


@router.get("/servers/{server_id}")
async def get_mcp_server(
    server_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取 MCP 服务器详情"""
    service = ToolService(db)
    server = await service.get_mcp_server(server_id=server_id, user_id=current_user.id)

    return {"success": True, "data": _serialize_server(server)}


@router.put("/servers/{server_id}")
async def update_mcp_server(
    server_id: UUID,
    request: McpServerUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新 MCP 服务器"""
    from app.schemas.mcp import McpServerUpdate

    service = ToolService(db)
    server = await service.update_mcp_server(
        server_id=server_id,
        user_id=current_user.id,
        data=McpServerUpdate(
            name=request.name,
            description=request.description,
            transport=request.transport,
            url=request.url,
            headers=request.headers,
            timeout=request.timeout,
            retries=request.retries,
            enabled=request.enabled,
        ),
    )

    return {"success": True, "data": _serialize_server(server)}


@router.delete("/servers/{server_id}")
async def delete_mcp_server(
    server_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除 MCP 服务器"""
    service = ToolService(db)
    await service.delete_mcp_server(server_id=server_id, user_id=current_user.id)

    return {"success": True, "data": None}


# ==================== Server Actions ====================


@router.post("/servers/{server_id}/toggle")
async def toggle_mcp_server(
    server_id: UUID,
    request: ToggleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """启用/禁用 MCP 服务器"""
    service = ToolService(db)
    server = await service.toggle_mcp_server(
        server_id=server_id,
        user_id=current_user.id,
        enabled=request.enabled,
    )

    return {"success": True, "data": _serialize_server(server)}


@router.post("/servers/{server_id}/test")
async def test_server_connection(
    server_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """测试已存在服务器的连接"""
    service = ToolService(db)
    result = await service.test_connection(server_id=server_id, user_id=current_user.id)

    return {
        "success": True,
        "data": {
            "success": result.success,
            "message": result.message,
            "toolCount": result.tool_count,
            "tools": result.tools,
            "latencyMs": result.latency_ms,
        },
    }


@router.post("/servers/{server_id}/refresh")
async def refresh_server_tools(
    server_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """刷新服务器工具列表"""
    service = ToolService(db)
    tools = await service.refresh_server_tools(server_id=server_id, user_id=current_user.id)

    return {"success": True, "data": [_serialize_tool(t) for t in tools]}


@router.get("/servers/{server_id}/tools")
async def list_server_tools(
    server_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取服务器的工具列表"""
    service = ToolService(db)
    tools = await service.get_server_tools(server_id=server_id, user_id=current_user.id)

    return {"success": True, "data": [_serialize_tool(t) for t in tools]}


# ==================== Connection Test & Tools ====================


@router.post("/test")
async def test_connection(
    request: McpTestRequest,
    current_user: User = Depends(get_current_user),
):
    """测试连接 (创建前)"""
    mcp_client = get_mcp_client()
    config = McpConnectionConfig(
        url=request.url or "",
        transport=request.transport,
        timeout_seconds=request.timeout // 1000,
        headers=request.headers or {},
    )

    # For test connection before creation, pass None (will create temporary server)
    result = await mcp_client.test_connection(config, server=None)

    return {
        "success": True,
        "data": {
            "success": result.success,
            "error": result.error,
            "tools": [{"name": t.name, "description": t.description or ""} for t in result.tools],
            "latencyMs": result.latency_ms,
        },
    }


@router.get("/tools")
async def discover_tools(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发现当前用户的所有 MCP 工具（用户级别）"""
    service = ToolService(db)

    servers = await service.list_mcp_servers(
        user_id=current_user.id,
        enabled_only=True,
    )

    all_tools = []
    for server in servers:
        tools = await service.get_server_tools(server_id=server.id, user_id=current_user.id)
        for tool in tools:
            all_tools.append(
                {
                    "serverName": server.name,
                    "name": tool.name,
                    "labelName": tool.label_name or tool.name,
                    "description": tool.description,
                }
            )

    return {"success": True, "data": {"tools": all_tools}}


@router.post("/tools/execute")
async def execute_tool(
    request: McpToolExecuteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行 MCP 工具

    使用 serverName 查找真实的 MCP server instance，并验证权限和状态。
    确保使用真实的 server instance 和 tool_name 执行工具。
    """
    from loguru import logger

    from app.core.tools.mcp_tool_utils import get_mcp_tool_with_instance

    logger.debug(
        f"[execute_tool] Executing MCP tool: serverName={request.serverName}, "
        f"toolName={request.toolName}, user_id={current_user.id}"
    )

    # Get tool with instance validation (validates server exists, enabled, and user permissions)
    tool = await get_mcp_tool_with_instance(
        server_name=request.serverName,
        tool_name=request.toolName,
        user_id=current_user.id,
        db=db,
    )

    if not tool:
        # get_mcp_tool_with_instance already logs detailed warnings
        raise NotFoundException(
            f"MCP tool '{request.toolName}' not found on server '{request.serverName}' or server is not accessible"
        )

    try:
        logger.debug(
            f"[execute_tool] Invoking tool '{request.toolName}' on server '{request.serverName}' "
            f"with arguments: {request.arguments}"
        )
        result = await tool.ainvoke(request.arguments)
        logger.debug(f"[execute_tool] Tool '{request.toolName}' executed successfully on server '{request.serverName}'")
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(
            f"[execute_tool] Tool execution failed: serverName={request.serverName}, "
            f"toolName={request.toolName}, error={str(e)}",
            exc_info=True,
        )
        raise BadRequestException(f"Tool execution failed: {str(e)}")
