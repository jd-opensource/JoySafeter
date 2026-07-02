import base64
import logging
import os
import time
import uuid
from typing import Any, Optional

import httpx

from app.joysafeter_orchestrator.kernel.vault_cipher import VaultCipher
from app.joysafeter_orchestrator.runtime.adapter import HarnessInput, SkillArchive

logger = logging.getLogger(__name__)

CONVERSATION_HISTORY_EVENT_LIMIT = 100
CONVERSATION_HISTORY_MAX_CHARS = 24_000

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
        dumped = config.model_dump()
        return dumped if isinstance(dumped, dict) else {}
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


def build_permissions_dict(allow: list[str], ask: list[str]) -> dict[str, list[str]]:
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
            resp = await client.post(
                token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": oauth_config.get("refresh_token", ""),
                    "client_id": oauth_config.get("client_id", ""),
                    "client_secret": oauth_config.get("client_secret", ""),
                },
            )
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
    model = None
    if agent.model:
        model = agent.model.get("id") if isinstance(agent.model, dict) else str(agent.model)

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
        workspace_path = os.path.join(joysafeter_config.sandbox_workspace_root, str(session_id))

    engine_kind = getattr(agent, "engine_kind", None) or "claude"
    project_id = str(agent.project_id) if getattr(agent, "project_id", None) is not None else None

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
        secret_svc = SecretService(db)
        secret_refs = environment_config.get("secret_refs")
        if isinstance(secret_refs, list):
            secrets = await secret_svc.merge_secret_refs_into_env(secrets, secret_refs, project_id=project_id)

        if getattr(agent, "secret_ref", None):
            secrets = await secret_svc.merge_secret_refs_into_env(
                secrets, [agent.secret_ref], project_id=project_id, override=True
            )
        if secrets and not model:
            if engine_kind == "codex":
                model = secrets.get("OPENAI_MODEL")
            else:
                # claude / native: prefer Anthropic model, but fall back to
                # OPENAI_MODEL so a native agent configured with an OpenAI-
                # compatible secret (OPENAI_API_KEY/BASE_URL) still resolves a model.
                model = secrets.get("ANTHROPIC_MODEL") or secrets.get("OPENAI_MODEL") or secrets.get("MODEL")
        # Don't merge secrets into env for gRPC. Docker sandboxes receive them
        # via container env; local runtime adapters merge HarnessInput.secrets.

        if session_id:
            session_svc = SessionService(db)
            session = await session_svc.get_session(session_id)
            if session:
                harness_session_id = getattr(session, "last_harness_session_id", None)
                work_dir = _session_container_work_dir(getattr(session, "last_work_dir", None))
            vault_ids = session.vault_ids if session and hasattr(session, "vault_ids") else []
            if vault_ids and mcp_configs:
                vault_svc = VaultService(db)
                mcp_configs = await vault_svc.resolve_mcp_credentials(vault_ids, mcp_configs)

        for tool in agent.tools or []:
            if isinstance(tool, dict) and tool.get("type") == "custom":
                custom_tools.append(
                    {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "input_schema": tool.get("input_schema", {}),
                    }
                )

        if session_id:
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
                    prompt_lines.append(f"- `{mount_path}` (access: {ms.access})")
                    if ms.instructions:
                        prompt_lines.append(f"  Instructions: {ms.instructions}")

                    files = []
                    memories, _ = await mem_svc.list_memories(ms.store_id, limit=10000)
                    for mem in memories:
                        files.append({"path": mem.path, "content": mem.content})

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
                    skill_archives.append(
                        SkillArchive(
                            name=item.get("name", "unknown"),
                            data=data,
                            target=target,
                        )
                    )
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
                    archive = await packer._pack_custom(item["skill_id"], item.get("version", "latest"), target)
                    if archive:
                        skill_archives.append(archive)
                    # Commit the usage_log row (and any audit-only writes
                    # ``_record_usage`` did) since this DB session is scoped
                    # to the packer alone.
                    await packer_db.commit()

    base_system = task.system_prompt or agent.system_prompt or ""
    combined_system: str | None
    if memory_system_prompt:
        combined_system = f"{base_system}\n\n{memory_system_prompt}" if base_system else memory_system_prompt
    else:
        combined_system = base_system or None

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
            for sf in session_files:
                try:
                    data = await storage.get(sf.storage_key)
                    file_mounts.append(
                        FileMount(
                            path=sf.mount_path,
                            content=data,
                            filename=sf.filename,
                        )
                    )
                except Exception as e:
                    logger.warning("Failed to load file %s: %s", sf.filename, e)
                # Generate presigned URL if storage supports it
                try:
                    url = await storage.presign_url(sf.storage_key, expires=3600)
                    if url:
                        file_refs.append(
                            FileRef(
                                path=sf.mount_path,
                                url=url,
                                filename=sf.filename,
                                size_bytes=sf.size_bytes,
                            )
                        )
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
                repos.append(
                    {
                        "url": rr.url,
                        "branch": rr.branch or "",
                        "path": rr.mount_path or "",
                        "authorization_token": token,
                        "mount_name": rr.mount_name or "",
                    }
                )

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


def _should_inject_conversation_history(engine_kind: str, has_harness_resume: bool) -> bool:
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


async def _build_conversation_history(session_id: uuid.UUID, current_task_id: uuid.UUID) -> Optional[str]:
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

            text_content = _extract_content_text(payload)
            current_user_msg = text_content or None

        elif event_type == "agent.message" and current_user_msg is not None:
            text_content = _extract_content_text(payload)
            if text_content:
                current_agent_parts.append(text_content)

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
    return f"{prefix}{value[-(max_chars - len(prefix)) :]}"
