"""
Tools API - List available builtin, MCP, and custom tools

支持用户级别的工具查询
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.response import success_response
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.tool_service import ToolService

router = APIRouter(prefix="/v1/tools", tags=["Tools"])


@router.get("")
async def list_tools(
    category: Optional[str] = Query(None, description="Filter by category"),
    tool_type: Optional[str] = Query(None, description="Filter by tool type (builtin, mcp, custom)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取用户可用的工具列表（用户级别）

    包括:
    - 内置工具 (builtin)
    - 用户的 MCP 服务器工具
    - 用户的自定义工具

    Args:
        category: 按类别过滤
        tool_type: 按工具类型过滤 (builtin, mcp, custom)

    Returns:
        {"success": True, "data": [ToolResponse, ...]}
    """
    service = ToolService(db)

    # Get tools for user scope (returns List[ToolInfo])
    tools = service.get_available_tools(
        user_id=current_user.id,
        tool_type=tool_type,
        category=category,
    )

    # ToolInfo.to_response() 统一转换
    return success_response(
        data=[t.to_response() for t in tools],
        message="Tools retrieved successfully",
    )


@router.get("/builtin")
async def list_builtin_tools(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取所有内置工具

    Returns:
        {"success": True, "data": [ToolResponse, ...]}
    """
    service = ToolService(db)

    tools = service.get_builtin_tools()

    return success_response(
        data=[t.to_response() for t in tools],
        message="Builtin tools retrieved successfully",
    )


@router.get("/{tool_id}")
async def get_tool(
    tool_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取工具详情

    Args:
        tool_id: 工具 ID (对于 MCP 工具: server::tool_name)

    Returns:
        {"success": True, "data": ToolResponse}
    """
    service = ToolService(db)

    tool = service.get_tool_by_key(tool_id)

    if not tool:
        return success_response(data=None, message="Tool not found")

    return success_response(
        data=tool.to_response(),
        message="Tool retrieved successfully",
    )
