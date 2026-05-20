import asyncio
import logging
import uuid

from app.conductor.kernel.queue import QueueBackend

logger = logging.getLogger(__name__)


class TaskScheduler:
    def __init__(self, queue: QueueBackend, max_concurrent: int = 10):
        self._queue = queue
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running = True

    async def run(self) -> None:
        logger.info("TaskScheduler started (max_concurrent=%d)", self._semaphore._value)
        while self._running:
            await self._semaphore.acquire()
            task_id = await self._queue.pop_global(timeout=30)
            if task_id is None:
                self._semaphore.release()
                continue
            logger.info("Scheduler picked up task %s", task_id)
            asyncio.create_task(self._schedule_task(task_id))

    async def _schedule_task(self, task_id: uuid.UUID) -> None:
        try:
            from app.core.database import AsyncSessionLocal
            from app.conductor.services.task_service import TaskService
            from app.conductor.services.agent_service import AgentService
            from app.conductor.services.session_service import SessionService
            from app.conductor.lifespan import (
                get_bridge_registry,
                get_sandbox_resolver,
            )

            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                agent_svc = AgentService(db)
                session_svc = SessionService(db)

                claimed = await task_svc.claim_task_for_scheduling(task_id)
                if not claimed:
                    logger.warning("Task %s not pending, skipping", task_id)
                    return

                task = await task_svc.get_task(task_id)
                if not task:
                    logger.error("Task %s not found after claim", task_id)
                    return

                agent = await agent_svc.get_agent(task.agent_id)
                if not agent:
                    from app.conductor.models.task import TaskStatus
                    await task_svc.update_task_status(
                        task_id, TaskStatus.FAILED, error="Agent not found"
                    )
                    return

                # Auto-create session if not provided
                session_id = task.chat_session_id
                if not session_id:
                    session = await session_svc.create_session(
                        agent_id=agent.id,
                        title="Auto-created",
                        agent_version=agent.version,
                        agent_snapshot={
                            "name": agent.name,
                            "description": agent.description,
                            "model": agent.model,
                            "system_prompt": agent.system_prompt,
                            "tools": agent.tools,
                            "skills": agent.skills,
                            "mcp_configs": agent.mcp_configs,
                            "multiagent": agent.multiagent,
                            "engine_kind": agent.engine_kind,
                            "permission_mode": agent.permission_mode,
                        },
                    )
                    session_id = session.id
                    task.chat_session_id = session_id
                    await db.commit()

                agent_env = dict(agent.env or {})

                # Resolve secrets so they are injected as Docker env vars.
                # The Rust runner does not reliably forward gRPC-level secrets
                # to the CLI subprocess, so we bake them into the container env.
                if getattr(agent, "secret_ref", None):
                    from app.conductor.services.secret_service import SecretService
                    secret_svc = SecretService(db)
                    secret = await secret_svc.get_secret_by_name(agent.secret_ref)
                    if secret and secret.data:
                        for k, v in secret.data.items():
                            agent_env.setdefault(k, str(v))
                        if "ANTHROPIC_AUTH_TOKEN" in agent_env and "ANTHROPIC_API_KEY" not in agent_env:
                            agent_env["ANTHROPIC_API_KEY"] = agent_env["ANTHROPIC_AUTH_TOKEN"]

                # Resolve environment_ref → image + networking
                env_ref = None
                if session_id and task.chat_session_id:
                    session = await session_svc.get_session(session_id)
                    if session:
                        env_ref = session.environment_ref
                if not env_ref:
                    env_ref = agent.environment_ref

                resolved_image = None
                networking = None
                if env_ref:
                    from app.conductor.services.environment_service import EnvironmentService
                    env_svc = EnvironmentService(db)
                    environment = await env_svc.get_environment_by_ref(env_ref)
                    if environment:
                        resolved_image = environment.image_tag
                        config = environment.config or {}
                        net_cfg = config.get("networking")
                        if net_cfg and isinstance(net_cfg, dict):
                            networking = net_cfg
                            # Auto-add MCP server hostnames if networking is limited
                            if net_cfg.get("type") == "limited" and net_cfg.get("allow_mcp_servers"):
                                allowed = list(net_cfg.get("allowed_hosts", []))
                                for mcp in (agent.mcp_configs or []):
                                    if isinstance(mcp, dict) and mcp.get("url"):
                                        host = _extract_host(mcp["url"])
                                        if host and host not in allowed:
                                            allowed.append(host)
                                networking = {**net_cfg, "allowed_hosts": allowed}

            # Resolve sandbox using the full 3-stage resolver
            resolver = get_sandbox_resolver()
            if resolver:
                resolved = await resolver.resolve(
                    session_id, agent_env, image=resolved_image, networking=networking
                )
                sandbox_id = resolved["sandbox_id"]
                external_id = resolved["external_id"]
            else:
                # Fallback: use basic sandbox service
                from app.conductor.services.sandbox_service import SandboxService
                from app.conductor.config import conductor_config
                async with AsyncSessionLocal() as db:
                    sandbox_svc = SandboxService(db)
                    sandbox = await sandbox_svc.find_by_session(session_id)
                    if not sandbox:
                        sandbox = await sandbox_svc.claim_from_pool(session_id)
                    if not sandbox:
                        sandbox = await sandbox_svc.create_sandbox(
                            image=conductor_config.sandbox_image,
                            provider=conductor_config.sandbox_provider,
                            chat_session_id=session_id,
                        )
                    sandbox_id = sandbox.id
                    external_id = sandbox.external_id

            # CAS: scheduling → claimed
            from app.conductor.models.task import TaskStatus
            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                await task_svc.update_task_status(
                    task_id, TaskStatus.CLAIMED, sandbox_id=sandbox_id
                )

            # Register bridge
            bridge_registry = get_bridge_registry()

            if bridge_registry:
                await bridge_registry.register(sandbox_id, external_id)

            # HA: register sandbox ownership and task-sandbox mapping
            from app.conductor.lifespan import get_redis_coordinator

            coordinator = get_redis_coordinator()
            if coordinator:
                await coordinator.register_sandbox_owner(sandbox_id)
                await coordinator.set_task_sandbox(task_id, sandbox_id)

            # Push task to sandbox queue.
            # The gRPC Session handler's outer loop (pop_for_sandbox) will pick it up.
            await self._queue.push_to_sandbox(sandbox_id, task_id)
            logger.info("Task %s pushed to sandbox queue %s", task_id, sandbox_id)

        except Exception as e:
            logger.error("Failed to schedule task %s: %s", task_id, e)
            try:
                from app.core.database import AsyncSessionLocal
                from app.conductor.services.task_service import TaskService
                from app.conductor.models.task import TaskStatus
                async with AsyncSessionLocal() as db:
                    svc = TaskService(db)
                    await svc.update_task_status(
                        task_id, TaskStatus.FAILED, error=f"Schedule failed: {e}"
                    )
            except Exception as inner:
                logger.error("Failed to mark task %s as failed: %s", task_id, inner)
        finally:
            self._semaphore.release()

    async def push_to_global(self, task_id: uuid.UUID) -> None:
        await self._queue.push_global(task_id)

    def stop(self) -> None:
        self._running = False


def _extract_host(url: str) -> str | None:
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        return parsed.hostname
    except Exception:
        return None
