"""Shared helpers for writing Claude Code ``.claude/settings.json``.

Used by the in-process harness adapters (claude_adapter, native_adapter) to
write tool permissions + MCP servers before spawning the ``claude`` CLI,
mirroring the Rust ``write_settings_json`` (sandbox-runner runner.rs) so both
launch paths behave identically.
"""

import json
import logging
import os
from typing import Any

from app.joysafeter_orchestrator.runtime.adapter import HarnessInput
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure

logger = logging.getLogger(__name__)


def write_claude_settings(work_dir: str, input: HarnessInput) -> None:
    """Write/merge tool permissions + MCP servers into work_dir/.claude/settings.json.

    Mirrors the Rust ``write_settings_json``: MCP server defs go to .mcp.json,
    and a ``permissions`` block (allow/ask only — the official Managed Agents
    model has no deny) goes to .claude/settings.json. Merges into any existing
    settings.json so other keys are preserved.
    """
    allow = list(input.allowed_tools or [])
    ask = list(input.ask_tools or [])
    if not (allow or ask or input.mcp_servers):
        return

    claude_dir = os.path.join(work_dir, ".claude")
    try:
        os.makedirs(claude_dir, exist_ok=True)
    except OSError as exc:
        log_boundary_failure(
            logger,
            boundary="claude_settings",
            code="CLAUDE_SETTINGS_DIR_CREATE_FAILED",
            message="Failed to create Claude settings directory",
            operation="create_claude_settings_dir",
            error=exc,
            data={"path": claude_dir},
        )
        return
    settings_path = os.path.join(claude_dir, "settings.json")

    settings: dict[str, Any] = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                settings = loaded
        except (OSError, json.JSONDecodeError):
            settings = {}

    if input.mcp_servers:
        # MCP server *definitions* live in <cwd>/.mcp.json (project scope) —
        # Claude Code does NOT read them from .claude/settings.json
        # (claude-code src/services/mcp/config.ts). settings.json only carries
        # the auto-approval flag for those project-scoped servers.
        _write_mcp_json(work_dir, input.mcp_servers)
        settings["enableAllProjectMcpServers"] = True

    perms: dict[str, list[str]] = {}
    if allow:
        perms["allow"] = allow
    if ask:
        perms["ask"] = ask
    if perms:
        settings["permissions"] = perms

    try:
        with open(settings_path, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
    except OSError as exc:
        log_boundary_failure(
            logger,
            boundary="claude_settings",
            code="CLAUDE_SETTINGS_WRITE_FAILED",
            message="Failed to write Claude settings",
            operation="write_claude_settings",
            error=exc,
            data={"path": settings_path},
        )


def _write_mcp_json(work_dir: str, mcp_servers: list[dict[str, Any]]) -> None:
    """Write MCP server definitions to <work_dir>/.mcp.json (project scope).

    Mirrors the Rust ``write_mcp_json``: remote servers (url present) use
    ``type: "http"`` (or "sse" when explicitly requested); local servers use
    ``command``/``args``/``env``. Merges into any existing .mcp.json.
    """
    mcp_json_path = os.path.join(work_dir, ".mcp.json")

    root: dict[str, Any] = {}
    if os.path.exists(mcp_json_path):
        try:
            with open(mcp_json_path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                root = loaded
        except (OSError, json.JSONDecodeError):
            root = {}

    mcp_obj = root.get("mcpServers")
    if not isinstance(mcp_obj, dict):
        mcp_obj = {}

    for server in mcp_servers:
        if not isinstance(server, dict):
            continue
        name = server.get("name", "")
        if not name:
            continue
        url = server.get("url", "")
        if url:
            server_type = server.get("server_type") or server.get("type") or ""
            transport = "sse" if server_type == "sse" else "http"
            entry: dict[str, Any] = {"type": transport, "url": url}
            if server.get("headers"):
                entry["headers"] = server["headers"]
        else:
            entry = {
                "command": server.get("command", ""),
                "args": server.get("args", []),
            }
            if server.get("env"):
                entry["env"] = server["env"]
        mcp_obj[name] = entry

    root["mcpServers"] = mcp_obj
    try:
        with open(mcp_json_path, "w", encoding="utf-8") as fh:
            json.dump(root, fh, indent=2)
    except OSError as exc:
        log_boundary_failure(
            logger,
            boundary="claude_settings",
            code="CLAUDE_MCP_JSON_WRITE_FAILED",
            message="Failed to write Claude MCP configuration",
            operation="write_mcp_json",
            error=exc,
            data={"path": mcp_json_path},
        )
