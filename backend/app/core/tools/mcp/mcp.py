import weakref
from dataclasses import asdict
from datetime import timedelta
from typing import Any, Literal, Optional, Union

from loguru import logger
from pydantic import BaseModel

from app.core.tools.mcp.params import SSEClientParams, StreamableHTTPClientParams
from app.core.tools.tool import EnhancedTool, ToolMetadata, ToolSourceType
from app.core.tools.toolkit import Toolkit
from app.utils.mcp import get_entrypoint_for_tool, prepare_command

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import get_default_environment, stdio_client
    from mcp.client.streamable_http import streamablehttp_client
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")


class MCPTools(Toolkit):
    """
    A toolkit for integrating Model Context Protocol (MCP) servers with Agno agents.
    This allows agents to access tools, resources, and prompts exposed by MCP servers.

    Can be used in three ways:
    1. Direct initialization with a ClientSession
    2. As an async context manager with StdioServerParameters
    3. As an async context manager with SSE or Streamable HTTP client parameters
    """

    def __init__(
        self,
        command: Optional[str] = None,
        *,
        url: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
        transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
        server_params: Optional[Union[StdioServerParameters, SSEClientParams, StreamableHTTPClientParams]] = None,
        session: Optional[ClientSession] = None,
        timeout_seconds: int = 10,
        client=None,
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
        refresh_connection: bool = False,
        tool_name_prefix: Optional[str] = None,
        **kwargs,
    ):
        """
        Initialize the MCP toolkit.

        Args:
            session: An initialized MCP ClientSession connected to an MCP server
            server_params: Parameters for creating a new session
            command: The command to run to start the server. Should be used in conjunction with env.
            url: The URL endpoint for SSE or Streamable HTTP connection when transport is "sse" or "streamable-http".
            env: The environment variables to pass to the server. Should be used in conjunction with command.
            client: The underlying MCP client (optional, used to prevent garbage collection)
            timeout_seconds: Read timeout in seconds for the MCP client
            include_tools: Optional list of tool names to include (if None, includes all)
            exclude_tools: Optional list of tool names to exclude (if None, excludes none)
            transport: The transport protocol to use, either "stdio" or "sse" or "streamable-http"
            refresh_connection: If True, the connection and tools will be refreshed on each run
        """
        super().__init__(name="MCPTools", **kwargs)

        if transport == "sse":
            logger.info("SSE as a standalone transport is deprecated. Please use Streamable HTTP instead.")

        # Set these after `__init__` to bypass the `_check_tools_filters`
        # because tools are not available until `initialize()` is called.
        self.include_tools = include_tools
        self.exclude_tools = exclude_tools
        self.refresh_connection = refresh_connection
        self.tool_name_prefix = tool_name_prefix

        if session is None and server_params is None:
            if transport == "sse" and url is None:
                raise ValueError("One of 'url' or 'server_params' parameters must be provided when using SSE transport")
            if transport == "stdio" and command is None:
                raise ValueError(
                    "One of 'command' or 'server_params' parameters must be provided when using stdio transport"
                )
            if transport == "streamable-http" and url is None:
                raise ValueError(
                    "One of 'url' or 'server_params' parameters must be provided when using Streamable HTTP transport"
                )

        # Ensure the received server_params are valid for the given transport
        if server_params is not None:
            if transport == "sse":
                if not isinstance(server_params, SSEClientParams):
                    raise ValueError(
                        "If using the SSE transport, server_params must be an instance of SSEClientParams."
                    )
            elif transport == "stdio":
                if not isinstance(server_params, StdioServerParameters):
                    raise ValueError(
                        "If using the stdio transport, server_params must be an instance of StdioServerParameters."
                    )
            elif transport == "streamable-http":
                if not isinstance(server_params, StreamableHTTPClientParams):
                    raise ValueError(
                        "If using the streamable-http transport, server_params must be an instance of StreamableHTTPClientParams."
                    )

        self.timeout_seconds = timeout_seconds
        self.session: Optional[ClientSession] = session
        self.server_params: Optional[Union[StdioServerParameters, SSEClientParams, StreamableHTTPClientParams]] = (
            server_params  # type: ignore[assignment]
        )
        self.transport = transport
        self.url = url
        # Default execution timeout equals configured client timeout; refined after connect
        self._execution_timeout = timeout_seconds

        # Merge provided env with system env
        if env is not None:
            env = {
                **get_default_environment(),
                **env,
            }
        else:
            env = get_default_environment()

        if command is not None and transport not in ["sse", "streamable-http"]:
            parts = prepare_command(command)
            cmd = parts[0]
            arguments = parts[1:] if len(parts) > 1 else []
            self.server_params = StdioServerParameters(command=cmd, args=arguments, env=env)

        self._client = client

        self._initialized = False
        self._connection_task = None
        self._active_contexts: list[Any] = []
        self._context = None
        self._session_context = None

        def cleanup():
            """Cancel active connections"""
            if self._connection_task and not self._connection_task.done():
                self._connection_task.cancel()

        # Setup cleanup logic before the instance is garbage collected
        self._cleanup_finalizer = weakref.finalize(self, cleanup)

    @property
    def initialized(self) -> bool:
        return self._initialized

    async def is_alive(self) -> bool:
        if self.session is None:
            return False
        try:
            await self.session.send_ping()
            return True
        except (RuntimeError, BaseException):
            return False

    async def connect(self, force: bool = False):
        """Initialize a MCPTools instance and connect to the contextual MCP server"""

        if force:
            # Clean up the session and context so we force a new connection
            self.session = None
            self._context = None
            self._session_context = None
            self._initialized = False
            self._connection_task = None
            self._active_contexts = []

        if self._initialized:
            return

        try:
            await self._connect()
        except (RuntimeError, BaseException) as e:
            logger.error(f"Failed to connect to {str(self)}: {e}")

    async def _connect(self) -> None:
        """Connects to the MCP server and initializes the tools"""

        if self._initialized:
            return

        if self.session is not None:
            await self.initialize()
            return

        # Create a new studio session
        if self.transport == "sse":
            sse_params = asdict(self.server_params) if self.server_params is not None else {}  # type: ignore
            if "url" not in sse_params:
                sse_params["url"] = self.url
            self._context = sse_client(**sse_params)  # type: ignore
            client_timeout = min(self.timeout_seconds, sse_params.get("timeout", self.timeout_seconds))

        # Create a new streamable HTTP session
        elif self.transport == "streamable-http":
            streamable_http_params = asdict(self.server_params) if self.server_params is not None else {}  # type: ignore
            if "url" not in streamable_http_params:
                streamable_http_params["url"] = self.url
            self._context = streamablehttp_client(**streamable_http_params)  # type: ignore
            params_timeout = streamable_http_params.get("timeout", self.timeout_seconds)
            if isinstance(params_timeout, timedelta):
                params_timeout = int(params_timeout.total_seconds())
            client_timeout = min(self.timeout_seconds, params_timeout)

        else:
            if self.server_params is None:
                raise ValueError("server_params must be provided when using stdio transport.")
            self._context = stdio_client(self.server_params)  # type: ignore
            client_timeout = self.timeout_seconds

        # Record execution timeout to propagate into EnhancedTool metadata
        self._execution_timeout = client_timeout

        session_params = await self._context.__aenter__()  # type: ignore
        self._active_contexts.append(self._context)
        read, write = session_params[0:2]

        self._session_context = ClientSession(read, write, read_timeout_seconds=timedelta(seconds=client_timeout))  # type: ignore
        self.session = await self._session_context.__aenter__()  # type: ignore
        self._active_contexts.append(self._session_context)

        # Initialize with the new session
        await self.initialize()

    async def close(self) -> None:
        """Close the MCP connection and clean up resources

        Note: This method handles the case where the connection was created
        in a different asyncio task than the one closing it. In such cases,
        anyio's cancel scopes will raise an error which we handle gracefully.
        """
        if not self._initialized:
            return

        # Mark as not initialized first to prevent concurrent usage
        self._initialized = False

        # Try to close the session context first
        if self._session_context is not None:
            try:
                await self._session_context.__aexit__(None, None, None)
            except RuntimeError as e:
                # Handle cross-task cancel scope error
                if "cancel scope" in str(e).lower() or "different task" in str(e).lower():
                    logger.debug(f"Session close skipped (cross-task): {e}")
                else:
                    logger.warning(f"Error closing session context: {e}")
            except Exception as e:
                logger.warning(f"Error closing session context: {e}")
            finally:
                self.session = None
                self._session_context = None

        # Try to close the transport context
        if self._context is not None:
            try:
                await self._context.__aexit__(None, None, None)
            except RuntimeError as e:
                # Handle cross-task cancel scope error
                if "cancel scope" in str(e).lower() or "different task" in str(e).lower():
                    logger.debug(f"Transport close skipped (cross-task): {e}")
                else:
                    logger.warning(f"Error closing transport context: {e}")
            except Exception as e:
                logger.warning(f"Error closing transport context: {e}")
            finally:
                self._context = None

        # Clear active contexts list
        self._active_contexts.clear()

    async def __aenter__(self) -> "MCPTools":
        await self._connect()
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb):
        """Exit the async context manager."""
        if self._session_context is not None:
            await self._session_context.__aexit__(_exc_type, _exc_val, _exc_tb)
            self.session = None
            self._session_context = None

        if self._context is not None:
            await self._context.__aexit__(_exc_type, _exc_val, _exc_tb)
            self._context = None

        self._initialized = False

    def _get_server_identifier(self) -> Optional[str]:
        """
        Returns an identifier for the connected MCP server (command or URL).
        """
        try:
            if self.transport == "stdio":
                if self.server_params is not None and hasattr(self.server_params, "command"):
                    cmd = getattr(self.server_params, "command")
                    return str(cmd) if cmd is not None else None
                return "stdio"
            elif self.transport in ["sse", "streamable-http"]:
                if self.url:
                    return str(self.url) if self.url is not None else None
                if self.server_params is not None and hasattr(self.server_params, "url"):
                    url = getattr(self.server_params, "url")
                    return str(url) if url is not None else None
        except Exception:
            pass
        return None

    def _json_schema_to_pydantic_model(self, schema: Any, name: str) -> Optional[type[BaseModel]]:
        """
        Convert a JSON Schema dict from MCP into a Pydantic BaseModel for validation.
        Handles common primitive types and arrays. Falls back to None if unsupported.
        """
        from pydantic import create_model

        try:
            if not isinstance(schema, dict):
                return None

            properties = schema.get("properties", {}) or {}
            required = set(schema.get("required", []) or [])

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
                    from typing import List as TypingList

                    py_type = TypingList[item_type]  # type: ignore[assignment]
                elif prop_type == "object":
                    from typing import Dict as TypingDict

                    py_type = TypingDict[str, Any]  # type: ignore[assignment]

                if prop_name in required and default is None:
                    fields[prop_name] = (py_type, ...)  # type: ignore[assignment]
                else:
                    from typing import Optional as TypingOptional

                    fields[prop_name] = (TypingOptional[py_type], default)  # type: ignore[assignment]

            if not fields:
                return None

            model_name = f"MCP_{name}_Args"
            return create_model(model_name, **fields)  # type: ignore
        except Exception as e:
            logger.debug(f"Failed to convert JSON schema to Pydantic for tool '{name}': {e}")
            return None

    async def build_tools(self) -> None:
        """Build the tools for the MCP toolkit"""
        if self.session is None:
            raise ValueError("Session is not initialized")

        try:
            # Get the list of tools from the MCP server
            available_tools = await self.session.list_tools()  # type: ignore

            self._check_tools_filters(
                available_tools=[tool.name for tool in available_tools.tools],
                include_tools=self.include_tools,
                exclude_tools=self.exclude_tools,
            )

            # Filter tools based on include/exclude lists
            filtered_tools = []
            for tool in available_tools.tools:
                if self.exclude_tools and tool.name in self.exclude_tools:
                    continue
                if self.include_tools is None or tool.name in self.include_tools:
                    filtered_tools.append(tool)

            # Get tool name prefix if available
            tool_name_prefix = ""
            if self.tool_name_prefix is not None:
                tool_name_prefix = self.tool_name_prefix + "_"

            # Register the tools with the toolkit
            for tool in filtered_tools:
                try:
                    # Get an entrypoint for the tool
                    entrypoint = get_entrypoint_for_tool(tool, self.session)  # type: ignore

                    # Build validation schema from MCP JSON Schema (if possible)
                    args_schema_model = self._json_schema_to_pydantic_model(tool.inputSchema, tool.name)

                    # Build metadata for EnhancedTool
                    metadata = ToolMetadata(
                        source_type=ToolSourceType.MCP,
                        tags={"mcp"},
                        mcp_server_name=self._get_server_identifier(),
                        mcp_tool_name=tool.name,
                    )
                    metadata.custom_attrs["execution_timeout"] = self._execution_timeout

                    # Create EnhancedTool adapter wrapping the async entrypoint
                    f = EnhancedTool.from_entrypoint(
                        name=tool_name_prefix + tool.name,
                        description=tool.description or "",
                        args_schema=args_schema_model,
                        entrypoint=entrypoint,
                        tool_metadata=metadata,
                    )

                    # Register the Function with the toolkit
                    self.functions[f.name] = f
                    logger.debug(f"Function: {f.name} registered with {self.name}")
                except Exception as e:
                    logger.error(f"Failed to register tool {tool.name}: {e}")

        except (RuntimeError, BaseException) as e:
            logger.error(f"Failed to get tools for {str(self)}: {e}")
            raise

    async def initialize(self) -> None:
        """Initialize the MCP toolkit by getting available tools from the MCP server"""
        if self._initialized:
            return

        try:
            if self.session is None:
                raise ValueError("Session is not initialized")

            # Initialize the session if not already initialized
            await self.session.initialize()

            await self.build_tools()

            self._initialized = True

        except (RuntimeError, BaseException) as e:
            logger.error(f"Failed to initialize MCP toolkit: {e}")
