"""
Node tools resolution.

Parses `GraphNode` tool configuration (persisted in DB) and resolves it into a
LangChain-compatible tools list for `create_agent(..., tools=[...])`.

Frontend stores tools under:
- node.data.config.tools = { builtin: string[], mcp: string[] }
  where mcp entries are in format `${server_name}::${toolName}`.
Backend also has a dedicated `GraphNode.tools` JSONB field; we support both.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from loguru import logger

# MCP tools are now loaded from ToolRegistry instead of direct connections
# Import default user ID constant
from app.core.constants import DEFAULT_USER_ID
from app.core.tools.tool import EnhancedTool, ToolMetadata, ToolSourceType
from app.models.graph import GraphNode
from app.utils.sandbox_paths import get_user_sandbox_host_dir


def _first_dict(*candidates: Any) -> Optional[dict]:
    for c in candidates:
        if isinstance(c, dict):
            return c
    return None


def extract_tools_config(node: GraphNode) -> Optional[dict]:
    """
    Extract tools config dict from a GraphNode.

    Preference order:
    1) node.data.config.tools (canonical)
    2) node.data.tools (legacy)
    """
    data = node.data or {}
    config = data.get("config", {}) if isinstance(data, dict) else {}
    tools_from_config = config.get("tools") if isinstance(config, dict) else None

    tools_dict = _first_dict(tools_from_config, data.get("tools") if isinstance(data, dict) else None)
    if not tools_dict:
        return None
    return tools_dict


def _parse_mcp_ids(mcp_ids: Iterable[str]) -> Dict[str, Set[str]]:
    """Parse MCP tool IDs (format: server_name::tool_name)"""
    result: Dict[str, Set[str]] = {}

    for raw in mcp_ids:
        if not raw:
            continue

        # Split by "::" separator
        if "::" not in raw:
            logger.warning(
                f"[_parse_mcp_ids] Invalid format (missing '::'): '{raw}'. Expected format: 'server_name::tool_name'"
            )
            continue

        server_name, tool_name = raw.split("::", 1)
        server_name = (server_name or "").strip()
        tool_name = (tool_name or "").strip()

        if not server_name:
            logger.warning(f"[_parse_mcp_ids] Missing server name in: '{raw}'")
            continue

        if not tool_name:
            logger.warning(f"[_parse_mcp_ids] Missing tool name in: '{raw}'")
            continue

        result.setdefault(server_name, set()).add(tool_name)

    return result


def _alias_tool(*, name: str, description: str, callable_func: Any) -> EnhancedTool:
    """Create an EnhancedTool with a stable user-facing `name`."""
    return EnhancedTool.from_callable(  # type: ignore
        callable_func=callable_func,
        name=name,
        description=description,
        tool_metadata=ToolMetadata(source_type=ToolSourceType.BUILTIN, tags={"builtin"}, category="node"),
    )


def _resolve_builtin_tools(*, builtin_ids: List[str], root_dir: Path, user_id: str, backend: Any = None) -> List[Any]:
    """
    Resolve builtin tool IDs into LangChain tools.

    Resolve builtin tool IDs (e.g. ``tavily_search``, ``preview_skill``)
    into concrete LangChain tool implementations.

    Args:
        backend: Optional sandbox backend adapter (PydanticSandboxAdapter).
                 When provided, preview_skill reads files from inside the container.
    """
    # Try to get tools from registry first
    from app.core.tools.tool_registry import get_global_registry

    registry = get_global_registry()

    # Lazy imports to avoid import-time failures when optional dependencies
    # (e.g. `tavily-python`) are not installed.
    from app.core.tools.builtin.preview_skill import preview_skill_in_sandbox

    # Bind preview_skill with the user's sandbox root path
    # NOTE: We use a real wrapper function instead of functools.partial because
    # langchain's create_schema_from_function cannot introspect partial objects.
    _sandbox_root = str(get_user_sandbox_host_dir(str(user_id)))

    def bound_preview_skill(skill_name: str, skills_subdir: str = "skills") -> str:
        """Preview a skill's files and validate its metadata."""
        # The Agent sees paths inside the container (e.g. /workspace/skills/...)
        # Normalize the subdir by stripping /workspace prefix.
        normalized_subdir = skills_subdir.strip("/")
        if normalized_subdir.startswith("workspace/"):
            normalized_subdir = normalized_subdir[len("workspace/") :]
        if not normalized_subdir:
            normalized_subdir = "skills"

        # If a backend is available, read files directly from inside the container.
        # This avoids relying on Docker volume mount sync (unreliable on macOS).
        if backend is not None:
            return _preview_skill_from_backend(backend, skill_name, normalized_subdir)

        # Fallback: read from host filesystem
        return preview_skill_in_sandbox(
            skill_name=skill_name,
            sandbox_root=_sandbox_root,
            skills_subdir=normalized_subdir,
        )

    # Research tools - get from registry only
    research_tools = {}
    for tool_id in ["tavily_search", "think_tool"]:
        registry_tool = registry.get_tool(tool_id)
        if registry_tool:
            research_tools[tool_id] = registry_tool
            logger.debug(f"[node_tools] Found {tool_id} in registry")
        else:
            logger.warning(f"[node_tools] Tool '{tool_id}' not found in registry, skipping")

    # Canonical mapping for UI-friendly IDs -> tool implementations.
    aliases: Dict[str, Any] = {
        "preview_skill": _alias_tool(
            name="preview_skill",
            description="Preview a skill generated in the sandbox. Reads all files and returns JSON with contents and validation.",
            callable_func=bound_preview_skill,
        ),
        **research_tools,  # Add research tools to aliases
    }

    resolved: List[Any] = []
    for tool_id in builtin_ids:
        if not tool_id:
            continue
        t = aliases.get(tool_id)
        if t is None:
            logger.warning(f"[node_tools] Unknown builtin tool id '{tool_id}', skipping")
            continue
        resolved.append(t)
    return resolved


