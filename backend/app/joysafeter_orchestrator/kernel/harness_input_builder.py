import base64
import json
import logging
import os
import time
import uuid
from typing import Any, Optional

import httpx

from app.joysafeter_orchestrator.kernel.everos_identity import (
    resolve_everos_user_identity_for_session,
)
from app.joysafeter_orchestrator.kernel.vault_cipher import VaultCipher
from app.joysafeter_orchestrator.runtime.adapter import HarnessInput, SkillArchive
from app.joysafeter_shared.everos_scope import (
    compose_everos_project_id,
    compose_everos_user_id,
    everos_path_safe_id,
)

logger = logging.getLogger(__name__)

CONVERSATION_HISTORY_EVENT_LIMIT = 100
CONVERSATION_HISTORY_MAX_CHARS = 24_000
GRPC_INLINE_FILE_MOUNT_MAX_BYTES = 24 * 1024 * 1024
EVEROS_BOOTSTRAP_EPISODE_LIMIT = 5
EVEROS_BOOTSTRAP_FACT_PER_EPISODE_LIMIT = 5
EVEROS_BOOTSTRAP_AGENT_CASE_LIMIT = 5
EVEROS_BOOTSTRAP_AGENT_SKILL_LIMIT = 5
EVEROS_BOOTSTRAP_MAX_CHARS = 12_000
EVEROS_BOOTSTRAP_TIMEOUT_SECONDS = 5.0

# ------------------------------------------------------------------
# Builder helpers — Rust parity (harness_input_builder.rs)
# ------------------------------------------------------------------

_vault_cipher: VaultCipher | None = VaultCipher.from_env()


def _resolve_environment_setup_commands(environment) -> list[str]:
    """Generate apt/pip/npm/cargo/gem/go install commands from environment config."""
    if not environment:
        return []
    config = _environment_config_dict(environment)
    packages = config.get("packages", {})

    commands: list[str] = []
    if isinstance(packages, dict):
        apt = packages.get("apt", [])
        if apt:
            commands.append(f"apt-get update && apt-get install -y {' '.join(apt)}")
        pip = packages.get("pip", [])
        if pip:
            commands.append(f"pip install {' '.join(pip)}")
        npm = packages.get("npm", [])
        if npm:
            commands.append(f"npm install -g {' '.join(npm)}")
        cargo = packages.get("cargo", [])
        if cargo:
            commands.append(f"cargo install {' '.join(cargo)}")
        gem = packages.get("gem", [])
        if gem:
            commands.append(f"gem install {' '.join(gem)}")
        go = packages.get("go", [])
        if go:
            commands.extend(f"go install {pkg}" for pkg in go)
    return commands


def _environment_config_dict(environment) -> dict[str, Any]:
    if not environment:
        return {}
    config = getattr(environment, "config", None) or {}
    if isinstance(config, dict):
        return config
    if hasattr(config, "model_dump"):
        return config.model_dump()
    return {}


def _extract_agent_setup_commands(agent) -> list[str]:
    """Extract setup_commands from agent.metadata."""
    metadata = getattr(agent, "metadata", None) or {}
    if isinstance(metadata, dict):
        return list(metadata.get("setup_commands", []))
    return []


def _session_container_work_dir(last_work_dir: Optional[str]) -> str:
    if last_work_dir and os.path.isabs(last_work_dir):
        return last_work_dir
    return "/workspace"


def _should_inline_session_file_mounts(session_files: list[Any], workspace_path: Optional[str]) -> bool:
    if workspace_path:
        return False
    total_size = sum(int(getattr(sf, "size_bytes", 0) or 0) for sf in session_files)
    return total_size <= GRPC_INLINE_FILE_MOUNT_MAX_BYTES


def _agent_model_id(agent_model: Any) -> Optional[str]:
    if not agent_model:
        return None
    return (
        agent_model.get("id")
        if isinstance(agent_model, dict)
        else str(agent_model)
    )


def _resolve_harness_model(
    *,
    agent_model: Any,
    engine_kind: str,
    secrets: dict[str, str],
) -> Optional[str]:
    explicit_model = _agent_model_id(agent_model)
    if explicit_model:
        return explicit_model
    if engine_kind == "codex":
        return secrets.get("OPENAI_MODEL") or secrets.get("MODEL")
    # Claude Code should read provider-selected Anthropic models from
    # ANTHROPIC_MODEL in the container environment. Passing that same value as
    # `claude --model ...` breaks some Anthropic-compatible gateways.
    return None


def _resolve_everos_base_url() -> str:
    return os.getenv(
        "EVEROS_MEMORY_PROXY_BASE_URL",
        "http://host.docker.internal:8000/api/v1/everos_memory",
    ).rstrip("/")


def _everos_path_safe_id(value: Any, fallback: str) -> str:
    """Return an EverOS API path-safe id.

    EverOS persists ``app_id`` / ``project_id`` / owner ids as directory
    segments, so JoySafeter ids that flow into the service must match the
    EverOS route allow-list and avoid traversal tokens.
    """
    return everos_path_safe_id(value, fallback)


def _build_everos_identity_env(
    *,
    project_id: Any = None,
    project_slug: Any = None,
    session_id: Any = None,
    user_id: Any = None,
    user_name: Any = None,
    agent_id: Any = None,
) -> dict[str, str]:
    session = _everos_path_safe_id(session_id, "session")
    user = compose_everos_user_id(user_name=user_name, user_id=user_id)
    agent = _everos_path_safe_id(agent_id, "agent")
    everos_project_id = (
        compose_everos_project_id(project_slug=project_slug, project_id=project_id)
        if project_id and project_slug
        else _everos_path_safe_id(project_id, "default")
    )
    return {
        "EVEROS_APP_ID": "joysafeter",
        "EVEROS_PROJECT_ID": everos_project_id,
        "EVEROS_SESSION_ID": session,
        "EVEROS_USER_ID": user,
        "EVEROS_AGENT_ID": agent,
    }


