"""
Tool routes for web visualization.
Currently uses MOCK data.
"""

from typing import List

from fastapi import APIRouter, HTTPException
from loguru import logger

from app.dynamic_agent.web.mock_data import get_mock_tool_by_name, get_mock_tools
from app.dynamic_agent.web.models import ToolInfo

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get(
    "",
    response_model=List[ToolInfo],
    summary="Get available tools",
)
async def get_tools():
    try:
        logger.info("🔧 Getting available tools")
        tools = get_mock_tools()
        return tools
    except Exception as e:
        logger.error(f"❌ Error getting tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/{tool_name}",
    response_model=ToolInfo,
    summary="Get tool information",
)
async def get_tool_info(tool_name: str):
    try:
        logger.info(f"🔧 Getting tool info: {tool_name}")
        tool = get_mock_tool_by_name(tool_name)
        if not tool:
            raise HTTPException(status_code=404, detail="Tool not found")
        return tool
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting tool info: {e}")
        raise HTTPException(status_code=500, detail=str(e))
