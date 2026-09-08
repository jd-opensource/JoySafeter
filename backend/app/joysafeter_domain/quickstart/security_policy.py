"""Pure rules for the quickstart secure phase. No DB, no I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from pydantic import TypeAdapter

from app.joysafeter_domain.schemas.joysafeter_agent import (
    LocalMcpServerConfig,
    McpServerConfig,
    SseMcpServerConfig,
    StreamableHttpMcpServerConfig,
)
from app.joysafeter_shared.mcp_url import normalize_mcp_url

_URL_PATTERN = re.compile(r"https?://[^\s)\]}>\"']+", re.IGNORECASE)
_BARE_HOST_PATTERN = re.compile(
    r"(?<!@)\b([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+)\b",
    re.IGNORECASE,
)
_HOST_BLOCKLIST = {"example.com", "localhost"}
_MCP_INTENT = re.compile(r"\bmcp\b|credential group|external tool|tool credential", re.IGNORECASE)
_MCP_SERVER_LIST_ADAPTER = TypeAdapter(list[McpServerConfig])

_KNOWN_SERVICE_HOSTS: list[tuple[list[re.Pattern[str]], list[str]]] = [
    (
        [
            re.compile(r"\bgithub\b", re.I),
            re.compile(r"\bgit\b", re.I),
            re.compile(r"\brepo(?:sitory)?\b", re.I),
            re.compile(r"\bpull request\b", re.I),
        ],
        ["github.com", "api.github.com"],
    ),
    ([re.compile(r"\bslack\b", re.I)], ["slack.com", "slack-edge.com"]),
    ([re.compile(r"\bnotion\b", re.I)], ["api.notion.com"]),
    ([re.compile(r"\bjira\b", re.I), re.compile(r"\batlassian\b", re.I)], ["atlassian.net"]),
    ([re.compile(r"\blinear\b", re.I)], ["api.linear.app"]),
    (
        [re.compile(r"\bgoogle sheets\b", re.I), re.compile(r"\bgoogle drive\b", re.I)],
        ["sheets.googleapis.com", "www.googleapis.com"],
    ),
]


@dataclass(frozen=True)
class SecurityRecommendation:
    recommended_hosts: tuple[str, ...]
    recommended_mcp_servers: tuple["RecommendedMcpServer", ...]
    host_reason: str  # explicitHosts | knownServices | none
    external_tools_recommended: bool
    external_tools_reason: str  # mcpServers | credentialIntent | none


@dataclass(frozen=True)
class RecommendedMcpServer:
    name: str
    url: str
    auth_requirement: str  # required | optional | none


def _normalize_host(raw: str) -> str | None:
    trimmed = re.sub(r"[),.;\]}>'\"]+$", "", raw.strip())
    if not trimmed:
        return None
    try:
        host = urlparse(trimmed if "://" in trimmed else f"//{trimmed}", scheme="").hostname or ""
    except ValueError:
        host = ""
    if not host:
        host = re.sub(r"^https?://", "", trimmed, flags=re.I).split("/")[0].split(":")[0]
    host = host.lower()
    if "." not in host or host in _HOST_BLOCKLIST or host.endswith(".local"):
        return None
    return host


def _collect_strings(value: object, out: list[str], depth: int = 0) -> None:
    if depth > 5 or value is None:
        return
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_strings(item, out, depth + 1)
    elif isinstance(value, dict):
        for item in value.values():
            _collect_strings(item, out, depth + 1)


def _extract_hosts(text: str) -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()
    for match in _URL_PATTERN.findall(text):
        host = _normalize_host(match)
        if host and host not in seen:
            seen.add(host)
            hosts.append(host)
    for match in _BARE_HOST_PATTERN.findall(text):
        host = _normalize_host(match)
        if host and host not in seen:
            seen.add(host)
            hosts.append(host)
    return hosts


def _extract_mcp_security_requirements(
    value: object,
) -> tuple[tuple[str, ...], tuple[RecommendedMcpServer, ...]]:
    entries = _MCP_SERVER_LIST_ADAPTER.validate_python(value) if value is not None else []

    hosts: list[str] = []
    servers: list[RecommendedMcpServer] = []
    seen_urls: set[str] = set()
    for entry in entries:
        if isinstance(entry, LocalMcpServerConfig):
            continue
        if not isinstance(entry, (StreamableHttpMcpServerConfig, SseMcpServerConfig)):
            continue
        host = (urlparse(entry.url).hostname or "").lower()
        if host and host not in hosts:
            hosts.append(host)
        if entry.auth_requirement.value == "none":
            continue
        normalized_url = normalize_mcp_url(entry.url)
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        servers.append(
            RecommendedMcpServer(
                name=entry.name,
                url=normalized_url,
                auth_requirement=entry.auth_requirement.value,
            )
        )
    return tuple(hosts), tuple(servers)


def recommend_security(user_texts: list[str], agent_config: dict | None) -> SecurityRecommendation:
    agent_strings: list[str] = []
    if agent_config is not None:
        _collect_strings(
            {key: value for key, value in agent_config.items() if key != "mcp_servers"},
            agent_strings,
        )
    authoritative_texts = agent_strings if agent_config is not None else [text for text in user_texts if text]
    combined = "\n".join(authoritative_texts)

    mcp_servers = (agent_config or {}).get("mcp_servers")
    configured_mcp_hosts, recommended_mcp_servers = _extract_mcp_security_requirements(mcp_servers)

    explicit_hosts = _extract_hosts(combined)
    known_hosts: list[str] = []
    for patterns, hosts in _KNOWN_SERVICE_HOSTS:
        if any(p.search(combined) for p in patterns):
            for host in hosts:
                if host not in known_hosts:
                    known_hosts.append(host)

    ordered: list[str] = []
    for host in configured_mcp_hosts:
        if host not in ordered:
            ordered.append(host)
    for host in [*explicit_hosts, *known_hosts]:
        if len(ordered) >= 8:
            break
        if host not in ordered:
            ordered.append(host)
    recommended_hosts = tuple(ordered)

    credential_intent = agent_config is None and bool(_MCP_INTENT.search(combined))
    external_tools = bool(recommended_mcp_servers) or credential_intent

    return SecurityRecommendation(
        recommended_hosts=recommended_hosts,
        recommended_mcp_servers=recommended_mcp_servers,
        host_reason=(
            "explicitHosts" if configured_mcp_hosts or explicit_hosts else "knownServices" if known_hosts else "none"
        ),
        external_tools_recommended=external_tools,
        external_tools_reason=(
            "mcpServers" if recommended_mcp_servers else "credentialIntent" if credential_intent else "none"
        ),
    )