def _preview_skill_from_backend(backend: Any, skill_name: str, skills_subdir: str = "skills") -> str:
    """Preview a skill by reading files from inside the Docker container via backend.

    This uses the backend adapter's ls_info() and read() methods to access
    files directly inside the container, avoiding host filesystem sync issues.
    """
    import json as _json

    from app.core.skill.validators import validate_skill_description, validate_skill_name
    from app.core.skill.yaml_parser import parse_skill_md

    skill_dir = f"/workspace/{skills_subdir}/{skill_name}"
    errors: List[str] = []
    warnings: List[str] = []

    def _safe_ls(path: str) -> List[Dict[str, Any]]:
        try:
            return list(backend.ls_info(path))
        except Exception as e:
            logger.warning(f"[preview_skill] Failed to list {path}: {e}")
            return []

    dir_listing = _safe_ls(skill_dir)
    resolved_subdir = skills_subdir

    if not dir_listing and skills_subdir == "skills":
        for entry in _safe_ls("/workspace"):
            path = str(entry.get("path", ""))
            if not path or not entry.get("is_dir"):
                continue
            thread_name = Path(path.rstrip("/")).name
            candidate_subdir = f"{thread_name}/skills"
            candidate_dir = f"/workspace/{candidate_subdir}/{skill_name}"
            candidate_listing = _safe_ls(candidate_dir)
            if candidate_listing:
                skill_dir = candidate_dir
                dir_listing = candidate_listing
                resolved_subdir = candidate_subdir
                break

    if not dir_listing:
        return _json.dumps(
            {
                "skill_name": skill_name,
                "files": [],
                "validation": {
                    "valid": False,
                    "errors": [f"Skill directory not found: {resolved_subdir}/{skill_name}"],
                    "warnings": [],
                },
            }
        )

    # Recursively collect all files from the skill directory
    files: List[Dict[str, Any]] = []
    _collect_files_from_backend(backend, skill_dir, skill_dir, files)

    # Locate and validate SKILL.md
    skill_md_entry = next((f for f in files if f["path"] == "SKILL.md"), None)
    if skill_md_entry is None:
        errors.append("SKILL.md not found in skill directory")
    else:
        frontmatter, body = parse_skill_md(skill_md_entry["content"])
        fm_name = frontmatter.get("name", "")
        if not fm_name:
            errors.append("Missing required field 'name' in SKILL.md frontmatter")
        else:
            name_valid, name_err = validate_skill_name(fm_name)
            if not name_valid:
                errors.append(f"Invalid skill name: {name_err}")

        fm_desc = frontmatter.get("description", "")
        if not fm_desc:
            errors.append("Missing required field 'description' in SKILL.md frontmatter")
        else:
            desc_valid, desc_err = validate_skill_description(str(fm_desc))
            if not desc_valid:
                errors.append(f"Invalid skill description: {desc_err}")

        if not body or not body.strip():
            warnings.append("SKILL.md body is empty; consider adding usage documentation")

    valid = len(errors) == 0
    return _json.dumps(
        {
            "skill_name": skill_name,
            "files": files,
            "validation": {
                "valid": valid,
                "errors": errors,
                "warnings": warnings,
            },
        }
    )


