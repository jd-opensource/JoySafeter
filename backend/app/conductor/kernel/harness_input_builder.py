import base64
import logging
import uuid
from typing import Any, Optional

from app.conductor.runtime.adapter import HarnessInput, SkillArchive

logger = logging.getLogger(__name__)


async def build_harness_input(
    task,
    agent,
    session_id: Optional[uuid.UUID],
    sandbox_external_id: str,
    sandbox_db_id: uuid.UUID,
) -> HarnessInput:
    from app.core.database import AsyncSessionLocal
    from app.conductor.services.secret_service import SecretService
    from app.conductor.services.vault_service import VaultService
    from app.conductor.services.session_service import SessionService
    from app.conductor.services.memory_service import MemoryService

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

    async with AsyncSessionLocal() as db:
        if getattr(agent, "secret_ref", None):
            secret_svc = SecretService(db)
            secret = await secret_svc.get_secret_by_name(agent.secret_ref)
            if secret and secret.data:
                secrets = {k: str(v) for k, v in secret.data.items()}
                if "ANTHROPIC_AUTH_TOKEN" in secrets and "ANTHROPIC_API_KEY" not in secrets:
                    secrets["ANTHROPIC_API_KEY"] = secrets["ANTHROPIC_AUTH_TOKEN"]
                env.update(secrets)

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
                        ms.store_id, limit=500
                    )
                    for mem in memories:
                        files.append(
                            {"path": mem.path, "content": mem.content}
                        )

                    memory_mounts.append(
                        {
                            "mount_name": ms.mount_name,
                            "store_id": str(ms.store_id),
                            "access": ms.access,
                            "instructions": ms.instructions,
                            "files": files,
                        }
                    )

                memory_system_prompt = "\n".join(prompt_lines)

    if memory_mounts and session_id:
        from app.conductor.lifespan import get_memory_subscribers
        from app.conductor.kernel.memory_sync import MemorySessionEntry

        subs = get_memory_subscribers()
        if subs:
            for mm in memory_mounts:
                await subs.register(
                    uuid.UUID(mm["store_id"]),
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

    base_system = task.system_prompt or agent.system_prompt or ""
    if memory_system_prompt:
        combined_system = (
            f"{base_system}\n\n{memory_system_prompt}"
            if base_system
            else memory_system_prompt
        )
    else:
        combined_system = base_system or None

    return HarnessInput(
        prompt=task.prompt,
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
        custom_tools=custom_tools,
        memory_mounts=memory_mounts,
        memory_system_prompt=memory_system_prompt,
        skill_archives=skill_archives,
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
                name = tool.get("mcp_server_name", "")
                if name:
                    mcp_names.add(name)

    for cfg in agent.mcp_configs or []:
        if isinstance(cfg, dict):
            name = cfg.get("name", "")
            if name:
                mcp_names.add(name)

    return custom_names, mcp_names
