import weakref
from contextlib import AsyncExitStack
from dataclasses import asdict
from datetime import timedelta
from types import TracebackType
from typing import Any, List, Literal, Optional, Union

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


class MultiMCPTools(Toolkit):
    """
    A toolkit for integrating multiple Model Context Protocol (MCP) servers with Agno agents.
    This allows agents to access tools, resources, and prompts exposed by MCP servers.

    Can be used in three ways:
    1. Direct initialization with a ClientSession
    2. As an async context manager with StdioServerParameters
    3. As an async context manager with SSE or Streamable HTTP endpoints
    """

    def __init__(
        self,
        commands: Optional[List[str]] = None,
        urls: Optional[List[str]] = None,
        urls_transports: Optional[List[Literal["sse", "streamable-http"]]] = None,
        *,
        env: Optional[dict[str, str]] = None,
        server_params_list: Optional[
            list[Union[SSEClientParams, StdioServerParameters, StreamableHTTPClientParams]]
        ] = None,
        timeout_seconds: int = 10,
        client=None,
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
        refresh_connection: bool = False,
        allow_partial_failure: bool = False,
        **kwargs,
    ):
        """
        Initialize the MCP toolkit.

        Args:
            commands: List of commands to run to start the servers. Should be used in conjunction with env.
            urls: List of URLs for SSE and/or Streamable HTTP endpoints.
            urls_transports: List of transports to use for the given URLs.
            server_params_list: List of StdioServerParameters or SSEClientParams or StreamableHTTPClientParams for creating new sessions.
            env: The environment variables to pass to the servers. Should be used in conjunction with commands.
            client: The underlying MCP client (optional, used to prevent garbage collection).
            timeout_seconds: Timeout in seconds for managing timeouts for Client Session if Agent or Tool doesn't respond.
            include_tools: Optional list of tool names to include (if None, includes all).
            exclude_tools: Optional list of tool names to exclude (if None, excludes none).
            allow_partial_failure: If True, allows toolkit to initialize even if some MCP servers fail to connect. If False, any failure will raise an exception.
            refresh_connection: If True, the connection and tools will be refreshed on each run
        """
        super().__init__(name="MultiMCPTools", **kwargs)

        if urls_transports is not None:
            if "sse" in urls_transports:
                logger.info("SSE as a standalone transport is deprecated. Please use Streamable HTTP instead.")

        if urls is not None:
            if urls_transports is None:
                logger.warning(
                    "The default transport 'streamable-http' will be used. You can explicitly set the transports by providing the urls_transports parameter."
                )
            else:
                if len(urls) != len(urls_transports):
                    raise ValueError("urls and urls_transports must be of the same length")

        # Set these after `__init__` to bypass the `_check_tools_filters`
        # beacuse tools are not available until `initialize()` is called.
        self.include_tools = include_tools
        self.exclude_tools = exclude_tools
        self.refresh_connection = refresh_connection

        if server_params_list is None and commands is None and urls is None:
            raise ValueError("Either server_params_list or commands or urls must be provided")

        self.server_params_list: List[Union[SSEClientParams, StdioServerParameters, StreamableHTTPClientParams]] = (
            server_params_list or []
        )
        self.timeout_seconds = timeout_seconds
        self.commands: Optional[List[str]] = commands
        self.urls: Optional[List[str]] = urls
        # Merge provided env with system env
        if env is not None:
            env = {
                **get_default_environment(),
                **env,
            }
        else:
            env = get_default_environment()

        if commands is not None:
            for command in commands:
                parts = prepare_command(command)
                cmd = parts[0]
                arguments = parts[1:] if len(parts) > 1 else []
                self.server_params_list.append(StdioServerParameters(command=cmd, args=arguments, env=env))

        if urls is not None:
            if urls_transports is not None:
                for url, transport in zip(urls, urls_transports):
                    if transport == "streamable-http":
                        self.server_params_list.append(StreamableHTTPClientParams(url=url))
                    else:
                        self.server_params_list.append(SSEClientParams(url=url))
            else:
                for url in urls:
                    self.server_params_list.append(StreamableHTTPClientParams(url=url))

        self._async_exit_stack = AsyncExitStack()

        self._client = client

        self._initialized = False
        self._connection_task = None
        self._successful_connections = 0
        self._sessions: list[ClientSession] = []

        self.allow_partial_failure = allow_partial_failure
        # Map id(session) -> meta {server_identifier, url, transport, execution_timeout}
        self._session_meta: dict[int, dict] = {}

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
        try:
            for session in self._sessions:
                await session.send_ping()
            return True
        except (RuntimeError, BaseException):
            return False

    async def connect(self, force: bool = False):
        """Initialize a MultiMCPTools instance and connect to the MCP servers"""

        if force:
            # Clean up the session and context so we force a new connection
            self._sessions = []
            self._successful_connections = 0
            self._initialized = False
            self._connection_task = None

        if self._initialized:
            return

        try:
            await self._connect()
        except (RuntimeError, BaseException) as e:
            logger.error(f"Failed to connect to {str(self)}: {e}")

    @classmethod
    async def create_and_connect(
        cls,
        commands: Optional[List[str]] = None,
        urls: Optional[List[str]] = None,
        urls_transports: Optional[List[Literal["sse", "streamable-http"]]] = None,
        *,
        env: Optional[dict[str, str]] = None,
        server_params_list: Optional[
            List[Union[SSEClientParams, StdioServerParameters, StreamableHTTPClientParams]]
        ] = None,
        timeout_seconds: int = 5,
        client=None,
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
        refresh_connection: bool = False,
        **kwargs,
    ) -> "MultiMCPTools":
        """Initialize a MultiMCPTools instance and connect to the MCP servers"""
        instance = cls(
            commands=commands,
            urls=urls,
            urls_transports=urls_transports,
            env=env,
            server_params_list=server_params_list,
            timeout_seconds=timeout_seconds,
            client=client,
            include_tools=include_tools,
            exclude_tools=exclude_tools,
            refresh_connection=refresh_connection,
            **kwargs,
        )

        await instance._connect()
        return instance

    async def _connect(self) -> None:
        """Connects to the MCP servers and initializes the tools"""
        if self._initialized:
            return

        server_connection_errors = []

        for server_params in self.server_params_list:
            try:
                # Handle stdio connections
                if isinstance(server_params, StdioServerParameters):
                    stdio_transport = await self._async_exit_stack.enter_async_context(stdio_client(server_params))
                    read, write = stdio_transport
                    session = await self._async_exit_stack.enter_async_context(
                        ClientSession(read, write, read_timeout_seconds=timedelta(seconds=self.timeout_seconds))
                    )
                    await self.initialize(session)
                    # Record session metadata for stdio transport
                    try:
                        exec_timeout = self.timeout_seconds
                        identifier = getattr(server_params, "command", "stdio")
                        self._session_meta[id(session)] = {
                            "server_identifier": identifier,
                            "url": None,
                            "transport": "stdio",
                            "execution_timeout": exec_timeout,
                        }
                    except Exception:
                        pass
                    self._successful_connections += 1

                # Handle SSE connections
                elif isinstance(server_params, SSEClientParams):
                    client_connection = await self._async_exit_stack.enter_async_context(
                        sse_client(**asdict(server_params))
                    )
                    read, write = client_connection
                    session = await self._async_exit_stack.enter_async_context(ClientSession(read, write))
                    await self.initialize(session)
                    # Record session metadata for SSE transport
                    try:
                        sp = server_params  # type: ignore
                        to = getattr(sp, "timeout", None)
                        exec_timeout = (
                            min(self.timeout_seconds, int(to)) if isinstance(to, (int, float)) else self.timeout_seconds
                        )
                        self._session_meta[id(session)] = {
                            "server_identifier": getattr(sp, "url", None),
                            "url": getattr(sp, "url", None),
                            "transport": "sse",
                            "execution_timeout": exec_timeout,
                        }
                    except Exception:
                        pass
                    self._successful_connections += 1

                # Handle Streamable HTTP connections
                elif isinstance(server_params, StreamableHTTPClientParams):
                    client_connection = await self._async_exit_stack.enter_async_context(
                        streamablehttp_client(**asdict(server_params))
                    )
                    read, write = client_connection[0:2]
                    session = await self._async_exit_stack.enter_async_context(ClientSession(read, write))
                    await self.initialize(session)
                    # Record session metadata for Streamable HTTP transport
                    try:
                        sp = server_params  # type: ignore
                        to = getattr(sp, "timeout", None)
                        if isinstance(to, timedelta):
                            exec_timeout = min(self.timeout_seconds, int(to.total_seconds()))
                        elif isinstance(to, (int, float)):
                            exec_timeout = min(self.timeout_seconds, int(to))
                        else:
                            exec_timeout = self.timeout_seconds
                        self._session_meta[id(session)] = {
                            "server_identifier": getattr(sp, "url", None),
                            "url": getattr(sp, "url", None),
                            "transport": "streamable-http",
                            "execution_timeout": exec_timeout,
                        }
                    except Exception:
                        pass
                    self._successful_connections += 1

            except Exception as e:
                if not self.allow_partial_failure:
                    raise ValueError(f"MCP connection failed: {e}")

                logger.error(f"Failed to initialize MCP server with params {server_params}: {e}")
                server_connection_errors.append(str(e))
                continue

        if self._successful_connections > 0:
            await self.build_tools()

        if self._successful_connections == 0 and server_connection_errors:
            raise ValueError(f"All MCP connections failed: {server_connection_errors}")

        if not self._initialized and self._successful_connections > 0:
            self._initialized = True

    async def close(self) -> None:
        """Close the MCP connections and clean up resources"""
        if not self._initialized:
            return

        try:
            await self._async_exit_stack.aclose()
            self._sessions = []
            self._successful_connections = 0

        except (RuntimeError, BaseException) as e:
            logger.error(f"Failed to close MCP connections: {e}")

        self._initialized = False

    async def __aenter__(self) -> "MultiMCPTools":
        """Enter the async context manager."""
        try:
            await self._connect()
        except (RuntimeError, BaseException) as e:
            logger.error(f"Failed to connect to {str(self)}: {e}")
        return self

    async def __aexit__(
        self,
        exc_type: Union[type[BaseException], None],
        exc_val: Union[BaseException, None],
        exc_tb: Union[TracebackType, None],
    ):
        """Exit the async context manager."""
        await self._async_exit_stack.aclose()
        self._initialized = False
        self._successful_connections = 0

    def _json_schema_to_pydantic_model(self, schema: Any, name: str) -> Optional[type[BaseModel]]:
        """
        Convert a JSON Schema dict from MCP into a Pydantic BaseModel for validation.
        Supports common primitives, arrays, and shallow objects. Returns None if unsupported.
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
        for session in self._sessions:
            # Get the list of tools from the MCP server
            available_tools = await session.list_tools()

            # Filter tools based on include/exclude lists
            filtered_tools = []
            for tool in available_tools.tools:
                if self.exclude_tools and tool.name in self.exclude_tools:
                    continue
                if self.include_tools is None or tool.name in self.include_tools:
                    filtered_tools.append(tool)

            # Register the tools with the toolkit
            for tool in filtered_tools:
                try:
                    # Get an entrypoint for the tool
                    entrypoint = get_entrypoint_for_tool(tool, session)

                    # Build validation schema from MCP JSON Schema (if possible)
                    args_schema_model = self._json_schema_to_pydantic_model(tool.inputSchema, tool.name)

                    # Metadata per session
                    meta = self._session_meta.get(id(session), {})
                    metadata = ToolMetadata(
                        source_type=ToolSourceType.MCP,
                        tags={"mcp"},
                        mcp_server_name=meta.get("server_identifier"),
                        mcp_tool_name=tool.name,
                        toolset_name=self.name,
                    )
                    metadata.custom_attrs["execution_timeout"] = meta.get("execution_timeout", self.timeout_seconds)

                    # Create EnhancedTool adapter wrapping the async entrypoint
                    f = EnhancedTool.from_entrypoint(
                        name=tool.name,
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
                    raise

    async def initialize(self, session: ClientSession) -> None:
        """Initialize the MCP toolkit by getting available tools from the MCP server"""

        try:
            # Initialize the session if not already initialized
            await session.initialize()

            self._sessions.append(session)
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to get MCP tools: {e}")
            raise