def _collect_files_from_backend(backend: Any, dir_path: str, base_dir: str, files: List[Dict[str, Any]]) -> None:
    """Recursively collect files from inside the container via backend."""
    import os

    _EXCLUDED_DIRS = {"__pycache__", ".git", "node_modules", ".mypy_cache", ".pytest_cache"}

    try:
        entries = backend.ls_info(dir_path)
    except Exception:
        return

    for entry in entries:
        path = entry.get("path", "").rstrip("/")
        is_dir = entry.get("is_dir", False)

        if not path:
            continue

        basename = os.path.basename(path)

        if is_dir:
            if basename in _EXCLUDED_DIRS:
                continue
            _collect_files_from_backend(backend, path, base_dir, files)
        else:
            # Get relative path
            rel_path = path
            if path.startswith(base_dir):
                rel_path = path[len(base_dir) :].lstrip("/")

            if not rel_path:
                continue

            # Read file content
            try:
                raw_content = backend.read(path, offset=0, limit=100000)
                content = raw_content if isinstance(raw_content, str) else str(raw_content)
                # Strip line numbers added by format_read_response
                # format_content_with_line_numbers outputs: "{line_num}\t{content}"
                # e.g. "     1\t---" or "     2\tname: foo"
                # Also handle legacy " | " format for safety.
                stripped_lines = []
                for line in content.splitlines():
                    # Try tab-separated format first: "  N\tcontent"
                    m = re.match(r"^\s*\d+(?:\.\d+)?\t", line)
                    if m:
                        stripped_lines.append(line[m.end() :])
                    # Fallback: pipe-separated format "  N | content"
                    elif " | " in line[:12]:
                        stripped_lines.append(line.split(" | ", 1)[1])
                    else:
                        stripped_lines.append(line)
                content = "\n".join(stripped_lines)
            except Exception:
                continue

            # Detect file type
            ext = os.path.splitext(rel_path)[1].lower()
            _EXT_MAP = {
                ".py": "python",
                ".md": "markdown",
                ".json": "json",
                ".yaml": "yaml",
                ".yml": "yaml",
                ".txt": "text",
                ".sh": "shell",
                ".js": "javascript",
                ".ts": "typescript",
                ".html": "html",
                ".css": "css",
            }
            file_type = _EXT_MAP.get(ext, "other")

            files.append(
                {
                    "path": rel_path,
                    "content": content,
                    "file_type": file_type,
                    "size": entry.get("size", len(content)),
                }
            )


