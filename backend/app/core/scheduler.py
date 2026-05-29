"""
Background scheduler loops for task auto-dispatch and stale execution reaping.

Registered in app lifespan (main.py). Each function is an infinite async loop
following the same pattern as _container_reaper.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from loguru import logger

from app.core.database import AsyncSessionLocal

_DISPATCH_INTERVAL = 30
_REAPER_INTERVAL = 30

_STALE_THRESHOLDS: list[tuple[tuple[str, ...], timedelta]] = [
    (
        ("pending", "dispatched"),
        timedelta(minutes=5),
    ),
    (
        ("running",),
        timedelta(minutes=10),
    ),
    (
        ("approval_wait",),
        timedelta(minutes=60),
    ),
]


async def task_dispatcher_loop() -> None:
    """Every 30s, find BACKLOG tasks with agent assignees and dispatch them."""
    while True:
        await asyncio.sleep(_DISPATCH_INTERVAL)
        try:
            async with AsyncSessionLocal() as db:
                from sqlalchemy import select

                from app.models.task import Task

                # Find backlog tasks with assigned agents
                tasks = (
                    (
                        await db.execute(
                            select(Task).where(
                                Task.status == "backlog",
                                Task.agent_id.isnot(None),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

                count = 0
                for task in tasks:
                    try:
                        from app.services.dispatch_service import DispatchService

                        dispatch = DispatchService(db)
                        await dispatch.dispatch_task(task.id, task.creator_id)
                        count += 1
                    except Exception as task_exc:
                        logger.warning(f"Auto-dispatch failed for task {task.id}: {task_exc}")

                if count:
                    logger.info(f"Scheduler: auto-dispatched {count} tasks")
        except Exception as exc:
            logger.warning(f"Task dispatcher error: {exc}")


async def execution_reaper_loop() -> None:
    """Every 30s, find stale executions and mark them failed."""
    while True:
        await asyncio.sleep(_REAPER_INTERVAL)
        try:
            reaped = await _reap_stale_executions()
            if reaped:
                logger.info(f"Scheduler: reaped {reaped} stale executions")
        except Exception as exc:
            logger.warning(f"Execution reaper error: {exc}")
        try:
            from app.core.observation.otel.provider import get_broadcast_processor, get_persistence_processor

            get_persistence_processor().reap_stale()
            get_broadcast_processor().reap_stale()
        except Exception as exc:
            logger.debug(f"Observation bucket reap failed: {exc}")
        try:
            await _reap_orphan_traces()
        except Exception as exc:
            logger.debug(f"Orphan trace reap failed: {exc}")


async def recover_stale_on_startup() -> None:
    """One-shot: catch executions that went stale during downtime."""
    try:
        reaped = await _reap_stale_executions()
        if reaped:
            logger.info(f"Startup recovery: reaped {reaped} stale executions")
        else:
            logger.info("Startup recovery: no stale executions found")
    except Exception as exc:
        logger.warning(f"Startup stale execution recovery failed: {exc}")


async def _reap_stale_executions() -> int:
    """Shared logic for reaper loop and startup recovery.

    Delegates all business logic to ExecutionService.reap_stale_executions
    so the scheduler only decides *when* to run and *what thresholds* to use.
    """
    async with AsyncSessionLocal() as db:
        from app.services.execution_service import ExecutionService

        svc = ExecutionService(db)
        return await svc.reap_stale_executions(_STALE_THRESHOLDS)


async def _reap_orphan_traces() -> None:
    """Mark Trace rows as 'error' if their execution is already terminal but the Trace is still 'running'."""
    import sqlalchemy as sa
    from sqlalchemy.engine import CursorResult

    from app.core.observation.model import Trace
    from app.models.execution import Execution
    from app.utils.datetime import utc_now

    terminal = ("succeeded", "failed", "cancelled")
    async with AsyncSessionLocal() as db:
        result: CursorResult = await db.execute(  # type: ignore[assignment]
            sa.update(Trace)
            .where(
                Trace.status == "running",
                Trace.execution_id == Execution.id,
                Execution.status.in_(terminal),
            )
            .values(status="error", end_time=utc_now())
        )
        rows_fixed = result.rowcount
        if rows_fixed:
            await db.commit()
            logger.info(f"Scheduler: fixed {rows_fixed} orphan Trace rows")


# ---------------------------------------------------------------------------
# Conductor TaskScheduler: semaphore-driven queue scheduling
# ---------------------------------------------------------------------------

import uuid


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

            await self._scheduling_semaphore.acquire()
            task_id = await self._queue.pop_from_global()
            logger.info("Scheduler picked up task {}", task_id)
            t = asyncio.create_task(self._schedule_task(task_id))
            self._inflight_tasks.add(t)
            t.add_done_callback(self._inflight_tasks.discard)

    async def _schedule_task(self, task_id: uuid.UUID) -> None:
        try:
            from app.core.database import AsyncSessionLocal
            from app.services.task_service import ConductorTaskService as TaskService
            from app.services.agent_service import ConductorAgentService as AgentService
            from app.services.session_service import SessionService
            from app.core.lifespan import (
                get_bridge_registry,
                get_sandbox_resolver,
            )

            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                agent_svc = AgentService(db)
                session_svc = SessionService(db)

                claimed = await task_svc.claim_task_for_scheduling(task_id)
                if not claimed:
                    logger.warning("Task {} not pending (already being scheduled or terminal), skipping", task_id)
                    return

                task = await task_svc.get_task(task_id)
                if not task:
                    logger.error("Task {} not found after claim", task_id)
                    return

                agent = await agent_svc.get_agent(task.agent_id)
                if not agent:
                    from app.models.task import ConductorTaskStatus
                    await task_svc.update_task_error(
                        task_id, "Agent not found", ConductorTaskStatus.FAILED
                    )
                    return

                if getattr(agent, "archived_at", None) is not None:
                    logger.warning("Agent {} is archived, cancelling task {}", task.agent_id, task_id)
                    from app.models.task import ConductorTaskStatus
                    await task_svc.update_task_status(task_id, ConductorTaskStatus.CANCELLED)
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
                    )
                    session_id = session.id
                    task.chat_session_id = session_id
                    await db.commit()

                agent_env = dict(agent.env or {})

                if getattr(agent, "secret_ref", None):
                    from app.services.secret_service import SecretService
                    secret_svc = SecretService(db)
                    secret = await secret_svc.get_secret_by_name(agent.secret_ref)
                    if secret and secret.data:
                        for k, v in secret.data.items():
                            agent_env.setdefault(k, str(v))
                        if "ANTHROPIC_AUTH_TOKEN" in agent_env and "ANTHROPIC_API_KEY" not in agent_env:
                            agent_env["ANTHROPIC_API_KEY"] = agent_env["ANTHROPIC_AUTH_TOKEN"]

                env_ref = None
                if session_id and task.chat_session_id:
                    session = await session_svc.get_session(session_id)
                    if session:
                        env_ref = session.environment_ref
                if not env_ref:
                    env_ref = agent.environment_ref

                from app.core.sandbox_resolver import image_for_provider
                from app.core.settings import conductor_config as _cfg
                default_image = image_for_provider(
                    getattr(agent, "engine_kind", None) or "", _cfg.sandbox_image
                )

                resolved_image = default_image
                networking = None
                if env_ref:
                    from app.services.conductor_environment_service import EnvironmentService
                    env_svc = EnvironmentService(db)
                    environment = await env_svc.get_environment_by_ref(env_ref)
                    if environment:
                        resolved_image = environment.image_tag or default_image
                        config = environment.config or {}
                        net_cfg = config.get("networking")
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

            resolver = get_sandbox_resolver()
            if resolver:
                resolved = await resolver.resolve(
                    session_id, agent_env, image=resolved_image, networking=networking,
                    engine_kind=getattr(agent, "engine_kind", None),
                )
                sandbox_id = resolved["sandbox_id"]
                external_id = resolved["external_id"]
            else:
                from app.services.sandbox_manager import SandboxService
                from app.core.settings import conductor_config
                async with AsyncSessionLocal() as db:
                    sandbox_svc = SandboxService(db)
                    sandbox = await sandbox_svc.find_by_session(session_id)
                    if not sandbox:
                        sandbox = await sandbox_svc.claim_from_pool(conductor_config.sandbox_image, session_id)
                    if not sandbox:
                        sandbox = await sandbox_svc.create_sandbox(
                            image=conductor_config.sandbox_image,
                            provider=conductor_config.sandbox_provider,
                            chat_session_id=session_id,
                        )
                    sandbox_id = sandbox.id
                    external_id = sandbox.external_id

            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                await task_svc.update_task_sandbox(task_id, sandbox_id)

            bridge_registry = get_bridge_registry()

            if bridge_registry:
                await bridge_registry.get_or_register(sandbox_id, external_id)

            from app.core.lifespan import get_redis_coordinator

            coordinator = get_redis_coordinator()
            if coordinator:
                await coordinator.register_sandbox_owner(sandbox_id)
                await coordinator.set_task_sandbox(task_id, sandbox_id)

            await self._queue.push_to_sandbox(sandbox_id, task_id)
            logger.info("Task {} pushed to sandbox queue {}", task_id, sandbox_id)

        except Exception as e:
            logger.error("Failed to schedule task {}: {}", task_id, e)
            try:
                from app.core.task_controller import TaskController
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
