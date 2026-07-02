"""Runner-side joysafeter task scheduler."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# JoySafeter TaskScheduler: semaphore-driven queue scheduling
# ---------------------------------------------------------------------------
import asyncio
import uuid

from loguru import logger


class TaskScheduler:
    def __init__(self, queue, max_concurrent: int = 10, max_scheduling: int = 50):
        self._queue = queue
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._scheduling_semaphore = asyncio.Semaphore(max_scheduling)
        self._running = True
        self._inflight_tasks: set[asyncio.Task] = set()

    @property
    def execution_semaphore(self) -> asyncio.Semaphore:
        return self._semaphore

    async def run(self) -> None:
        logger.info(
            "TaskScheduler started (max_concurrent={}, max_scheduling={})",
            self._semaphore._value,
            self._scheduling_semaphore._value,
        )
        while self._running:
            while self._semaphore._value == 0:
                await asyncio.sleep(0.5)

            available_slots = self._scheduling_semaphore._value
            if available_slots <= 0:
                await asyncio.sleep(0.2)
                continue

            task_ids = await self._claim_pending_batch(available_slots)
            if not task_ids:
                # Redis/global queue is now a wakeup signal; DB pending remains
                # the source of truth and is scanned again after this returns.
                try:
                    await asyncio.wait_for(self._queue.pop_from_global(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    logger.warning("Scheduler wakeup wait failed: {}", e)
                    await asyncio.sleep(1.0)
                continue

            for task_id in task_ids:
                await self._scheduling_semaphore.acquire()
                logger.info("Scheduler claimed task {} from DB", task_id)
                t = asyncio.create_task(
                    self._schedule_task(task_id, already_claimed=True)
                )
                self._inflight_tasks.add(t)
                t.add_done_callback(self._inflight_tasks.discard)

    async def _claim_pending_batch(self, limit: int) -> list[uuid.UUID]:
        try:
            from app.joysafeter_orchestrator.services import TaskService
            from app.joysafeter_shared.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                return await TaskService(db).claim_pending_tasks_for_scheduling(limit)
        except Exception as e:
            logger.warning("Scheduler DB batch claim failed: {}", e)
            return []

    async def _schedule_task(self, task_id: uuid.UUID, already_claimed: bool = False) -> None:
        try:
            from app.joysafeter_orchestrator.lifespan import (
                get_bridge_registry,
                get_sandbox_resolver,
            )
            from app.joysafeter_orchestrator.services import AgentService, SessionService, TaskService
            from app.joysafeter_shared.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                agent_svc = AgentService(db)
                session_svc = SessionService(db)

                if not already_claimed:
                    claimed = await task_svc.claim_task_for_scheduling(task_id)
                    if not claimed:
                        logger.warning("Task {} not pending (already being scheduled or terminal), skipping", task_id)
                        return

                task = await task_svc.get_task(task_id)
                if not task:
                    logger.error("Task {} not found after claim", task_id)
                    return

                agent = await agent_svc.get_agent(
                    task.agent_id, project_id=getattr(task, "project_id", None)
                )
                if not agent:
                    from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus
                    await task_svc.update_task_error(
                        task_id, "Agent not found", JoySafeterTaskStatus.FAILED
                    )
                    return

                if getattr(agent, "archived_at", None) is not None:
                    logger.warning("Agent {} is archived, cancelling task {}", task.agent_id, task_id)
                    from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus
                    await task_svc.update_task_status(task_id, JoySafeterTaskStatus.CANCELLED)
                    return

                session_id = task.chat_session_id
                if not session_id:
                    session = await session_svc.create_session(
                        agent_id=agent.id,
                        title="Auto-created",
                        agent_version=agent.version,
                        agent_snapshot={
                            "type": "agent",
                            "id": str(agent.id),
                            "version": agent.version,
                            "name": agent.name,
                            "description": agent.description,
                            "model": agent.model,
                            "system": agent.system_prompt,
                            "tools": agent.tools,
                            "skills": agent.skills,
                            "mcp_servers": agent.mcp_configs,
                            "multiagent": agent.multiagent,
                        },
                        project_id=getattr(task, "project_id", None),
                    )
                    session_id = session.id
                    task.chat_session_id = session_id
                    await db.commit()

                env_ref = None
                if session_id and task.chat_session_id:
                    session = await session_svc.get_session(session_id)
                    if session:
                        env_ref = session.environment_ref
                if not env_ref:
                    env_ref = agent.environment_ref

                from app.joysafeter_orchestrator.kernel.sandbox_resolver import image_for_provider
                from app.joysafeter_shared.config.settings import joysafeter_config as _cfg
                default_image = image_for_provider(
                    getattr(agent, "engine_kind", None) or "", _cfg.sandbox_image
                )

                resolved_image = default_image
                networking = None
                environment_config = {}
                if env_ref:
                    from app.joysafeter_orchestrator.services import EnvironmentService
                    env_svc = EnvironmentService(db)
                    environment = await env_svc.get_environment_by_ref(env_ref, project_id=getattr(agent, "project_id", None))
                    if environment:
                        resolved_image = environment.image_tag or default_image
                        config = environment.config or {}
                        environment_config = config if isinstance(config, dict) else {}
                        net_cfg = environment_config.get("networking")
                        if net_cfg and isinstance(net_cfg, dict):
                            networking = net_cfg
                            if net_cfg.get("type") == "limited":
                                allowed = list(net_cfg.get("allowed_hosts", []))
                                for mcp in (agent.mcp_configs or []):
                                    if isinstance(mcp, dict) and mcp.get("url"):
                                        host = _extract_host(mcp["url"])
                                        if host and host not in allowed:
                                            allowed.append(host)
                                networking = {**net_cfg, "allowed_hosts": allowed}

                from app.joysafeter_orchestrator.services import SecretService
                secret_svc = SecretService(db)
                project_id = (
                    str(agent.project_id)
                    if getattr(agent, "project_id", None) is not None
                    else None
                )
                agent_env: dict[str, str] = {}
                env_vars = environment_config.get("env_vars")
                if isinstance(env_vars, dict):
                    agent_env.update({str(k): str(v) for k, v in env_vars.items()})
                secret_refs = environment_config.get("secret_refs")
                if isinstance(secret_refs, list):
                    agent_env = await secret_svc.merge_secret_refs_into_env(
                        agent_env, secret_refs, project_id=project_id
                    )
                if getattr(agent, "secret_ref", None):
                    agent_env = await secret_svc.merge_secret_refs_into_env(
                        agent_env, [agent.secret_ref], project_id=project_id, override=True
                    )
                agent_env.update({str(k): str(v) for k, v in (agent.env or {}).items()})
                secret_svc.apply_provider_aliases(agent_env)

            resolver = get_sandbox_resolver()
            if resolver:
                resolved = await resolver.resolve(
                    session_id, agent_env, image=resolved_image, networking=networking,
                    engine_kind=getattr(agent, "engine_kind", None),
                    project_id=getattr(task, "project_id", None),
                )
                sandbox_id = resolved["sandbox_id"]
                external_id = resolved["external_id"]
            else:
                from app.joysafeter_orchestrator.services import SandboxService
                from app.joysafeter_shared.config.settings import joysafeter_config
                async with AsyncSessionLocal() as db:
                    sandbox_svc = SandboxService(db)
                    sandbox = await sandbox_svc.find_by_session(session_id)
                    fallback_image = resolved_image or joysafeter_config.sandbox_image
                    requires_persistent_workspace = (
                        joysafeter_config.sandbox_workspace_root is not None
                    )
                    if not sandbox and not requires_persistent_workspace:
                        sandbox = await sandbox_svc.claim_from_pool(fallback_image, session_id)
                    if not sandbox:
                        sandbox = await sandbox_svc.create_sandbox(
                            image=fallback_image,
                            provider=joysafeter_config.sandbox_provider,
                            chat_session_id=session_id,
                            project_id=getattr(task, "project_id", None),
                        )
                    sandbox_id = sandbox.id
                    external_id = sandbox.external_id

            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus

                current_task = await task_svc.get_task(task_id)
                current_status = (
                    JoySafeterTaskStatus.from_str_lossy(current_task.status)
                    if current_task is not None
                    else JoySafeterTaskStatus.FAILED
                )
                if current_task is None or current_status.is_terminal():
                    logger.info(
                        "Task {} became terminal before sandbox enqueue, skipping",
                        task_id,
                    )
                    return
                attached = await task_svc.attach_sandbox_if_scheduling(task_id, sandbox_id)
                if not attached:
                    logger.info(
                        "Task {} left scheduling before sandbox enqueue, skipping",
                        task_id,
                    )
                    return

            bridge_registry = get_bridge_registry()

            if bridge_registry:
                await bridge_registry.get_or_register(sandbox_id, external_id)

            from app.joysafeter_orchestrator.lifespan import get_redis_coordinator

            coordinator = get_redis_coordinator()
            if coordinator:
                await coordinator.register_sandbox_owner(sandbox_id)
                await coordinator.set_task_sandbox(task_id, sandbox_id)

            await self._queue.push_to_sandbox(sandbox_id, task_id)
            logger.info("Task {} pushed to sandbox queue {}", task_id, sandbox_id)

        except Exception as e:
            logger.error("Failed to schedule task {}: {}", task_id, e, exc_info=True)
            try:
                from app.joysafeter_orchestrator.kernel.task_controller import TaskController
                retry_count = await TaskController.failover_or_fail_task(
                    task_id, f"Schedule failed: {e}"
                )
                if retry_count is not None:
                    delay = TaskController.compute_retry_delay(retry_count, task_id)
                    await asyncio.sleep(delay)
                    await self._queue.push_to_global(task_id)
                    logger.info("Task {} re-enqueued after scheduling failure (retry {})", task_id, retry_count)
            except Exception as inner:
                logger.error("Failed to failover task {}: {}", task_id, inner)
        finally:
            self._scheduling_semaphore.release()

    async def push_to_global(self, task_id: uuid.UUID) -> None:
        await self._queue.push_to_global(task_id)

    def stop(self) -> None:
        self._running = False


def _extract_host(url: str) -> str | None:
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        return parsed.hostname
    except Exception:
        return None