def _append_everos_system_prompt(
    base_system: Optional[str],
    everos_base_url: str,
    identity: dict[str, str] | None = None,
    *,
    active_session_ids: list[str] | None = None,
) -> str:
    identity = identity or _build_everos_identity_env()
    active_session_note = ""
    if active_session_ids is not None:
        active_session_note = (
            "\n"
            "Archived JoySafeter sessions are inactive for memory. For "
            "`episode`, `atomic_fact`, and `agent_case` `/get` or "
            "`/search` requests, include a `filters.session_id` "
            "constraint using `EVEROS_ACTIVE_SESSION_IDS`; do not retrieve "
            "or use memories from sessions outside that list.\n"
        )
    note = (
        "# EverOS Memory Service\n"
        "The EverOS memory service is available inside this sandbox at "
        f"`{everos_base_url}`. Use it for long-term memory operations when "
        "the task explicitly requires memory search or memory writes.\n\n"
        "Use the JoySafeter identity mapping below for every EverOS request:\n"
        f"- `app_id`: `{identity['EVEROS_APP_ID']}` from `EVEROS_APP_ID`\n"
        f"- `project_id`: `{identity['EVEROS_PROJECT_ID']}` from `EVEROS_PROJECT_ID`\n"
        f"- `session_id`: `{identity['EVEROS_SESSION_ID']}` from `EVEROS_SESSION_ID`\n"
        f"- user memory owner `user_id`: `{identity['EVEROS_USER_ID']}` from `EVEROS_USER_ID`\n"
        f"- agent memory owner `agent_id`: `{identity['EVEROS_AGENT_ID']}` from `EVEROS_AGENT_ID`\n\n"
        "For `/search` or `/get`, include `app_id` and `project_id`; set "
        "`user_id` for user memories and `agent_id` for agent memories."
        f"{active_session_note}"
    )
    if base_system:
        return f"{base_system}\n\n{note}"
    return note


