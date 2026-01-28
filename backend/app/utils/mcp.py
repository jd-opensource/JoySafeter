import json
from functools import partial
from typing import List, Optional
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel

try:
    from mcp import ClientSession
    from mcp.types import CallToolResult, EmbeddedResource, ImageContent, TextContent
    from mcp.types import Tool as MCPTool
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")


from app.utils import Audio, File, Image, Video


class ToolResult(BaseModel):
    """Result from a tool that can include media artifacts."""

    content: str
    images: Optional[List[Image]] = None
    videos: Optional[List[Video]] = None
    audios: Optional[List[Audio]] = None
    files: Optional[List[File]] = None


def get_entrypoint_for_tool(tool: MCPTool, session: ClientSession):
    """
    DEPRECATED: This function is kept for backward compatibility.

    Note: MCPTools.build_tools() still uses this for internal tool registration.
    For registering tools to ToolRegistry, use create_lazy_mcp_entrypoint instead.

    Return an entrypoint for an MCP tool that captures a session.
    """

    async def call_tool(tool_name: str, **kwargs) -> ToolResult:
        try:
            await session.send_ping()
        except Exception as e:
            logger.debug(f"Session ping failed: {e}")

        try:
            # 打印工具调用信息：工具名称和参数
            # logger.info(f"[MCP Tool Call] 工具名称: {tool_name}, 参数: {kwargs}")
            # 特别突出显示文件路径参数
            if "filepath" in kwargs:
                logger.warning(f"[MCP Tool Call] 🔍 文件路径参数: {kwargs['filepath']}")
            result: CallToolResult = await session.call_tool(tool_name, kwargs)  # type: ignore

            # Return an error if the tool call failed
            if result.isError:
                return ToolResult(content=f"Error from MCP tool '{tool_name}': {result.content}")

            # Process the result content (simplified version)
            response_str = ""
            for content_item in result.content:
                if hasattr(content_item, "text"):
                    response_str += content_item.text + "\n"

            return ToolResult(content=response_str.strip())
        except Exception as e:
            logger.exception(f"Failed to call MCP tool '{tool_name}': {e}")
            return ToolResult(content=f"Error: {e}")

    return partial(call_tool, tool_name=tool.name)


class ToolExecutionError(Exception):
    """工具执行错误"""

    def __init__(self, message: str, error_type: str = "unknown", retryable: bool = False):
        self.message = message
        self.error_type = error_type  # 'network', 'timeout', 'config', 'permission', 'unknown'
        self.retryable = retryable
        super().__init__(self.message)


def _is_retryable_error(error: Exception) -> bool:
    """判断错误是否可重试"""
    error_str = str(error).lower()
    retryable_keywords = [
        "timeout",
        "connection",
        "network",
        "temporary",
        "unavailable",
        "503",
        "502",
        "504",
    ]
    return any(keyword in error_str for keyword in retryable_keywords)


