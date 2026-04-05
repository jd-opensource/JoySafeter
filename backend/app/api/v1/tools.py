"""
Tools API - List available builtin, MCP, and custom tools

Supports user-level tool queries
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
    List tools available to the user (user-level).

    Includes:
    - Builtin tools
    - User's MCP server tools
    - User's custom tools

    Args:
        category: filter by category
        tool_type: filter by tool type (builtin, mcp, custom)

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

    # ToolInfo.to_response() provides unified conversion
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
    List all builtin tools.

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
    Get tool details.

    Args:
        tool_id: tool ID (for MCP tools: server::tool_name)

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