async def _fetch_everos_bootstrap_memories(
    everos_base_url: str,
    identity: dict[str, str],
    *,
    active_session_ids: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch lightweight startup memories from EverOS.

    This is intentionally best-effort at the caller boundary. The fetched
    records are used only to build a compact prompt preview; full records stay
    available through EverOS /get and /search during the session.
    """
    base_payload = {
        "app_id": identity["EVEROS_APP_ID"],
        "project_id": identity["EVEROS_PROJECT_ID"],
        "sort_order": "desc",
    }
    session_filter = _active_session_filter(active_session_ids)
    requests = [
        (
            "profiles",
            {
                **base_payload,
                "user_id": identity["EVEROS_USER_ID"],
                "memory_type": "profile",
                "page": 1,
                "page_size": 1,
            },
        ),
        (
            "episodes",
            {
                **base_payload,
                "user_id": identity["EVEROS_USER_ID"],
                "memory_type": "episode",
                "page": 1,
                "page_size": EVEROS_BOOTSTRAP_EPISODE_LIMIT,
                "sort_by": "timestamp",
                **({"filters": session_filter} if session_filter else {}),
            },
        ),
    ]
    memories: dict[str, list[dict[str, Any]]] = {
        "profiles": [],
        "episodes": [],
        "atomic_facts": [],
        "agent_cases": [],
        "agent_skills": [],
    }
    timeout = httpx.Timeout(EVEROS_BOOTSTRAP_TIMEOUT_SECONDS, connect=2.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for key, payload in requests:
            response = await client.post(
                f"{everos_base_url.rstrip('/')}/get",
                json=payload,
            )
            response.raise_for_status()
            data = response.json().get("data") or {}
            values = data.get(key) or []
            if isinstance(values, list):
                memories[key] = [v for v in values if isinstance(v, dict)]

        fact_parent_ids = _episode_fact_parent_ids(memories["episodes"])
        if fact_parent_ids:
            fact_filter = _merge_bootstrap_filters(
                {"parent_id": {"in": fact_parent_ids}},
                session_filter,
            )
            response = await client.post(
                f"{everos_base_url.rstrip('/')}/get",
                json={
                    **base_payload,
                    "user_id": identity["EVEROS_USER_ID"],
                    "memory_type": "atomic_fact",
                    "page": 1,
                    "page_size": EVEROS_BOOTSTRAP_EPISODE_LIMIT
                    * EVEROS_BOOTSTRAP_FACT_PER_EPISODE_LIMIT,
                    "sort_by": "timestamp",
                    "filters": fact_filter,
                },
            )
            response.raise_for_status()
            data = response.json().get("data") or {}
            values = data.get("atomic_facts") or []
            if isinstance(values, list):
                memories["atomic_facts"] = [v for v in values if isinstance(v, dict)]
                _attach_atomic_facts_to_episodes(
                    memories["episodes"],
                    memories["atomic_facts"],
                    per_episode=EVEROS_BOOTSTRAP_FACT_PER_EPISODE_LIMIT,
                )

        requests = [
            (
                "agent_cases",
                {
                    **base_payload,
                    "agent_id": identity["EVEROS_AGENT_ID"],
                    "memory_type": "agent_case",
                    "page": 1,
                    "page_size": EVEROS_BOOTSTRAP_AGENT_CASE_LIMIT,
                    "sort_by": "timestamp",
                    **({"filters": session_filter} if session_filter else {}),
                },
            ),
            (
                "agent_skills",
                {
                    **base_payload,
                    "agent_id": identity["EVEROS_AGENT_ID"],
                    "memory_type": "agent_skill",
                    "page": 1,
                    "page_size": EVEROS_BOOTSTRAP_AGENT_SKILL_LIMIT,
                    "sort_by": "updated_at",
                },
            ),
        ]
        for key, payload in requests:
            response = await client.post(
                f"{everos_base_url.rstrip('/')}/get",
                json=payload,
            )
            response.raise_for_status()
            data = response.json().get("data") or {}
            values = data.get(key) or []
            if isinstance(values, list):
                memories[key] = [v for v in values if isinstance(v, dict)]
    return memories


def _episode_fact_parent_ids(episodes: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    parent_ids: list[str] = []
    for episode in episodes:
        for key in ("entry_id", "parent_id"):
            value = episode.get(key)
            if isinstance(value, str) and value and value not in seen:
                seen.add(value)
                parent_ids.append(value)
    return parent_ids


def _attach_atomic_facts_to_episodes(
    episodes: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    *,
    per_episode: int,
) -> None:
    parent_to_episode_indexes: dict[str, list[int]] = {}
    for index, episode in enumerate(episodes):
        episode["atomic_facts"] = []
        for parent_id in _episode_fact_parent_ids([episode]):
            parent_to_episode_indexes.setdefault(parent_id, []).append(index)

    for fact in facts:
        parent_id = fact.get("parent_id")
        if not isinstance(parent_id, str):
            continue
        for index in parent_to_episode_indexes.get(parent_id, []):
            bucket = episodes[index].setdefault("atomic_facts", [])
            if isinstance(bucket, list) and len(bucket) < per_episode:
                bucket.append(fact)


def _merge_bootstrap_filters(
    primary_filter: dict[str, Any],
    session_filter: dict[str, Any] | None,
) -> dict[str, Any]:
    if not session_filter:
        return primary_filter
    return {"AND": [primary_filter, session_filter]}


def _active_session_filter(active_session_ids: list[str] | None) -> dict[str, Any] | None:
    if active_session_ids is None:
        return None
    if not active_session_ids:
        return {"session_id": "__no_active_sessions__"}
    if len(active_session_ids) == 1:
        return {"session_id": active_session_ids[0]}
    return {"session_id": {"in": active_session_ids}}


async def _list_active_everos_session_ids(
    db_session,
    *,
    project_id: str | None,
    fallback_session_id: uuid.UUID | None,
) -> list[str]:
    from sqlalchemy import select

    from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession

    if project_id:
        result = await db_session.execute(
            select(JoySafeterSession.id)
            .where(
                JoySafeterSession.project_id == project_id,
                JoySafeterSession.archived_at.is_(None),
            )
            .order_by(JoySafeterSession.created_at.desc())
            .limit(1000)
        )
        return [
            _everos_path_safe_id(str(session_id), "default_session")
            for session_id in result.scalars().all()
        ]
    if fallback_session_id is None:
        return []
    return [_everos_path_safe_id(str(fallback_session_id), "default_session")]


async def _build_everos_bootstrap_prompt(
    everos_base_url: str,
    identity: dict[str, str],
    *,
    active_session_ids: list[str] | None = None,
) -> str | None:
    try:
        memories = await _fetch_everos_bootstrap_memories(
            everos_base_url,
            identity,
            active_session_ids=active_session_ids,
        )
    except Exception as exc:
        logger.warning("Failed to fetch EverOS bootstrap memories: %s", exc)
        return None
    return _format_everos_bootstrap_prompt(identity, memories)


def _format_everos_bootstrap_prompt(
    identity: dict[str, str],
    memories: dict[str, list[dict[str, Any]]],
) -> str | None:
    profiles = memories.get("profiles") or []
    episodes = memories.get("episodes") or []
    agent_cases = memories.get("agent_cases") or []
    agent_skills = memories.get("agent_skills") or []
    if not (profiles or episodes or agent_cases or agent_skills):
        return None

    lines = [
        "# EverOS Memory Bootstrap",
        "The following startup memories were loaded for this session as compact context. Treat them as hints, not as exhaustive evidence.",
        f"- app_id: {identity['EVEROS_APP_ID']}",
        f"- project_id: {identity['EVEROS_PROJECT_ID']}",
        f"- session_id: {identity['EVEROS_SESSION_ID']}",
        f"- user_id: {identity['EVEROS_USER_ID']}",
        f"- agent_id: {identity['EVEROS_AGENT_ID']}",
        "",
        "When more detail is needed, load the full memory through the EverOS service instead of guessing from this preview:",
        "- Full user episode/profile/fact records: POST `${EVEROS_BASE_URL}/get` with `app_id`, `project_id`, `user_id`, and `memory_type` set to `episode`, `profile`, or `atomic_fact`.",
        "- Full agent case/skill records: POST `${EVEROS_BASE_URL}/get` with `app_id`, `project_id`, `agent_id`, and `memory_type` set to `agent_case` or `agent_skill`.",
        "- For relevance-based lookup, POST `${EVEROS_BASE_URL}/search` with the same ids and a task-specific query, then use `/get` if a full listing is needed.",
        "- Current `/get` is owner/type paginated; when you already know an id, request a page for that owner/type and match the id in the returned items.",
        f"- Agent skills are loaded progressively: this bootstrap includes up to {EVEROS_BOOTSTRAP_AGENT_SKILL_LIMIT}; use `/get` or `/search` for more.",
        "",
        "Example `/get` bodies:",
        f"- Episode: {json.dumps({'app_id': identity['EVEROS_APP_ID'], 'project_id': identity['EVEROS_PROJECT_ID'], 'user_id': identity['EVEROS_USER_ID'], 'memory_type': 'episode', 'page': 1, 'page_size': 5, 'sort_by': 'timestamp', 'sort_order': 'desc'}, ensure_ascii=False)}",
        f"- Atomic facts: {json.dumps({'app_id': identity['EVEROS_APP_ID'], 'project_id': identity['EVEROS_PROJECT_ID'], 'user_id': identity['EVEROS_USER_ID'], 'memory_type': 'atomic_fact', 'page': 1, 'page_size': 25, 'sort_by': 'timestamp', 'sort_order': 'desc', 'filters': {'parent_id': 'episode_entry_id'}}, ensure_ascii=False)}",
        f"- Agent case: {json.dumps({'app_id': identity['EVEROS_APP_ID'], 'project_id': identity['EVEROS_PROJECT_ID'], 'agent_id': identity['EVEROS_AGENT_ID'], 'memory_type': 'agent_case', 'page': 1, 'page_size': 5, 'sort_by': 'timestamp', 'sort_order': 'desc'}, ensure_ascii=False)}",
        f"- Agent skill: {json.dumps({'app_id': identity['EVEROS_APP_ID'], 'project_id': identity['EVEROS_PROJECT_ID'], 'agent_id': identity['EVEROS_AGENT_ID'], 'memory_type': 'agent_skill', 'page': 1, 'page_size': 5, 'sort_by': 'updated_at', 'sort_order': 'desc'}, ensure_ascii=False)}",
    ]

    if profiles:
        lines.extend(["", "## User Profiles"])
        for profile in profiles:
            profile_data = profile.get("profile_data") or {}
            lines.append(f"- id: {_text(profile.get('id'))}")
            if isinstance(profile_data, dict):
                for key in ("summary", "explicit_info", "implicit_traits"):
                    if key in profile_data:
                        lines.append(f"  - {key}: {_compact_value(profile_data[key])}")
            else:
                lines.append(f"  - profile_data: {_compact_value(profile_data)}")

    if episodes:
        lines.extend(["", f"## Latest User Episodes (up to {EVEROS_BOOTSTRAP_EPISODE_LIMIT})"])
        for episode in episodes[:EVEROS_BOOTSTRAP_EPISODE_LIMIT]:
            lines.append(f"- id: {_text(episode.get('id'))}")
            lines.append(f"  - timestamp: {_text(episode.get('timestamp'))}")
            lines.append(f"  - subject: {_text(episode.get('subject'))}")
            lines.append(f"  - summary: {_text(episode.get('summary'))}")
            facts = episode.get("atomic_facts") or []
            if isinstance(facts, list) and facts:
                lines.append("  - Related Facts:")
                for fact in facts[:EVEROS_BOOTSTRAP_FACT_PER_EPISODE_LIMIT]:
                    if isinstance(fact, dict):
                        lines.append(f"    - {_text(fact.get('fact'))}")

    if agent_cases:
        lines.extend(["", f"## Agent Case Metadata (up to {EVEROS_BOOTSTRAP_AGENT_CASE_LIMIT})"])
        for case in agent_cases[:EVEROS_BOOTSTRAP_AGENT_CASE_LIMIT]:
            lines.append(f"- id: {_text(case.get('id'))}")
            lines.append(f"  - session_id: {_text(case.get('session_id'))}")
            lines.append(f"  - timestamp: {_text(case.get('timestamp'))}")
            lines.append(f"  - task_intent: {_text(case.get('task_intent'))}")
            lines.append(f"  - approach: {_text(case.get('approach'))}")
            lines.append(f"  - key_insight: {_text(case.get('key_insight'))}")
            lines.append(f"  - quality_score: {_text(case.get('quality_score'))}")

    if agent_skills:
        lines.extend(["", f"## Agent Skill Metadata (progressive, up to {EVEROS_BOOTSTRAP_AGENT_SKILL_LIMIT})"])
        for skill in agent_skills[:EVEROS_BOOTSTRAP_AGENT_SKILL_LIMIT]:
            lines.append(f"- id: {_text(skill.get('id'))}")
            lines.append(f"  - name: {_text(skill.get('name'))}")
            lines.append(f"  - description: {_text(skill.get('description'))}")
            lines.append(f"  - confidence: {_text(skill.get('confidence'))}")
            lines.append(f"  - maturity_score: {_text(skill.get('maturity_score'))}")
            lines.append(f"  - source_case_ids: {_compact_value(skill.get('source_case_ids') or [])}")

    prompt = "\n".join(lines)
    if len(prompt) > EVEROS_BOOTSTRAP_MAX_CHARS:
        return prompt[:EVEROS_BOOTSTRAP_MAX_CHARS].rstrip() + "\n[EverOS bootstrap truncated]"
    return prompt


def _compact_value(value: Any) -> str:
    if isinstance(value, str):
        return _text(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _text(value: Any, limit: int = 600) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _policy_type(cfg: dict, default_cfg: dict) -> str:
    """Resolve a config's effective permission_policy type.

    Prefers the config's own policy, falling back to the toolset's
    default_config policy. Returns the ``type`` string (e.g. "always_ask",
    "always_allow") or "" when unset.
    """
    policy = cfg.get("permission_policy")
    if not isinstance(policy, dict) or not policy.get("type"):
        policy = default_cfg.get("permission_policy") or {}
    if isinstance(policy, dict):
        return policy.get("type", "") or ""
    return ""


def _mcp_rule_name(server: str, tool_name: str) -> str:
    """Map an MCP tool config to a Claude permission rule name.

    A bare server name maps to the whole-server wildcard
    ``mcp__<server>__*``; a config that names a specific tool maps to
    ``mcp__<server>__<tool>``. Returns "" when server is empty.
    """
    if not server:
        return ""
    # When the config name equals the server (group-level), use the wildcard.
    if not tool_name or tool_name == server:
        return f"mcp__{server}__*"
    return f"mcp__{server}__{tool_name}"


def _build_permission_rules(agent) -> tuple[list[str], list[str]]:
    """Parse agent toolsets into (allow, ask) permission rule lists.

    Mirrors the Anthropic Managed Agents permission model exactly — the only
    two policies are ``always_allow`` and ``always_ask``; there is no "disable"
    concept. Defaults match the API:

    - ``agent_toolset_20260401`` -> default ``always_allow``
    - ``mcp_toolset``            -> default ``always_ask`` (new MCP tools must
                                    be approved before they run)

    A per-tool ``configs[].permission_policy`` overrides the toolset default.
    MCP tool names are mapped to ``mcp__<server>__*`` rule form.
    """
    allow: list[str] = []
    ask: list[str] = []

    for tool in agent.tools or []:
        if not isinstance(tool, dict):
            continue
        tool_type = tool.get("type", "")
        default_cfg = tool.get("default_config") or {}

        if tool_type == "agent_toolset_20260401":
            for cfg in tool.get("configs") or []:
                if not isinstance(cfg, dict):
                    continue
                name = cfg.get("name", "")
                if not name:
                    continue
                # Agent toolset default is always_allow.
                if _policy_type(cfg, default_cfg) == "always_ask":
                    ask.append(name)
                else:
                    allow.append(name)

        elif tool_type == "mcp_toolset":
            # I15 fix: Rust reads "name", Python historically read
            # "mcp_server_name" — check both.
            server = tool.get("name") or tool.get("mcp_server_name", "")
            configs = tool.get("configs") or []
            if not configs:
                rule = _mcp_rule_name(server, "")
                if rule:
                    # MCP toolset default is always_ask.
                    if _policy_type({}, default_cfg) == "always_allow":
                        allow.append(rule)
                    else:
                        ask.append(rule)
                continue
            for cfg in configs:
                if not isinstance(cfg, dict):
                    continue
                rule = _mcp_rule_name(server, cfg.get("name", ""))
                if not rule:
                    continue
                # MCP toolset default is always_ask.
                if _policy_type(cfg, default_cfg) == "always_allow":
                    allow.append(rule)
                else:
                    ask.append(rule)

    return allow, ask


def build_permissions_dict(
    allow: list[str], ask: list[str]
) -> dict[str, list[str]]:
    """Build a Claude Code settings.json ``permissions`` object.

    Omits empty buckets so the written settings stay minimal.
    """
    perms: dict[str, list[str]] = {}
    if allow:
        perms["allow"] = allow
    if ask:
        perms["ask"] = ask
    return perms


def _extract_max_turns(agent) -> int:
    """Extract max_turns from agent.metadata, default 100."""
    metadata = getattr(agent, "metadata", None) or {}
    if isinstance(metadata, dict):
        return int(metadata.get("max_turns", 100))
    return 100


async def _maybe_refresh_oauth(credential: dict, db_session) -> dict:
    """Refresh OAuth token if within 300s of expiry. Returns updated credential."""
    oauth_config = credential.get("oauth_config")
    if not oauth_config or credential.get("credential_type") != "oauth":
        return credential

    expires_at = oauth_config.get("expires_at", 0)
    if time.time() < expires_at - 300:
        return credential  # still fresh

    token_url = oauth_config.get("token_url")
    if not token_url:
        return credential

    try:
        from app.joysafeter_shared.security.ssrf_guard import validate_url
        validate_url(token_url, context="OAuth token_url refresh")

        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            resp = await client.post(token_url, data={
                "grant_type": "refresh_token",
                "refresh_token": oauth_config.get("refresh_token", ""),
                "client_id": oauth_config.get("client_id", ""),
                "client_secret": oauth_config.get("client_secret", ""),
            })
            resp.raise_for_status()
            token_data = resp.json()

        new_token = token_data["access_token"]
        new_expires_at = time.time() + token_data.get("expires_in", 3600)
        new_refresh = token_data.get("refresh_token", oauth_config.get("refresh_token", ""))

        credential["token_value"] = new_token
        oauth_config["expires_at"] = new_expires_at
        oauth_config["refresh_token"] = new_refresh
        credential["oauth_config"] = oauth_config

        logger.info("Refreshed OAuth token for credential %s", credential.get("id", "?"))
    except Exception as e:
        logger.warning("OAuth refresh failed for credential %s: %s", credential.get("id", "?"), e)

    return credential


def _decrypt_credential_value(value: str) -> str:
    """Decrypt enc:-prefixed credential values using VaultCipher."""
    if _vault_cipher and value:
        try:
            return _vault_cipher.decrypt_or_passthrough(value)
        except Exception as e:
            logger.warning("VaultCipher decryption failed: %s", e)
    return value


async def build_harness_input(
    task,
    agent,
    session_id: Optional[uuid.UUID],
    sandbox_external_id: str,
    sandbox_db_id: uuid.UUID,
    provider_name: Optional[str] = None,
) -> HarnessInput:
    from app.joysafeter_orchestrator.services import MemoryService, SecretService, SessionService, VaultService
    from app.joysafeter_shared.database import AsyncSessionLocal

    env: dict[str, str] = {}
    model = _agent_model_id(agent.model)

    secrets: dict[str, str] = {}
    custom_tools: list[dict[str, Any]] = []
    memory_mounts: list[dict[str, Any]] = []
    memory_system_prompt: Optional[str] = None
    mcp_configs = list(agent.mcp_configs or [])
    harness_session_id: Optional[str] = None
    work_dir = "/workspace" if session_id else sandbox_external_id

    from app.joysafeter_shared.config.settings import joysafeter_config
    workspace_path: Optional[str] = None
    if joysafeter_config.sandbox_workspace_root and session_id:
        workspace_path = os.path.join(
            joysafeter_config.sandbox_workspace_root, str(session_id)
        )

    engine_kind = getattr(agent, "engine_kind", None) or "claude"
    project_id = (
        str(agent.project_id)
        if getattr(agent, "project_id", None) is not None
        else None
    )
    project_slug: Optional[str] = None
    everos_user_id: Optional[str] = None
    everos_user_name: Optional[str] = None
    active_everos_session_ids: Optional[list[str]] = None

    # Resolve environment for setup commands
    environment = None
    environment_config: dict[str, Any] = {}
    environment_ref = getattr(agent, "environment_ref", None)
    if environment_ref:
        from app.joysafeter_orchestrator.services import EnvironmentService
        async with AsyncSessionLocal() as db:
            env_svc = EnvironmentService(db)
            environment = await env_svc.get_environment_by_ref(environment_ref, project_id=project_id)
            environment_config = _environment_config_dict(environment)

    env_vars = environment_config.get("env_vars")
    if isinstance(env_vars, dict):
        env.update({str(k): str(v) for k, v in env_vars.items()})

    # Build setup commands (Rust parity)
    env_setup = _resolve_environment_setup_commands(environment)
    agent_setup = _extract_agent_setup_commands(agent)
    setup_commands = env_setup + agent_setup

    # Parse tool permission rules into allow/ask (official Managed Agents model)
    allowed_tools, ask_tools = _build_permission_rules(agent)

    # Extract max turns (Rust parity)
    max_turns = _extract_max_turns(agent)

    async with AsyncSessionLocal() as db:
        if project_id:
            from sqlalchemy import select as _sa_select

            from app.joysafeter_domain.models.joysafeter_project import Project

            project_result = await db.execute(
                _sa_select(Project.slug).where(Project.id == project_id).limit(1)
            )
            project_slug = project_result.scalar_one_or_none()

        secret_svc = SecretService(db)
        secret_refs = environment_config.get("secret_refs")
        if isinstance(secret_refs, list):
            secrets = await secret_svc.merge_secret_refs_into_env(
                secrets, secret_refs, project_id=project_id
            )

        if getattr(agent, "secret_ref", None):
            secrets = await secret_svc.merge_secret_refs_into_env(
                secrets, [agent.secret_ref], project_id=project_id, override=True
            )
        if secrets:
            model = _resolve_harness_model(
                agent_model=agent.model,
                engine_kind=engine_kind,
                secrets=secrets,
            )
        # Don't merge secrets into env for gRPC. Docker sandboxes receive them
        # via container env; local runtime adapters merge HarnessInput.secrets.

        if session_id:
            session_svc = SessionService(db)
            session = await session_svc.get_session(session_id)
            if session:
                harness_session_id = getattr(session, "last_harness_session_id", None)
                work_dir = _session_container_work_dir(
                    getattr(session, "last_work_dir", None)
                )
                everos_identity_user = await resolve_everos_user_identity_for_session(
                    db,
                    session_id,
                    session=session,
                    project_id=getattr(session, "project_id", None) or project_id,
                )
                everos_user_id = everos_identity_user.joysafeter_user_id
                everos_user_name = everos_identity_user.joysafeter_user_name
            active_everos_session_ids = await _list_active_everos_session_ids(
                db,
                project_id=project_id,
                fallback_session_id=session_id,
            )
            vault_ids = (
                session.vault_ids if session and hasattr(session, "vault_ids") else []
            )
            if vault_ids and mcp_configs:
                vault_svc = VaultService(db)
                mcp_configs = await vault_svc.resolve_mcp_credentials(
                    vault_ids, mcp_configs
                )

        for tool in agent.tools or []:
            if isinstance(tool, dict) and tool.get("type") == "custom":
                custom_tools.append(
                    {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "input_schema": tool.get("input_schema", {}),
                    }
                )

        from app.joysafeter_orchestrator.kernel.legacy_memory import legacy_sandbox_memory_enabled

        if session_id and legacy_sandbox_memory_enabled():
            session_svc = SessionService(db)
            mem_svc = MemoryService(db)
            mem_stores = await session_svc.list_session_memory_stores(session_id)
            if mem_stores:
                prompt_lines = [
                    "# Memory",
                    "The following memory stores are mounted. "
                    "Use them to persist and retrieve information across sessions.",
                    "",
                ]
                for ms in mem_stores:
                    mount_path = f"/mnt/memory/{ms.mount_name}"
                    prompt_lines.append(
                        f"- `{mount_path}` (access: {ms.access})"
                    )
                    if ms.instructions:
                        prompt_lines.append(
                            f"  Instructions: {ms.instructions}"
                        )

                    files = []
                    memories, _ = await mem_svc.list_memories(
                        ms.store_id, limit=10000
                    )
                    for mem in memories:
                        files.append(
                            {"path": mem.path, "content": mem.content}
                        )

                    memory_mounts.append(
                        {
                            "mount_name": ms.mount_name,
                            "store_id": f"memstore_{ms.store_id}",
                            "raw_store_id": str(ms.store_id),
                            "access": ms.access,
                            "instructions": ms.instructions,
                            "files": files,
                        }
                    )

                memory_system_prompt = "\n".join(prompt_lines)

    env.update({str(k): str(v) for k, v in (agent.env or {}).items()})
    everos_base_url = _resolve_everos_base_url()
    env["EVEROS_BASE_URL"] = everos_base_url
    everos_identity = _build_everos_identity_env(
        project_id=project_id,
        project_slug=project_slug,
        session_id=session_id or sandbox_external_id,
        user_id=everos_user_id,
        user_name=everos_user_name,
        agent_id=getattr(agent, "id", None) or engine_kind,
    )
    env.update(everos_identity)
    if active_everos_session_ids is not None:
        env["EVEROS_ACTIVE_SESSION_IDS"] = json.dumps(active_everos_session_ids, ensure_ascii=False)

    if memory_mounts and session_id:
        from app.joysafeter_orchestrator.kernel.memory_sync import MemorySessionEntry
        from app.joysafeter_orchestrator.lifespan import get_memory_subscribers

        subs = get_memory_subscribers()
        if subs:
            for mm in memory_mounts:
                await subs.register(
                    uuid.UUID(mm["raw_store_id"]),
                    MemorySessionEntry(
                        session_id=session_id,
                        sandbox_db_id=sandbox_db_id,
                        mount_name=mm["mount_name"],
                    ),
                )

    skill_archives: list[SkillArchive] = []
    for target, items in [
        ("skills", agent.skills or []),
        ("agents", getattr(agent, "agents", None) or []),
        ("commands", getattr(agent, "commands", None) or []),
    ]:
        for item in items:
            if isinstance(item, dict) and item.get("tar_gz_b64"):
                try:
                    data = base64.b64decode(item["tar_gz_b64"])
                    skill_archives.append(SkillArchive(
                        name=item.get("name", "unknown"),
                        data=data,
                        target=target,
                    ))
                except Exception as e:
                    logger.warning("Failed to decode skill archive %s: %s", item.get("name"), e)
            elif isinstance(item, dict) and item.get("skill_id"):
                from app.joysafeter_orchestrator.services import SkillPacker
                async with AsyncSessionLocal() as packer_db:
                    packer = SkillPacker(
                        packer_db,
                        project_id=str(agent.project_id) if agent.project_id else None,
                        # Audit ids for ``SkillUsageLog``. Each is optional;
                        # the log row carries NULL for any id we can't
                        # resolve at this point. ``user_id`` isn't on the
                        # task model, so it stays NULL until the API
                        # adds it.
                        session_id=str(session_id) if session_id else None,
                        agent_id=str(agent.id) if getattr(agent, "id", None) else None,
                        user_id=None,
                    )
                    archive = await packer._pack_custom(
                        item["skill_id"], item.get("version", "latest"), target
                    )
                    if archive:
                        skill_archives.append(archive)
                    # Commit the usage_log row (and any audit-only writes
                    # ``_record_usage`` did) since this DB session is scoped
                    # to the packer alone.
                    await packer_db.commit()

    base_system = task.system_prompt or agent.system_prompt or ""
    if memory_system_prompt:
        combined_system = (
            f"{base_system}\n\n{memory_system_prompt}"
            if base_system
            else memory_system_prompt
        )
    else:
        combined_system = base_system or None

    combined_system = _append_everos_system_prompt(
        combined_system,
        everos_base_url,
        everos_identity,
        active_session_ids=active_everos_session_ids,
    )
    everos_bootstrap_prompt = await _build_everos_bootstrap_prompt(
        everos_base_url,
        everos_identity,
        active_session_ids=active_everos_session_ids,
    )
    if everos_bootstrap_prompt:
        combined_system = f"{combined_system}\n\n{everos_bootstrap_prompt}"

    prompt = task.prompt
    has_harness_resume = bool(harness_session_id and harness_session_id.strip())
    if _should_inject_conversation_history(engine_kind, has_harness_resume) and session_id:
        history = await _build_conversation_history(session_id, task.id)
        if history:
            logger.debug("Conversation history injected (%d chars) for session=%s", len(history), session_id)
            prompt = f"{history}\n\n{prompt}"

    # Load session file resources for gRPC transfer
    from app.joysafeter_orchestrator.runtime.adapter import FileMount, FileRef
    from app.joysafeter_orchestrator.sandbox.file_injection import load_session_files
    file_mounts: list[FileMount] = []
    file_refs: list[FileRef] = []
    if session_id:
        session_files = await load_session_files(session_id)
        if session_files:
            from app.joysafeter_shared.storage import get_storage
            storage = get_storage()
            inline_file_mounts = _should_inline_session_file_mounts(
                session_files, workspace_path
            )
            for sf in session_files:
                if inline_file_mounts:
                    try:
                        data = await storage.get(sf.storage_key)
                        file_mounts.append(FileMount(
                            path=sf.mount_path,
                            content=data,
                            filename=sf.filename,
                        ))
                    except Exception as e:
                        logger.warning("Failed to load file %s: %s", sf.filename, e)
                # Generate presigned URL if storage supports it
                try:
                    url = await storage.presign_url(sf.storage_key, expires=3600)
                    if url:
                        file_refs.append(FileRef(
                            path=sf.mount_path,
                            url=url,
                            filename=sf.filename,
                            size_bytes=sf.size_bytes,
                        ))
                except Exception:
                    pass

    # Load session repo resources (github_repository) for cloning in the sandbox.
    # Tokens are decrypted here and never logged.
    repos: list[dict[str, Any]] = []
    if session_id:
        from sqlalchemy import select as _sa_select

        from app.joysafeter_domain.models.joysafeter_session_repo import (
            JoySafeterSessionRepo,
        )

        async with AsyncSessionLocal() as repo_db:
            secret_svc = SecretService(repo_db)
            result = await repo_db.execute(
                _sa_select(JoySafeterSessionRepo)
                .where(JoySafeterSessionRepo.session_id == session_id)
                .order_by(JoySafeterSessionRepo.created_at)
            )
            for rr in result.scalars().all():
                token = ""
                if rr.encrypted_token:
                    try:
                        token = secret_svc.decrypt_data({"token": rr.encrypted_token})["token"]
                    except Exception:
                        logger.warning("Failed to decrypt clone token for repo resource %s", rr.id)
                        continue
                repos.append({
                    "url": rr.url,
                    "branch": rr.branch or "",
                    "path": rr.mount_path or "",
                    "authorization_token": token,
                    "mount_name": rr.mount_name or "",
                })

    return HarnessInput(
        prompt=prompt,
        system_prompt=combined_system,
        env=env,
        work_dir=work_dir,
        session_id=harness_session_id,
        permission_mode=extract_permission_mode(agent.tools),
        model=model,
        mcp_servers=mcp_configs,
        skills=agent.skills or [],
        tools=agent.tools or [],
        secrets=secrets,
        workspace_path=workspace_path,
        custom_tools=custom_tools,
        memory_mounts=memory_mounts,
        memory_system_prompt=memory_system_prompt,
        skill_archives=skill_archives,
        file_mounts=file_mounts,
        file_refs=file_refs,
        # Rust-parity fields
        provider=engine_kind,
        setup_commands=setup_commands,
        allowed_tools=allowed_tools,
        ask_tools=ask_tools,
        max_turns=max_turns,
        repos=repos,
    )


def extract_permission_mode(tools: list) -> str:
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        tool_type = tool.get("type", "")
        if tool_type in ("agent_toolset_20260401", "mcp_toolset"):
            default_cfg = tool.get("default_config") or {}
            policy = default_cfg.get("permission_policy") or {}
            if isinstance(policy, dict) and policy.get("type") == "always_ask":
                return "default"
            for cfg in tool.get("configs") or []:
                if isinstance(cfg, dict):
                    cp = cfg.get("permission_policy") or {}
                    if isinstance(cp, dict) and cp.get("type") == "always_ask":
                        return "default"
    return "bypassPermissions"


def extract_tool_name_sets(agent) -> tuple[set[str], set[str]]:
    custom_names: set[str] = set()
    mcp_names: set[str] = set()

    for tool in agent.tools or []:
        if isinstance(tool, dict):
            if tool.get("type") == "custom":
                custom_names.add(tool["name"])
            elif tool.get("type") == "mcp_toolset":
                # I15 fix: Rust reads "name", Python historically read "mcp_server_name" — check both
                name = tool.get("name") or tool.get("mcp_server_name", "")
                if name:
                    mcp_names.add(name)

    for cfg in agent.mcp_configs or []:
        if isinstance(cfg, dict):
            name = cfg.get("name", "")
            if name:
                mcp_names.add(name)

    return custom_names, mcp_names


def _should_inject_conversation_history(
    engine_kind: str, has_harness_resume: bool
) -> bool:
    return engine_kind in {"claude", "codex", "native"} and not has_harness_resume


def _extract_content_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    content = payload.get("content")
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()

    return ""


async def _build_conversation_history(
    session_id: uuid.UUID, current_task_id: uuid.UUID
) -> Optional[str]:
    """Build conversation history for CLI agents from session events.

    Uses persisted session events (user.message + agent.message) rather than
    tasks, since tasks may be retried/re-queued after sandbox death.
    """
    from sqlalchemy import text

    from app.joysafeter_shared.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        current_turn_running_seq = await db.scalar(
            text(
                """
                SELECT MAX(seq) FROM joysafeter_session_events
                WHERE session_id = :session_id
                  AND event_type = 'session.status_running'
                  AND payload->>'task_id' = :task_id
                """
            ),
            {"session_id": session_id, "task_id": str(current_task_id)},
        )

        boundary_seq = current_turn_running_seq
        if current_turn_running_seq is not None:
            current_turn_user_msg_seq = await db.scalar(
                text(
                    """
                    SELECT MAX(seq) FROM joysafeter_session_events
                    WHERE session_id = :session_id
                      AND event_type = 'user.message'
                      AND seq < :running_seq
                    """
                ),
                {"session_id": session_id, "running_seq": current_turn_running_seq},
            )
            boundary_seq = current_turn_user_msg_seq or current_turn_running_seq

        result = await db.execute(
            text(
                """
                SELECT event_type, payload, seq FROM (
                    SELECT event_type, payload, seq, created_at
                    FROM joysafeter_session_events
                    WHERE session_id = :session_id
                      AND (CAST(:boundary_seq AS BIGINT) IS NULL OR seq < :boundary_seq)
                    ORDER BY seq DESC, created_at DESC
                    LIMIT :limit
                ) recent
                ORDER BY seq ASC, created_at ASC
                """
            ),
            {
                "session_id": session_id,
                "boundary_seq": boundary_seq,
                "limit": CONVERSATION_HISTORY_EVENT_LIMIT,
            },
        )
        events = list(result.mappings().all())

    if not events:
        return None

    # Build conversation from user.message and agent.message events BEFORE current turn
    lines = []
    current_user_msg = None
    current_agent_parts: list[str] = []

    for evt in events:
        event_type = evt["event_type"]
        payload = evt["payload"]
        if event_type == "user.message":
            # Flush previous exchange
            if current_user_msg is not None:
                lines.append(f"User: {current_user_msg}")
                if current_agent_parts:
                    lines.append(f"Assistant: {''.join(current_agent_parts)}")
                current_agent_parts = []

            text = _extract_content_text(payload)
            current_user_msg = text or None

        elif event_type == "agent.message" and current_user_msg is not None:
            text = _extract_content_text(payload)
            if text:
                current_agent_parts.append(text)

    # Flush last exchange
    if current_user_msg is not None:
        lines.append(f"User: {current_user_msg}")
        if current_agent_parts:
            lines.append(f"Assistant: {''.join(current_agent_parts)}")

    if not lines:
        return None

    header = "[CONVERSATION HISTORY - Prior turns in this session]"
    footer = "[END CONVERSATION HISTORY]"
    body = _trim_history_lines_to_budget(lines, CONVERSATION_HISTORY_MAX_CHARS)
    if not body:
        return None
    return f"{header}\n{body}\n{footer}"


def _trim_history_lines_to_budget(lines: list[str], max_chars: int) -> str:
    if not lines or max_chars <= 0:
        return ""

    selected: list[str] = []
    used = 0
    for line in reversed(lines):
        separator_chars = 0 if not selected else 2
        line_chars = len(line)
        if used + separator_chars + line_chars <= max_chars:
            used += separator_chars + line_chars
            selected.append(line)
            continue

        if not selected:
            remaining = max_chars - separator_chars
            selected.append(_truncate_start(line, remaining))
        break

    selected.reverse()
    return "\n\n".join(line for line in selected if line)


def _truncate_start(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    if max_chars <= 0:
        return ""
    prefix = "..."
    if max_chars <= len(prefix):
        return value[-max_chars:]
    return f"{prefix}{value[-(max_chars - len(prefix)):]}"
