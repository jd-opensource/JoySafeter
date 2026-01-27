# engine/mcp/server.py
# MCP Server instance - centralized location

from typing import List

from fastmcp import FastMCP

from dynamic_engine.mcp.config import ToolOriginConf

# MCP Server singleton
mcp_server = FastMCP("seclens", host="0.0.0.0", port=8000)

# Dynamic tools configuration list
dynamic_tools_conf: List[ToolOriginConf] = []
