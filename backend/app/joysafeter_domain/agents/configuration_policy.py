from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.joysafeter_shared.common.app_errors import InvalidRequestError

_LOCAL_MCP_HOSTS = frozenset({"localhost", "127.0.0.1", "host.docker.internal", "::1"})


def _configuration_error(*, code: str, message: str, data: dict[str, Any]) -> InvalidRequestError:
    return InvalidRequestError(
        code=code,
        message=message,
        data=data,
        user_action="fix_input",
    )


class AgentConfigurationPolicy:
    @staticmethod
    def validate_mcp_servers(mcp_servers: list[dict] | None, *, require_https: bool) -> None:
        if not mcp_servers:
            return
        seen_names: set[str] = set()
        for config in mcp_servers:
            if not isinstance(config, dict):
                continue
            if config.get("type") == "sse" and config.get("auth_requirement") != "none":
                raise _configuration_error(
                    code="AGENT_MCP_AUTH_REQUIREMENT_UNSUPPORTED",
                    message="SSE MCP servers do not support managed credential injection",
                    data={
                        "mcp_server_name": config.get("name", ""),
                        "transport": "sse",
                        "auth_requirement": config.get("auth_requirement"),
                    },
                )
            url = config.get("url", "")
            if url.lower().startswith("http://") and require_https:
                host = (urlparse(url).hostname or "").lower()
                if host not in _LOCAL_MCP_HOSTS:
                    raise _configuration_error(
                        code="AGENT_MCP_URL_SCHEME_INVALID",
                        message=f"MCP server URL must use HTTPS: {url}",
                        data={"url": url, "host": host},
                    )
            name = config.get("name", "")
            if name:
                if name in seen_names:
                    raise _configuration_error(
                        code="AGENT_MCP_SERVER_NAME_DUPLICATE",
                        message=f"Duplicate MCP server name: {name}",
                        data={"mcp_server_name": name},
                    )
                seen_names.add(name)

    @staticmethod
    def validate_tool_mcp_references(tools: list | None, mcp_servers: list[dict] | None) -> None:
        if not tools:
            return
        declared_names = {
            config.get("name", "")
            for config in mcp_servers or []
            if isinstance(config, dict) and config.get("name", "")
        }
        builtin_toolset_seen = False
        mcp_toolsets_seen: set[str] = set()
        custom_tools_seen: set[str] = set()
        mcp_references: list[str] = []
        for tool in tools:
            tool_data = tool.model_dump() if hasattr(tool, "model_dump") else tool
            tool_type = tool_data.get("type")
            if tool_type == "agent_toolset_20260401":
                if builtin_toolset_seen:
                    raise _configuration_error(
                        code="AGENT_TOOLSET_DUPLICATE",
                        message="Duplicate built-in toolset",
                        data={"toolset": "agent_toolset_20260401"},
                    )
                builtin_toolset_seen = True
            elif tool_type == "mcp_toolset":
                server_name = tool_data.get("mcp_server_name", "")
                if server_name in mcp_toolsets_seen:
                    raise _configuration_error(
                        code="AGENT_TOOLSET_DUPLICATE",
                        message=f"Duplicate MCP toolset for server: {server_name}",
                        data={"toolset": "mcp_toolset", "mcp_server_name": server_name},
                    )
                mcp_toolsets_seen.add(server_name)
                mcp_references.append(server_name)
            elif tool_type == "custom":
                name = tool_data.get("name", "")
                if name in custom_tools_seen:
                    raise _configuration_error(
                        code="AGENT_CUSTOM_TOOL_DUPLICATE",
                        message=f"Duplicate custom tool: {name}",
                        data={"tool_name": name},
                    )
                custom_tools_seen.add(name)

            seen_config_names: set[str] = set()
            for config in tool_data.get("configs") or []:
                config_data = config.model_dump() if hasattr(config, "model_dump") else config
                name = config_data.get("name", "") if isinstance(config_data, dict) else ""
                if name in seen_config_names:
                    raise _configuration_error(
                        code="AGENT_TOOL_CONFIG_DUPLICATE",
                        message=f"Duplicate tool config: {name}",
                        data={"toolset": tool_type, "tool_name": name},
                    )
                seen_config_names.add(name)

        for server_name in mcp_references:
            if not server_name:
                continue
            if server_name not in declared_names:
                raise _configuration_error(
                    code="AGENT_TOOL_MCP_SERVER_UNDECLARED",
                    message=f"Tool references undeclared MCP server: {server_name}",
                    data={"mcp_server_name": server_name, "declared_mcp_server_names": sorted(declared_names)},
                )
