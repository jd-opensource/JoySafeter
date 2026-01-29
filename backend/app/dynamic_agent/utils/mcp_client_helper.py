from __future__ import annotations

import asyncio
import os
import threading
from _pydatetime import timedelta
from contextlib import AsyncExitStack
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client

from app.dynamic_agent.core.constants import MCP_TOOL_JOINER

# A minimal alias describing a generic tool spec as received from MCP servers.
ToolSpec = Dict[str, Any]

from loguru import logger  # noqa: E402


def create_no_proxy_httpx_client() -> httpx.AsyncClient:
    """Create an httpx client that bypasses system proxy for local connections.

    This is necessary because macOS system proxy settings can interfere with
    local Docker container connections, causing 502 Bad Gateway errors.
    """
    return httpx.AsyncClient(
        proxy=None,  # Disable proxy
        trust_env=False,  # Don't read proxy from environment
        timeout=httpx.Timeout(30.0, connect=10.0),
    )


class MultiMCP:
    """Aggregate multiple MCP servers behind a single facade.

    Responsibilities:
    - Maintain async client sessions to multiple MCP servers.
    - Discover tools from each server and produce namespaced tool views.
    - Provide a unified `call` API using the "<server>:<tool>" naming.
    - Optionally convert discovered tools into LangChain `StructuredTool`s.
    """

    def __init__(
        self,
        server_configs: List[Dict[str, str]],
        *,
        namespace: str = "server",
        rename: Optional[Callable[[str, str], str]] = None,
        collision_policy: str = "namespace",  # 'error' | 'suffix' | 'namespace'
        suffix_format: str = "-{n}",
        include_metadata: bool = True,
    ) -> None:
        self._server_configs = server_configs
        self._namespace = namespace
        self._rename = rename
        self._collision_policy = collision_policy
        self._suffix_format = suffix_format
        self._include_metadata = include_metadata

        self._stack: Optional[AsyncExitStack] = None
        self._sessions: Dict[str, ClientSession] = {}
        self._tools_per_server: Optional[Dict[str, List[Dict[str, Any]]]] = None

    async def __aenter__(self) -> "MultiMCP":
        stack = AsyncExitStack()
        await stack.__aenter__()
        self._stack = stack
        # Enter contexts sequentially to guarantee matching enter/exit in the same task
        for cfg in self._server_configs:
            name = cfg["name"]
            url = cfg["url"]
            try:
                await self._connect_with_retry(
                    stack, name, url, timeout=float(os.environ.get("MCP_TOOL_READ_TIMEOUT_SECONDS", 3600))
                )
            except Exception as e:
                logger.error(f"Failed to connect to {name} at {url}: {e}")
                await stack.aclose()
                raise
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if self._stack is not None:
                await self._stack.aclose()
        except Exception as e:
            logger.warning(f"Error during stack cleanup: {e}")
        finally:
            self._stack = None
            self._sessions = {}
            self._tools_per_server = None

    async def _connect_with_retry(
        self,
        stack: AsyncExitStack,
        name: str,
        url: str,
        max_retries: int = 3,
        timeout: float = 30.0,
    ) -> None:
        """Connect to MCP server with retry logic and timeout.

        Args:
            stack: AsyncExitStack for resource management
            name: Server name
            url: Server URL
            max_retries: Maximum number of connection attempts
            timeout: Timeout in seconds for each attempt
        """
        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                logger.info(f"Connecting to {name} at {url} (attempt {attempt + 1}/{max_retries})...")

                # Use timeout for SSE client connection
                # Create custom httpx client factory that bypasses system proxy
                def no_proxy_client_factory(**kwargs):
                    return httpx.AsyncClient(proxy=None, trust_env=False, **kwargs)

                read, write = await asyncio.wait_for(
                    stack.enter_async_context(
                        sse_client(
                            url,
                            sse_read_timeout=float(os.environ.get("MCP_TOOL_READ_TIMEOUT_SECONDS", 3600)),
                            httpx_client_factory=no_proxy_client_factory,  # type: ignore[arg-type]
                        )
                    ),
                    timeout=timeout,
                )
                session = await asyncio.wait_for(
                    stack.enter_async_context(
                        ClientSession(
                            read,
                            write,
                            read_timeout_seconds=timedelta(
                                seconds=int(os.environ.get("MCP_TOOL_READ_TIMEOUT_SECONDS", 3600))
                            ),
                        )
                    ),
                    timeout=timeout,
                )
                await asyncio.wait_for(session.initialize(), timeout=timeout)
                self._sessions[name] = session
                logger.info(f"✓ Connected to {name}")
                return
            except asyncio.TimeoutError as e:
                last_error = e
                logger.warning(f"Connection to {name} timed out (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)  # Exponential backoff
            except Exception as e:
                last_error = e
                logger.warning(f"Connection to {name} failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)  # Exponential backoff

        # All retries exhausted
        raise ConnectionError(
            f"Failed to connect to {name} at {url} after {max_retries} attempts. Last error: {last_error}"
        )

    @property
    def sessions(self) -> Dict[str, ClientSession]:
        return self._sessions

    async def discover_tools(self, force: bool = False) -> Dict[str, List[Dict[str, Any]]]:
        """Query each server for its tools and cache the result.

        Returns a mapping: server_name -> list of tool dicts {name, description, input_schema}.
        Set `force=True` to refresh the cache.
        """
        if self._tools_per_server is not None and not force:
            return self._tools_per_server
        tools_per_server: Dict[str, List[Dict[str, Any]]] = {}

        async def _discover(name: str, session: ClientSession):
            result = await session.list_tools()
            items: List[Dict[str, Any]] = []
            for tool in result.tools:
                items.append(
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": tool.inputSchema,
                    }
                )
            tools_per_server[name] = items

        await asyncio.gather(*(_discover(n, s) for n, s in self._sessions.items()))
        self._tools_per_server = tools_per_server
        return tools_per_server

    def _make_unique_names(
        self, tools_per_server: Dict[str, List[Dict[str, Any]]]
    ) -> List[Tuple[str, str, Dict[str, Any]]]:
        # Build unique names across servers according to collision policy.
        # Returns list of tuples: (unique_name, server_name, tool_dict)
        seen: set[str] = set()
        out: List[Tuple[str, str, Dict[str, Any]]] = []
        for server_name, tools in tools_per_server.items():
            for t in tools:
                base = (
                    self._rename(server_name, t["name"])
                    if self._rename
                    else (f"{server_name}{MCP_TOOL_JOINER}{t['name']}" if self._namespace == "server" else t["name"])
                )
                name = base
                if name in seen:
                    old_name = name
                    logger.warning(f'Duplicate name "{name}"')
                    if self._collision_policy == "error":
                        raise ValueError(f"tool name collision: {name}")
                    elif self._collision_policy == "suffix":
                        i = 2
                        while f"{base}{self._suffix_format.format(n=i)}" in seen:
                            i += 1
                        name = f"{base}{self._suffix_format.format(n=i)}"
                    else:  # 'namespace'
                        name = f"{server_name}{MCP_TOOL_JOINER}{t['name']}"
                    logger.warning(f'Duplicate name "{old_name}", rename to {name}')

                seen.add(name)
                out.append((name, server_name, t))
        return out

    def namespaced_tools(self) -> List[Dict[str, Any]]:
        if self._tools_per_server is None:
            raise RuntimeError("discover_tools() must be called before namespaced_tools()")
        out: List[Dict[str, Any]] = []
        for unique_name, server_name, t in self._make_unique_names(self._tools_per_server):
            # Expose a flattened tool view with server/original metadata retained.
            out.append(
                {
                    "name": unique_name,
                    "description": t["description"],
                    "input_schema": t["input_schema"],
                    "server": server_name,
                    "original_name": t["name"],
                }
            )
        return out

    async def call(self, namespaced: str, /, **kwargs: Any) -> Any:
        """Call a tool by namespaced id "<server>:<tool>" with kwargs as arguments.

        Attempt to normalize common MCP content response shapes:
        - Single text item: try JSON-deserialize, fall back to raw string.
        - Single binary/data item: return `.data` as-is if present.
        - Multiple items: return list of `.text` (or str fallback).
        """
        if ":" not in namespaced:
            raise ValueError("namespaced tool must be in format '<server>:<tool>'")
        server_name, tool_name = namespaced.split(":", 1)
        if server_name not in self._sessions:
            raise KeyError(f"unknown server: {server_name}")
        session = self._sessions[server_name]
        result = await session.call_tool(tool_name, arguments=kwargs)
        if result.content:
            if len(result.content) == 1:
                content = result.content[0]
                if hasattr(content, "text"):
                    text = content.text
                    try:
                        import json as json_lib

                        return json_lib.loads(text)
                    except (json_lib.JSONDecodeError, ValueError):
                        return text
                elif hasattr(content, "data"):
                    return content.data
            return [c.text if hasattr(c, "text") else str(c) for c in result.content]
        return None

    # ---------- LangChain helpers ----------
    def _pydantic_model_from_json_schema(self, name: str, schema: Dict[str, Any]):
        """Create a lightweight Pydantic model from a JSON Schema.

        Notes:
        - Maps basic JSON types to Python/Pydantic types.
        - Optional fields default to `None` unless explicitly required.
        - Keeps things permissive for complex/unknown schemas by falling back to `Any`.
        """
        try:
            from pydantic import create_model
        except Exception as e:
            raise ImportError("pydantic is required to build LangChain arg schemas") from e

        props: Dict[str, Any] = schema.get("properties", {}) or {}
        required = set(schema.get("required", []) or [])

        def map_type(js: Dict[str, Any]):
            t = js.get("type")
            if t == "string":
                return (str, ...)
            if t == "integer":
                return (int, ...)
            if t == "number":
                return (float, ...)
            if t == "boolean":
                return (bool, ...)
            if t == "array":
                from typing import Any as TAny
                from typing import List as TList

                return (TList[TAny], ...)
            if t == "object":
                return (dict, ...)
            # default to Any
            from typing import Any as TAny

            return (TAny, ...)

        fields: Dict[str, Tuple[Any, Any]] = {}
        for key, js in props.items():
            typ, default = map_type(js)
            if key not in required:
                default = None
            fields[key] = (typ, default if default is not ... else ...)

        model = create_model(name, **fields)  # type: ignore[call-overload]
        return model

    def to_langchain_tools(self, tool_call_timeout: float = 30.0) -> List[Any]:
        """Export discovered MCP tools as LangChain `StructuredTool`s.

        Implementation details:
        - Uses a per-tool closure that captures `server_name` and `tool_name` via default
          arguments to avoid Python's late-binding pitfall in loops.
        - Provides both sync `func` and async `coroutine` interfaces. The sync path:
          * Uses `asyncio.run` when no loop is running.
          * If already inside an event loop, runs the coroutine in a background thread
            to avoid `asyncio.run()` restrictions.
        - Optionally appends metadata (server/tool) to the tool description.
        - Each tool call is wrapped with a timeout to prevent hanging.

        Args:
            tool_call_timeout: Maximum time in seconds for each individual tool call (default: 30s)
        """
        try:
            # Newer LangChain versions
            from langchain_core.tools import StructuredTool  # type: ignore
        except ImportError:
            try:
                # Older LangChain versions
                from langchain.tools import StructuredTool  # type: ignore
            except ImportError as e:
                raise ImportError("LangChain StructuredTool not found. Please install/update langchain.") from e

        if self._tools_per_server is None:
            raise RuntimeError("discover_tools() must be called before to_langchain_tools()")

        tools: List[Any] = []
        for unique_name, server_name, t in self._make_unique_names(self._tools_per_server):
            args_model = None
            schema = t.get("input_schema") or {}
            try:
                args_model = self._pydantic_model_from_json_schema(
                    name=f"Args_{server_name}_{t['name']}", schema=schema
                )
            except ImportError:
                args_model = None

            # Capture current loop values to avoid late-binding issues
            async def _acall(
                _server_name=server_name, _tool_name=t["name"], _timeout=tool_call_timeout, **kwargs: Any
            ) -> Any:
                try:
                    async with asyncio.timeout(_timeout):
                        return await self.call(f"{_server_name}:{_tool_name}", **kwargs)
                except asyncio.TimeoutError:
                    logger.error(f"Tool call {_server_name}:{_tool_name} exceeded timeout of {_timeout}s")
                    raise

            # Sync wrapper: always runs in a separate thread with its own event loop
            # This avoids all issues with nested event loops
            def _call(_server_name=server_name, _tool_name=t["name"], _timeout=tool_call_timeout, **kwargs: Any) -> Any:
                fut_result: Dict[str, Any] = {}
                fut_error: Dict[str, BaseException] = {}

                def runner():
                    try:
                        # Create a new event loop in this thread
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        try:
                            fut_result["value"] = new_loop.run_until_complete(
                                _acall(_server_name=_server_name, _tool_name=_tool_name, _timeout=_timeout, **kwargs)
                            )
                        finally:
                            new_loop.close()
                    except BaseException as e:
                        fut_error["ex"] = e

                t_th = threading.Thread(target=runner, daemon=True)
                t_th.start()
                t_th.join(timeout=_timeout + 1)  # Add 1s buffer for thread cleanup
                if "ex" in fut_error:
                    raise fut_error["ex"]
                return fut_result.get("value")

            description = t["description"] or ""
            if self._include_metadata:
                meta = f" [server={server_name} tool={t['name']}]"
                description = (description + meta).strip()

            # args_schema can be None or BaseModel type
            tool_args_schema = args_model if args_model is not None else None
            tool = StructuredTool(
                name=unique_name,
                description=description,
                func=_call,
                coroutine=_acall,
                args_schema=tool_args_schema,  # type: ignore[arg-type]
                # metadata can be added in newer langchain via .metadata or description
            )
            tools.append(tool)
        return tools


__all__ = ["MultiMCP", "ToolSpec"]

if __name__ == "__main__":
    SERVER_CONFIGS = [
        {"name": "serverA", "url": "http://127.0.0.1:8000/sse"},
        {"name": "serverB", "url": "http://127.0.0.1:8000/sse"},
    ]

    async def main():
        async with MultiMCP(SERVER_CONFIGS, namespace="server", collision_policy="namespace") as mcp:
            # Discover tools
            tools_per = await mcp.discover_tools()
            print("Per-server tools:")
            for server, tools in tools_per.items():
                print(f"- {server}: {[t['name'] for t in tools]}")

            # Namespaced tools
            ns_tools = mcp.namespaced_tools()
            print("\nNamespaced tools:")
            for t in ns_tools:
                print(f"- {t['name']} ({t['server']} -> {t['original_name']})")

            # Call a specific tool (<server>:<tool>)
            try:
                res = await mcp.call(
                    "serverA:create_file", filename="hello.txt", content="Hello MultiMCP!", binary=False
                )
                print("\ncall result1:", res)
            except Exception as e:
                print("call error:", e)

            # Export as LangChain tools if needed
            try:
                lc_tools = mcp.to_langchain_tools(tool_call_timeout=30)
                print(f"\nLangChain tools built: {len(lc_tools)}")
                # Example integration into Agent: agent = initialize_agent(tools=lc_tools, ...)
                tool_map = {t.name: t for t in lc_tools}
                # r = tool_map['serverA:create_file'].run({'filename': "hello.txt", 'content': "Hello MultiMCP!", 'binary': False})
                # print("\ncall result21:", r)
                r = await tool_map["serverA:create_file"].arun(
                    {"filename": "hello.txt", "content": "Hello MultiMCP!", "binary": False}
                )
                print("\ncall result22:", r)
            except ImportError:
                print("LangChain or pydantic not installed, skipping export.")

    asyncio.run(main())
