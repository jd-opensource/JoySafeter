"""
MCP Tool Builder - 从工具定义创建 EnhancedTool

使用 lazy entrypoint，在执行时从 toolkit manager 获取 toolkit。
"""

from typing import Any, List, Optional

from loguru import logger
from pydantic import BaseModel

try:
    from mcp.types import Tool as MCPTool
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")

from app.core.tools.tool import EnhancedTool, ToolMetadata, ToolSourceType
from app.utils.mcp import create_lazy_mcp_entrypoint


def _json_schema_to_pydantic_model(schema: Any, name: str) -> Optional[type[BaseModel]]:
    """
    Convert a JSON Schema dict from MCP into a Pydantic BaseModel for validation.
    Handles common primitive types, arrays, and objects. Falls back to None if unsupported.

    This is a standalone version matching the logic in MCPTools._json_schema_to_pydantic_model
    to avoid duplication while maintaining consistency.
    """
    from typing import Any
    from typing import Dict as TypingDict
    from typing import List as TypingList
    from typing import Optional as TypingOptional

    from pydantic import create_model

    try:
        if not isinstance(schema, dict):
            return None

        if not isinstance(schema, dict):
            return None
        properties = schema.get("properties", {}) or {}  # type: ignore[union-attr]
        required = set(schema.get("required", []) or [])  # type: ignore[union-attr]

        type_mapping = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
        }

        fields = {}
        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, dict):
                continue
            prop_type = prop_schema.get("type")
            default = prop_schema.get("default", None)
            py_type: type[Any] = Any  # type: ignore[assignment]

            if prop_type in type_mapping:
                py_type = type_mapping[prop_type]  # type: ignore[assignment]
            elif prop_type == "array":
                items = prop_schema.get("items", {})
                if isinstance(items, dict):
                    item_type_val = items.get("type")
                    item_type: Any = type_mapping.get(item_type_val, Any) if isinstance(item_type_val, str) else Any
                else:
                    item_type = Any
                py_type = TypingList[item_type]  # type: ignore[assignment]
            elif prop_type == "object":
                py_type = TypingDict[str, Any]  # type: ignore[assignment]

            if prop_name in required and default is None:
                fields[prop_name] = (py_type, ...)  # type: ignore[assignment]
            else:
                fields[prop_name] = (TypingOptional[py_type], default)  # type: ignore[assignment]

        if not fields:
            return None

        model_name = f"MCP_{name}_Args"
        return create_model(model_name, **fields)  # type: ignore
    except Exception as e:
        logger.debug(f"Failed to convert JSON schema to Pydantic for tool '{name}': {e}")
        return None


def create_mcp_tools_from_definitions(
    mcp_tools: List[MCPTool],
    server_name: str,
    user_id: str,
    timeout_seconds: int = 60,
) -> List[EnhancedTool]:
    """从 MCP 工具定义创建 EnhancedTool 列表"""
    enhanced_tools = []

    for tool in mcp_tools:
        try:
            entrypoint = create_lazy_mcp_entrypoint(
                tool_name=tool.name,
                server_name=server_name,
                user_id=user_id,
            )

            args_schema_model = _json_schema_to_pydantic_model(tool.inputSchema, tool.name)

            metadata = ToolMetadata(
                source_type=ToolSourceType.MCP,
                tags={"mcp"},
                mcp_server_name=server_name,
                mcp_tool_name=tool.name,
            )
            metadata.custom_attrs["execution_timeout"] = timeout_seconds

            enhanced_tool = EnhancedTool.from_entrypoint(
                name=tool.name,
                description=tool.description or "",
                args_schema=args_schema_model,
                entrypoint=entrypoint,
                tool_metadata=metadata,
            )

            enhanced_tools.append(enhanced_tool)
            logger.debug(f"Created EnhancedTool for MCP tool: {tool.name} from server: {server_name}")

        except Exception as e:
            logger.error(f"Failed to create EnhancedTool for MCP tool {tool.name}: {e}")
            continue

    return enhanced_tools
