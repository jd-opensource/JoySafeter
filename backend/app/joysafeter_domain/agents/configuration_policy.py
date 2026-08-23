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
        for tool in tools:
            tool_data = tool.model_dump() if hasattr(tool, "model_dump") else tool
            if tool_data.get("type") != "mcp_toolset":
                continue
            server_name = tool_data.get("mcp_server_name", "")
            if server_name and server_name not in declared_names:
                raise _configuration_error(
                    code="AGENT_TOOL_MCP_SERVER_UNDECLARED",
                    message=f"Tool references undeclared MCP server: {server_name}",
                    data={"mcp_server_name": server_name, "declared_mcp_server_names": sorted(declared_names)},
                )