def _normalize_user_id(user_id: Any | None) -> str:
    """
    Normalize user_id to a string format.

    Converts UUID objects to strings, handles None by returning DEFAULT_USER_ID.
    Ensures all user_id values are strings (UUID format).

    Args:
        user_id: User ID (can be UUID object, string, or None)

    Returns:
        Normalized user_id as string (UUID format)
    """
    if user_id is None:
        return DEFAULT_USER_ID

    # Convert UUID object to string if needed
    if isinstance(user_id, uuid.UUID):
        return str(user_id)

    # Already a string
    if isinstance(user_id, str):
        return user_id

    # Fallback: convert to string
    return str(user_id)


async def resolve_tools_for_node(
    node: GraphNode, *, user_id: str | None = None, backend: Any = None
) -> Optional[List[Any]]:
    """
    Resolve tools list for a node.

    Process flow:
    1. Extract tools config from node
    2. Parse builtin tools → resolve to tool objects
    3. Parse MCP tools → resolve server names → get tools
    4. Return combined tool list

    MCP server identification: server name (unique per user)

    Args:
        node: GraphNode to resolve tools for
        user_id: User ID (normalized to string UUID format)

    Returns:
        - None: means "no explicit tools config" (caller may use defaults)
        - [] / [..]: explicit tool list
    """
    # Normalize user_id
    normalized_user_id = _normalize_user_id(user_id)

    logger.debug(f"[resolve_tools_for_node] Starting resolution for node_id={node.id}, user_id={normalized_user_id}")

    # Step 1: Extract tools config
    cfg = extract_tools_config(node)
    if cfg is None:
        logger.debug(f"[resolve_tools_for_node] No tools config found for node_id={node.id}")
        return None

    logger.debug(f"[resolve_tools_for_node] Tools config: {cfg}")

    builtin_ids = cfg.get("builtin") if isinstance(cfg, dict) else None
    mcp_ids = cfg.get("mcp") if isinstance(cfg, dict) else None

    builtin_ids_list = list(builtin_ids) if isinstance(builtin_ids, list) else []
    mcp_ids_list = list(mcp_ids) if isinstance(mcp_ids, list) else []

    logger.debug(f"[resolve_tools_for_node] Parsed config: builtin_ids={builtin_ids_list}, mcp_ids={mcp_ids_list}")

    root_dir = Path(f"/tmp/{normalized_user_id}")
    tools: List[Any] = []

    # Step 2: Resolve builtin tools
    if builtin_ids_list:
        logger.debug(f"[resolve_tools_for_node] Resolving {len(builtin_ids_list)} builtin tools")
        builtin_tools = _resolve_builtin_tools(
            builtin_ids=builtin_ids_list, root_dir=root_dir, user_id=normalized_user_id, backend=backend
        )
        logger.debug(f"[resolve_tools_for_node] Resolved {len(builtin_tools)} builtin tools")
        tools.extend(builtin_tools)

    # Step 3: Resolve MCP tools from Registry with instance validation
    if mcp_ids_list:
        logger.debug(f"[resolve_tools_for_node] Resolving {len(mcp_ids_list)} MCP tools")

        from app.core.database import async_session_factory
        from app.core.tools.mcp_tool_utils import resolve_mcp_tools_from_list

        async with async_session_factory() as db:
            mcp_tools = await resolve_mcp_tools_from_list(mcp_ids_list, normalized_user_id, db)

        logger.debug(f"[resolve_tools_for_node] Retrieved {len(mcp_tools)} MCP tools")
        tools.extend(mcp_tools)

    logger.debug(
        f"[resolve_tools_for_node] Final resolution for node_id={node.id} | "
        f"builtin_selected={len(builtin_ids_list)} | mcp_selected={len(mcp_ids_list)} | "
        f"tools_resolved={len(tools)}"
    )

    # Final check: ensure no ToolMetadata objects in the list
    from app.core.tools.tool import ToolMetadata

    for i, tool in enumerate(tools):
        if isinstance(tool, ToolMetadata):
            logger.error(
                f"[resolve_tools_for_node] ERROR: ToolMetadata object found at index {i} "
                f"in tools list! This should not happen. metadata: {tool}"
            )

    return tools