def create_lazy_mcp_entrypoint(
    tool_name: str,
    server_name: str,
    user_id: str,
    max_retries: int = 2,
    retry_delay: float = 0.5,
):
    """创建 MCP 工具的 lazy entrypoint"""

    async def call_tool(**kwargs) -> ToolResult:
        import asyncio

        from app.core.database import async_session_factory
        from app.services.mcp_server_service import McpServerService
        from app.services.mcp_toolkit_manager import get_toolkit_manager

        # Get toolkit from toolkit manager
        toolkit_manager = get_toolkit_manager()

        # Look up server config (cache this if possible in future)
        async with async_session_factory() as db:
            server_service = McpServerService(db)
            server = await server_service.repo.get_by_name(user_id, server_name)

            if not server:
                error_msg = f"MCP server '{server_name}' not found for user '{user_id}'"
                logger.error(f"[MCP Tool Execution] {error_msg}")
                return ToolResult(content=f"Error: {error_msg}")

            if not server.enabled:
                error_msg = f"MCP server '{server_name}' is disabled"
                logger.warning(f"[MCP Tool Execution] {error_msg}")
                return ToolResult(content=f"Error: {error_msg}")

            # Get toolkit from manager (will create if not exists)
            try:
                toolkit = await toolkit_manager.get_toolkit(server, user_id)
                session = toolkit.session

                if not session:
                    error_msg = f"Toolkit session not initialized for server '{server_name}'"
                    logger.error(f"[MCP Tool Execution] {error_msg}")
                    return ToolResult(content=f"Error: {error_msg}")
            except Exception as e:
                error_msg = f"Failed to get toolkit for server '{server_name}': {e}"
                logger.error(f"[MCP Tool Execution] {error_msg}", exc_info=True)
                return ToolResult(content=f"Error: {error_msg}")

        # Retry logic for tool execution
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                # 打印工具调用信息：工具名称和参数
                logger.info(
                    f"[MCP Tool Call] 工具名称: {tool_name}, "
                    f"服务器: {server_name}, "
                    f"参数: {kwargs}, "
                    f"尝试次数: {attempt + 1}/{max_retries + 1}"
                )
                # 特别突出显示文件路径参数
                if "filepath" in kwargs:
                    logger.warning(f"[MCP Tool Call] 🔍 文件路径参数: {kwargs['filepath']}")

                result: CallToolResult = await session.call_tool(tool_name, kwargs)  # type: ignore

                # Return an error if the tool call failed
                if result.isError:
                    error_content = result.content
                    error_msg = f"MCP tool '{tool_name}' returned error: {error_content}"
                    logger.warning(f"[MCP Tool Execution] {error_msg}")
                    # Tool-level errors are usually not retryable
                    return ToolResult(content=f"Error: {error_msg}")

                # Process the result content
                response_str = ""
                images = []

                for content_item in result.content:
                    if isinstance(content_item, TextContent):
                        text_content = content_item.text

                        # Parse as JSON to check for custom image format
                        try:
                            parsed_json = json.loads(text_content)
                            if (
                                isinstance(parsed_json, dict)
                                and parsed_json.get("type") == "image"
                                and "data" in parsed_json
                            ):
                                logger.debug("Found custom JSON image format in TextContent")

                                # Extract image data
                                image_data = parsed_json.get("data")
                                mime_type = parsed_json.get("mimeType", "image/png")

                                if image_data and isinstance(image_data, str):
                                    import base64

                                    try:
                                        image_bytes = base64.b64decode(image_data)
                                    except Exception as e:
                                        logger.debug(f"Failed to decode base64 image data: {e}")
                                        image_bytes = None

                                    if image_bytes:
                                        img_artifact = Image(
                                            id=str(uuid4()),
                                            url=None,
                                            content=image_bytes,
                                            mime_type=mime_type,
                                        )
                                        images.append(img_artifact)
                                        response_str += "Image has been generated and added to the response.\n"
                                        continue

                        except (json.JSONDecodeError, TypeError):
                            pass

                        response_str += text_content + "\n"

                    elif isinstance(content_item, ImageContent):
                        # Handle standard MCP ImageContent
                        image_data = getattr(content_item, "data", None)

                        if image_data and isinstance(image_data, str):
                            import base64

                            try:
                                image_data = base64.b64decode(image_data)
                            except Exception as e:
                                logger.debug(f"Failed to decode base64 image data: {e}")
                                image_data = None

                        img_artifact = Image(
                            id=str(uuid4()),
                            url=getattr(content_item, "url", None),
                            content=image_data,
                            mime_type=getattr(content_item, "mimeType", "image/png"),
                        )
                        images.append(img_artifact)
                        response_str += "Image has been generated and added to the response.\n"
                    elif isinstance(content_item, EmbeddedResource):
                        # Handle embedded resources
                        response_str += f"[Embedded resource: {content_item.resource.model_dump_json()}]\n"
                    else:
                        # Handle other content types
                        response_str += f"[Unsupported content type: {content_item.type}]\n"

                logger.debug(
                    f"[MCP Tool Execution] Successfully executed tool '{tool_name}' from server '{server_name}'"
                )
                return ToolResult(
                    content=response_str.strip(),
                    images=images if images else None,
                )

            except Exception as e:
                last_error = e
                is_retryable = _is_retryable_error(e)

                if attempt < max_retries and is_retryable:
                    delay = retry_delay * (2**attempt)  # Exponential backoff
                    logger.warning(
                        f"[MCP Tool Execution] Transient error calling tool '{tool_name}' from server '{server_name}' "
                        f"(attempt {attempt + 1}/{max_retries + 1}): {e}. Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    # Try to refresh session on retry
                    try:
                        toolkit = await toolkit_manager.get_toolkit(server, user_id)
                        session = toolkit.session
                    except Exception as refresh_error:
                        logger.warning(f"[MCP Tool Execution] Failed to refresh toolkit on retry: {refresh_error}")
                    continue
                else:
                    # Non-retryable error or max retries reached
                    "timeout" if "timeout" in str(e).lower() else "unknown"
                    if not is_retryable:
                        "config" if "not found" in str(e).lower() or "disabled" in str(e).lower() else "unknown"

                    error_msg = f"Failed to execute MCP tool '{tool_name}' from server '{server_name}': {e}"
                    logger.error(f"[MCP Tool Execution] {error_msg}", exc_info=True)
                    return ToolResult(content=f"Error: {error_msg}")

        # Should not reach here, but handle it anyway
        final_error = last_error or Exception("Unknown error")
        error_msg = f"Failed to execute MCP tool '{tool_name}' from server '{server_name}' after {max_retries + 1} attempts: {final_error}"
        logger.error(f"[MCP Tool Execution] {error_msg}")
        return ToolResult(content=f"Error: {error_msg}")

    return call_tool


def prepare_command(command: str) -> list[str]:
    """Sanitize a command and split it into parts before using it to run a MCP server."""
    import os
    import shutil
    from shlex import split

    # Block dangerous characters
    if any(char in command for char in ["&", "|", ";", "`", "$", "(", ")"]):
        raise ValueError("MCP command can't contain shell metacharacters")

    parts = split(command)
    if not parts:
        raise ValueError("MCP command can't be empty")

    # Only allow specific executables
    ALLOWED_COMMANDS = {
        # Python
        "python",
        "python3",
        "uv",
        "uvx",
        "pipx",
        # Node
        "node",
        "npm",
        "npx",
        "yarn",
        "pnpm",
        "bun",
        # Other runtimes
        "deno",
        "java",
        "ruby",
        "docker",
    }

    executable = parts[0].split("/")[-1]

    # Check if it's a relative path starting with ./ or ../
    if executable.startswith("./") or executable.startswith("../"):
        # Allow relative paths to binaries
        return parts

    # Check if it's an absolute path to a binary
    if executable.startswith("/") and os.path.isfile(executable):
        # Allow absolute paths to existing files
        return parts

    # Check if it's a binary in current directory without ./
    if "/" not in executable and os.path.isfile(executable):
        # Allow binaries in current directory
        return parts

    # Check if it's a binary in PATH
    if shutil.which(executable):
        return parts

    if executable not in ALLOWED_COMMANDS:
        raise ValueError(f"MCP command needs to use one of the following executables: {ALLOWED_COMMANDS}")

    first_part = parts[0]
    executable = first_part.split("/")[-1]

    # Allow known commands
    if executable in ALLOWED_COMMANDS:
        return parts

    # Allow relative paths to custom binaries
    if first_part.startswith(("./", "../")):
        return parts

    # Allow absolute paths to existing files
    if first_part.startswith("/") and os.path.isfile(first_part):
        return parts

    # Allow binaries in current directory without ./
    if "/" not in first_part and os.path.isfile(first_part):
        return parts

    # Allow binaries in PATH
    if shutil.which(first_part):
        return parts

    raise ValueError(f"MCP command needs to use one of the following executables: {ALLOWED_COMMANDS}")
