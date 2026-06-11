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

# ------------------------------------------------------------------
# Builder helpers — Rust parity (harness_input_builder.rs)
# ------------------------------------------------------------------

_vault_cipher: VaultCipher | None = VaultCipher.from_env()


def _resolve_environment_setup_commands(environment) -> list[str]:
    """Generate apt/pip/npm/cargo/gem/go install commands from environment config."""
    if not environment:
        return []
    config = getattr(environment, "config", None) or {}
    if isinstance(config, dict):
        packages = config.get("packages", {})
    else:
        packages = getattr(config, "packages", {}) or {}

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


def _extract_agent_setup_commands(agent) -> list[str]:
    """Extract setup_commands from agent.metadata."""
    metadata = getattr(agent, "metadata", None) or {}
    if isinstance(metadata, dict):
        return list(metadata.get("setup_commands", []))
    return []


def _parse_tool_allow_lists(agent) -> tuple[list[str], list[str]]:
    """Parse agent_toolset_20260401 into allowed/disallowed tool lists.

    Reads from the nested ``configs[]`` array inside each toolset entry,
    matching Rust ``parse_tool_allow_lists`` (harness_input_builder.rs).
    """
    tools = agent.tools or []
    allowed: list[str] = []
    disallowed: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") != "agent_toolset_20260401":
            continue
        # Rust reads from nested configs[] array
        configs = tool.get("configs") or []
        for cfg in configs:
            if not isinstance(cfg, dict):
                continue
            cfg_name = cfg.get("name", "")
            if not cfg_name:
                continue
            if cfg.get("enabled", True):
                allowed.append(cfg_name)
            else:
                disallowed.append(cfg_name)
    return allowed, disallowed


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
    from app.joysafeter_shared.database import AsyncSessionLocal
    from app.joysafeter_orchestrator.services import SecretService
    from app.joysafeter_orchestrator.services import VaultService
    from app.joysafeter_orchestrator.services import SessionService
    from app.joysafeter_orchestrator.services import MemoryService

    env = dict(agent.env or {})
    model = None
    if agent.model:
        model = (
            agent.model.get("id")
            if isinstance(agent.model, dict)
            else str(agent.model)
        )

    secrets: dict[str, str] = {}
    custom_tools: list[dict[str, Any]] = []
    memory_mounts: list[dict[str, Any]] = []
    memory_system_prompt: Optional[str] = None
    mcp_configs = list(agent.mcp_configs or [])
    harness_session_id: Optional[str] = None

    from app.joysafeter_shared.config.settings import joysafeter_config
    workspace_path: Optional[str] = None
    if joysafeter_config.sandbox_workspace_root and session_id:
        workspace_path = os.path.join(
            joysafeter_config.sandbox_workspace_root, str(session_id)
        )

    engine_kind = getattr(agent, "engine_kind", None) or "claude"

    # Resolve environment for setup commands
    environment = None
    environment_ref = getattr(agent, "environment_ref", None)
    if environment_ref:
        from app.joysafeter_orchestrator.services import EnvironmentService
        async with AsyncSessionLocal() as db:
            env_svc = EnvironmentService(db)
            environment = await env_svc.get_environment_by_ref(environment_ref)

    # Build setup commands (Rust parity)
    env_setup = _resolve_environment_setup_commands(environment)
    agent_setup = _extract_agent_setup_commands(agent)
    setup_commands = env_setup + agent_setup

    # Parse tool allow lists (Rust parity)
    allowed_tools, disallowed_tools = _parse_tool_allow_lists(agent)

    # Extract max turns (Rust parity)
    max_turns = _extract_max_turns(agent)

    async with AsyncSessionLocal() as db:
        if getattr(agent, "secret_ref", None):
            secret_svc = SecretService(db)
            secret = await secret_svc.get_secret_by_name(
                agent.secret_ref, project_id=str(agent.project_id)
            )
            if secret and secret.data:
                secrets = {k: str(v) for k, v in secret.data.items()}
                if "ANTHROPIC_AUTH_TOKEN" in secrets and "ANTHROPIC_API_KEY" not in secrets:
                    secrets["ANTHROPIC_API_KEY"] = secrets["ANTHROPIC_AUTH_TOKEN"]
                if not model and secrets.get("ANTHROPIC_MODEL"):
                    model = secrets["ANTHROPIC_MODEL"]
                # Don't merge secrets into env — they are injected via container env at creation time

        if session_id:
            session_svc = SessionService(db)
            session = await session_svc.get_session(session_id)
            if session:
                harness_session_id = getattr(session, "last_harness_session_id", None)
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

    if memory_mounts and session_id:
        from app.joysafeter_orchestrator.lifespan import get_memory_subscribers
        from app.joysafeter_orchestrator.kernel.memory_sync import MemorySessionEntry

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
                    packer = SkillPacker(packer_db)
                    archive = await packer._pack_custom(
                        item["skill_id"], item.get("version", "latest"), target
                    )
                    if archive:
                        skill_archives.append(archive)

    base_system = task.system_prompt or agent.system_prompt or ""
    if memory_system_prompt:
        combined_system = (
            f"{base_system}\n\n{memory_system_prompt}"
            if base_system
            else memory_system_prompt
        )
    else:
        combined_system = base_system or None

    prompt = task.prompt
    if engine_kind == "codex" and session_id:
        history = await _build_codex_conversation_history(session_id, task.id)
        if history:
            logger.debug("Codex history injected (%d chars) for session=%s", len(history), session_id)
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

    return HarnessInput(
        prompt=prompt,
        system_prompt=combined_system,
        env=env,
        work_dir=sandbox_external_id,
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
        disallowed_tools=disallowed_tools,
        max_turns=max_turns,
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


async def _build_codex_conversation_history(
    session_id: uuid.UUID, current_task_id: uuid.UUID
) -> Optional[str]:
    """Build conversation history for codex agents from session events.

    Uses persisted session events (user.message + agent.message) rather than
    tasks, since tasks may be retried/re-queued after sandbox death.
    """
    from app.joysafeter_shared.database import AsyncSessionLocal
    from app.joysafeter_orchestrator.services import SessionService

    async with AsyncSessionLocal() as db:
        session_svc = SessionService(db)
        events, _ = await session_svc.list_events(session_id, limit=500)

    if not events:
        return None

    # Find the current turn's status_running event to know where prior history ends
    # The user.message event immediately before status_running is part of the CURRENT turn
    current_turn_start_seq = None
    current_turn_user_msg_seq = None
    for evt in events:
        if evt.event_type == "session.status_running":
            payload = evt.payload if isinstance(evt.payload, dict) else {}
            if payload.get("task_id") == str(current_task_id):
                current_turn_start_seq = evt.seq
                break
        if evt.event_type == "user.message":
            current_turn_user_msg_seq = evt.seq

    # The user.message right before current turn's status_running is the current prompt
    # Exclude it from history by using its seq as the boundary
    boundary_seq = current_turn_user_msg_seq if current_turn_user_msg_seq else current_turn_start_seq

    # Build conversation from user.message and agent.message events BEFORE current turn
    lines = []
    current_user_msg = None
    current_agent_parts: list[str] = []

    for evt in events:
        # Stop at the current turn's boundary (user.message for current turn)
        if boundary_seq and evt.seq >= boundary_seq:
            break

        if evt.event_type == "user.message":
            # Flush previous exchange
            if current_user_msg is not None:
                lines.append(f"\nUser: {current_user_msg}")
                if current_agent_parts:
                    lines.append(f"Assistant: {''.join(current_agent_parts)}")
                current_agent_parts = []

            # Extract user message text
            payload = evt.payload if isinstance(evt.payload, dict) else {}
            content = payload.get("content", [])
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            current_user_msg = "".join(text_parts) if text_parts else None

        elif evt.event_type == "agent.message" and current_user_msg is not None:
            payload = evt.payload if isinstance(evt.payload, dict) else {}
            content = payload.get("content", [])
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    current_agent_parts.append(block.get("text", ""))

    # Flush last exchange
    if current_user_msg is not None:
        lines.append(f"\nUser: {current_user_msg}")
        if current_agent_parts:
            lines.append(f"Assistant: {''.join(current_agent_parts)}")

    if not lines:
        return None

    header = "[CONVERSATION HISTORY - Prior turns in this session]"
    footer = "\n[END CONVERSATION HISTORY]\n"
    return f"{header}\n{''.join(lines)}\n{footer}"
