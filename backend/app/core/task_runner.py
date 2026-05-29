import asyncio
import logging
import uuid
from typing import Any, Optional

from app.core.events.event_buffer import BufferedEvent, EventBatchSender
from app.core.queue import QueueBackend
from app.core.sandbox_bridge import (
    SandboxBridge,
    SandboxBridgeRegistry,
    SandboxBridgeStatus,
    WsOutMessage,
)
from app.core.runtime.adapter import HarnessAdapter, HarnessInput

logger = logging.getLogger(__name__)


class TaskRunner:
    """Per-sandbox task execution loop.

    Pops tasks from the sandbox queue, dispatches them via HarnessAdapter,
    streams events to subscribers, and updates task/session state in the DB.
    """

    def __init__(
        self,
        sandbox_bridge: SandboxBridge,
        queue: QueueBackend,
        adapter: HarnessAdapter,
        bridge_registry: SandboxBridgeRegistry,
        event_buffer: EventBatchSender,
        provider=None,
    ):
        self._bridge = sandbox_bridge
        self._queue = queue
        self._adapter = adapter
        self._registry = bridge_registry
        self._event_buffer = event_buffer
        self._provider = provider
        self._running = True
        self._cancel = asyncio.Event()
        self._consecutive_failures = 0

    async def run(self) -> None:
        from app.core.settings import conductor_config

        sandbox_id = self._bridge.sandbox_db_id
        logger.info("TaskRunner started for sandbox %s", sandbox_id)

        while self._running:
            task_id = await self._queue.pop_for_sandbox(sandbox_id, self._cancel)
            if task_id is None:
                if self._cancel.is_set():
                    break
                continue

            await self._execute_task(task_id)

            from app.core.lifespan import get_runtime_config
            rc = get_runtime_config()
            threshold = rc.sandbox_failure_threshold if rc else conductor_config.sandbox_failure_threshold
            if self._consecutive_failures >= threshold:
                logger.warning(
                    "Sandbox %s hit failure threshold (%d), ejecting",
                    sandbox_id,
                    self._consecutive_failures,
                )
                await self._cleanup_sandbox(sandbox_id)
                break

        logger.info("TaskRunner stopped for sandbox %s", sandbox_id)

    async def _execute_task(self, task_id: uuid.UUID) -> None:
        from app.core.database import AsyncSessionLocal
        from app.core.settings import conductor_config
        from app.models.task import ConductorTaskStatus as TaskStatus
        from app.models.session import SessionStatus
        from app.services.task_service import ConductorTaskService as TaskService
        from app.services.session_service import SessionService
        from app.services.agent_service import ConductorAgentService as AgentService
        from app.services.sandbox_service import SandboxService

        sandbox_id = self._bridge.sandbox_db_id
        self._bridge.status = SandboxBridgeStatus.BUSY
        self._bridge.current_task_id = task_id
        harness = None

        await self._bridge.broadcast_to_task(
            task_id, WsOutMessage(type="status", payload={"status": "running"})
        )

        try:
            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                agent_svc = AgentService(db)
                session_svc = SessionService(db)
                sandbox_svc = SandboxService(db)

                task = await task_svc.get_task(task_id)
                if not task:
                    logger.error("Task %s not found", task_id)
                    return

                agent = await agent_svc.get_agent(task.agent_id)
                if not agent:
                    await task_svc.update_task_error(
                        task_id, "Agent not found", TaskStatus.FAILED
                    )
                    return

                await task_svc.update_task_status(task_id, TaskStatus.RUNNING)

                if task.chat_session_id:
                    await session_svc.update_session_status(
                        task.chat_session_id, SessionStatus.RUNNING.value
                    )

                await sandbox_svc.touch(sandbox_id, task_id)

            from app.core.harness_input_builder import (
                build_harness_input,
                extract_tool_name_sets,
            )

            harness_input = await build_harness_input(
                task, agent, task.chat_session_id,
                self._bridge.external_id, self._bridge.sandbox_db_id,
            )
            harness = await self._adapter.start(harness_input)

            custom_tool_names, mcp_server_names = extract_tool_name_sets(agent)

            task_timeout = task.timeout_sec or conductor_config.task_default_timeout
            result = await self._run_with_pausable_deadline(
                task_id,
                task.chat_session_id,
                harness,
                custom_tool_names,
                mcp_server_names,
                task_timeout,
            )

            final_status = (
                TaskStatus.COMPLETED if not result.get("error") else TaskStatus.FAILED
            )
            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                session_svc = SessionService(db)
                sandbox_svc = SandboxService(db)

                error_msg = result.get("error")
                if error_msg:
                    await task_svc.update_task_error(
                        task_id, error_msg, final_status,
                    )
                else:
                    await task_svc.update_task_status(
                        task_id, final_status,
                    )
                await task_svc.update_task_output(task_id, result.get("output", ""))
                task_usage = result.get("usage")
                if task_usage:
                    await task_svc.update_task_usage(task_id, task_usage)

                if task.chat_session_id:
                    harness_session_id = result.get("session_id")
                    work_dir = result.get("work_dir")
                    await session_svc.update_session_sandbox(
                        task.chat_session_id,
                        sandbox_id,
                        harness_session_id=harness_session_id,
                        work_dir=work_dir,
                    )

                    task_usage = result.get("usage")
                    if task_usage:
                        if "model" not in task_usage and agent.model:
                            model_id = (
                                agent.model.get("id")
                                if isinstance(agent.model, dict)
                                else str(agent.model)
                            )
                            if model_id:
                                task_usage["model"] = model_id
                        await session_svc.accumulate_usage(
                            task.chat_session_id, task_usage
                        )

                    stop_reason = (
                        {"type": "end_turn"}
                        if not result.get("error")
                        else {
                            "type": "retries_exhausted",
                            "error": result.get("error"),
                        }
                    )
                    await session_svc.update_session_status(
                        task.chat_session_id,
                        SessionStatus.IDLE.value,
                        stop_reason=stop_reason,
                    )

                await sandbox_svc.update_status_cas(sandbox_id, "running", "idle")

            # HA: update coordinator state
            from app.core.lifespan import get_redis_coordinator

            coordinator = get_redis_coordinator()
            if coordinator:
                await coordinator.remove_task_sandbox(task_id)
                await coordinator.refresh_sandbox_owner(sandbox_id)

            # Track success: reset consecutive failure counter
            if final_status == TaskStatus.COMPLETED:
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1

            complete_msg = WsOutMessage(type="complete", payload=result)
            await self._bridge.broadcast_to_task(task_id, complete_msg)
            if coordinator:
                import json as _json
                await coordinator.publish_event(
                    task_id,
                    _json.dumps({"type": "complete", **result}),
                )

        except asyncio.CancelledError:
            logger.info("Task %s cancelled", task_id)
            self._consecutive_failures += 1
            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                await task_svc.update_task_error(
                    task_id, "Cancelled", TaskStatus.ABORTED
                )
        except TimeoutError:
            logger.warning(
                "Task %s exceeded server-side deadline, cancelling", task_id
            )
            self._consecutive_failures += 1
            if harness:
                try:
                    await self._adapter.cancel(harness)
                except Exception:
                    pass
            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                await task_svc.update_task_error(
                    task_id,
                    "Task timed out (server-side deadline)",
                    TaskStatus.TIMEOUT,
                )
            await self._bridge.broadcast_to_task(
                task_id,
                WsOutMessage(
                    type="complete",
                    payload={"error": "Task timed out (server-side deadline)"},
                ),
            )
        except Exception as e:
            logger.error("Task %s execution failed: %s", task_id, e)
            self._consecutive_failures += 1

            from app.core.task_controller import TaskController
            from app.core.retry import compute_retry_delay

            retryable = await TaskController.failover_or_fail_task(
                task_id, str(e)
            )
            if retryable:
                async with AsyncSessionLocal() as db:
                    task_svc = TaskService(db)
                    task = await task_svc.get_task(task_id)
                    retry_count = task.retry_count if task else 1
                delay = compute_retry_delay(retry_count, task_id)
                asyncio.create_task(
                    self._delayed_requeue(task_id, delay),
                    name=f"retry-{task_id}",
                )

            await self._bridge.broadcast_to_task(
                task_id,
                WsOutMessage(type="complete", payload={"error": str(e)}),
            )

            # Disconnect cleanup: probe container on unexpected failure
            if self._provider:
                await self._probe_and_cleanup(sandbox_id)
        finally:
            self._bridge.current_task_id = None
            self._bridge.status = SandboxBridgeStatus.IDLE
            self._bridge._requires_action_pending = False
            self._bridge.remove_task_subscribers(task_id)

    async def _cleanup_sandbox(self, sandbox_id: uuid.UUID) -> None:
        from app.core.database import AsyncSessionLocal
        from app.services.sandbox_service import SandboxService
        from app.core.task_controller import TaskController
        from app.core.retry import compute_retry_delay
        from app.core.lifespan import (
            get_memory_subscribers,
            get_redis_coordinator,
        )

        mem_subs = get_memory_subscribers()
        if mem_subs and self._bridge.current_task_id:
            from app.services.task_service import ConductorTaskService as TaskService

            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                task = await task_svc.get_task(self._bridge.current_task_id)
                if task and task.chat_session_id:
                    await mem_subs.unregister_session(task.chat_session_id)

        async with AsyncSessionLocal() as db:
            svc = SandboxService(db)
            if not await svc.update_status_cas(sandbox_id, "running", "stopped"):
                await svc.update_status_cas(sandbox_id, "idle", "stopped")

        await self._registry.remove(sandbox_id)

        # Drain sandbox queue and failover each task with retry backoff
        drained_ids = await self._queue.drain_sandbox(sandbox_id)
        for tid in drained_ids:
            retryable = await TaskController.failover_or_fail_task(
                tid, f"Sandbox {sandbox_id} ejected"
            )
            if retryable:
                async with AsyncSessionLocal() as db:
                    from app.services.task_service import ConductorTaskService as TaskService
                    task_svc = TaskService(db)
                    task = await task_svc.get_task(tid)
                    retry_count = task.retry_count if task else 1
                delay = compute_retry_delay(retry_count, tid)
                asyncio.create_task(
                    self._delayed_requeue(tid, delay),
                    name=f"retry-{tid}",
                )

        coordinator = get_redis_coordinator()
        if coordinator:
            await coordinator.remove_sandbox_owner(sandbox_id)
            await coordinator.remove_sandbox_queue(sandbox_id)

        logger.info("Sandbox %s cleaned up, %d tasks failovered", sandbox_id, len(drained_ids))

    async def _delayed_requeue(self, task_id: uuid.UUID, delay: float) -> None:
        await asyncio.sleep(delay)
        await self._queue.push_to_global(task_id)
        logger.info("Task %s re-enqueued after %.1fs retry delay", task_id, delay)

    async def _probe_and_cleanup(self, sandbox_id: uuid.UUID) -> None:
        self._bridge.status = SandboxBridgeStatus.DISCONNECTED
        external_id = self._bridge.external_id

        await asyncio.sleep(3)

        try:
            status = await self._provider.status(external_id)
        except Exception:
            status = "unknown"

        if status not in ("running", "created"):
            logger.warning(
                "Sandbox %s container dead after disconnect, cleaning up",
                sandbox_id,
            )
            await self._cleanup_sandbox(sandbox_id)
            self._running = False
            return

        await asyncio.sleep(2)

        try:
            status = await self._provider.status(external_id)
        except Exception:
            status = "unknown"

        if status not in ("running", "created"):
            logger.warning(
                "Sandbox %s container died during grace, cleaning up",
                sandbox_id,
            )
            await self._cleanup_sandbox(sandbox_id)
            self._running = False
            return

        # Container is still alive — start grace period as background task
        asyncio.create_task(
            self._grace_period_cleanup(sandbox_id, external_id),
            name=f"grace-cleanup-{sandbox_id}",
        )

    async def _grace_period_cleanup(
        self, sandbox_id: uuid.UUID, external_id: str
    ) -> None:
        grace_seconds = 120
        check_interval = 15

        elapsed = 0
        while elapsed < grace_seconds:
            await asyncio.sleep(check_interval)
            elapsed += check_interval

            if self._bridge.status == SandboxBridgeStatus.BUSY:
                logger.info(
                    "Sandbox %s reconnected during grace period", sandbox_id
                )
                return

            try:
                status = await self._provider.status(external_id)
            except Exception:
                status = "unknown"

            if status not in ("running", "created"):
                break

        if self._bridge.status != SandboxBridgeStatus.BUSY:
            logger.warning(
                "Sandbox %s grace period expired, cleaning up", sandbox_id
            )
            await self._cleanup_sandbox(sandbox_id)
            self._running = False

    async def _handle_memory_sync(
        self, session_id: Optional[uuid.UUID], payload: dict
    ) -> None:
        if not session_id:
            return

        mount_name = payload.get("store_mount_name", "")
        rel_path = payload.get("relative_path", "")
        content = payload.get("content", "")
        operation = payload.get("operation", "upsert")

        try:
            from app.core.database import AsyncSessionLocal
            from app.services.session_service import SessionService
            from app.services.conductor_memory_service import MemoryService

            async with AsyncSessionLocal() as db:
                session_svc = SessionService(db)
                mounts = await session_svc.list_session_memory_stores(session_id)

                for sms in mounts:
                    if sms.mount_name != mount_name:
                        continue
                    if sms.access == "read_only":
                        logger.warning(
                            "Ignoring write to read_only memory store mount=%s",
                            mount_name,
                        )
                        return

                    mem_svc = MemoryService(db)
                    if operation == "delete":
                        existing = await mem_svc.get_memory_by_path(
                            sms.store_id, rel_path
                        )
                        if existing:
                            await mem_svc.delete_memory(
                                sms.store_id, existing.id, session_id
                            )
                    else:
                        await mem_svc.upsert_memory_from_agent(
                            sms.store_id, rel_path, content, session_id
                        )
                    return
        except Exception as e:
            logger.warning("Memory sync failed: %s", e)

    async def _build_harness_input(
        self, task, agent, session_id: Optional[uuid.UUID]
    ) -> HarnessInput:
        from app.core.database import AsyncSessionLocal
        from app.services.secret_service import SecretService
        from app.services.vault_service import VaultService
        from app.services.session_service import SessionService
        from app.services.conductor_memory_service import MemoryService

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

        async with AsyncSessionLocal() as db:
            # 1. Resolve secrets from agent.secret_ref
            if getattr(agent, "secret_ref", None):
                secret_svc = SecretService(db)
                secret = await secret_svc.get_secret_by_name(agent.secret_ref)
                if secret and secret.data:
                    secrets = {k: str(v) for k, v in secret.data.items()}
                    env.update(secrets)

            # 2. Resolve vault credentials for MCP servers
            if session_id:
                session_svc = SessionService(db)
                session = await session_svc.get_session(session_id)
                vault_ids = (
                    session.vault_ids if session and hasattr(session, "vault_ids") else []
                )
                if vault_ids and mcp_configs:
                    vault_svc = VaultService(db)
                    mcp_configs = await vault_svc.resolve_mcp_credentials(
                        vault_ids, mcp_configs
                    )

            # 3. Extract custom tools from agent.tools
            for tool in agent.tools or []:
                if isinstance(tool, dict) and tool.get("type") == "custom":
                    custom_tools.append(
                        {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "input_schema": tool.get("input_schema", {}),
                        }
                    )

            # 4. Resolve memory stores
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

        # Register memory store subscribers
        if memory_mounts and session_id:
            from app.core.lifespan import get_memory_subscribers
            from app.core.memory_sync import MemorySessionEntry

            subs = get_memory_subscribers()
            if subs:
                for mm in memory_mounts:
                    await subs.register(
                        uuid.UUID(mm["store_id"]),
                        MemorySessionEntry(
                            session_id=session_id,
                            sandbox_db_id=self._bridge.sandbox_db_id,
                            mount_name=mm["mount_name"],
                        ),
                    )

        # Build skill archives from agent skills/agents/commands
        from app.core.runtime.adapter import SkillArchive
        import base64

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
            work_dir=self._bridge.external_id,
            session_id=str(session_id) if session_id else None,
            permission_mode=getattr(agent, "permission_mode", None)
            or "bypassPermissions",
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

    @staticmethod
    def _extract_tool_name_sets(agent) -> tuple[set[str], set[str]]:
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

    async def _run_with_pausable_deadline(
        self,
        task_id: uuid.UUID,
        session_id: Optional[uuid.UUID],
        harness,
        custom_tool_names: set[str],
        mcp_server_names: set[str],
        timeout: float,
    ) -> dict[str, Any]:
        """Run harness loop with a deadline that pauses during HITL waits."""
        import time

        deadline_remaining = timeout
        deadline_paused = False
        loop_result: dict[str, Any] = {}
        loop_done = asyncio.Event()
        loop_error: Optional[BaseException] = None

        original_enter = None
        original_exit = None

        async def _run_inner():
            nonlocal loop_result, loop_error
            try:
                loop_result = await self._run_harness_loop(
                    task_id, session_id, harness,
                    custom_tool_names, mcp_server_names,
                )
            except BaseException as e:
                loop_error = e
            finally:
                loop_done.set()

        inner_task = asyncio.create_task(_run_inner(), name=f"harness-{task_id}")

        wall_start = time.monotonic()
        hitl_pause_start: Optional[float] = None
        total_hitl_seconds = 0.0

        # Poll loop: check deadline accounting for HITL pauses
        while not loop_done.is_set():
            try:
                await asyncio.wait_for(
                    asyncio.shield(loop_done.wait()), timeout=1.0
                )
            except asyncio.TimeoutError:
                pass

            if loop_done.is_set():
                break

            if self._bridge._requires_action_pending:
                if hitl_pause_start is None:
                    hitl_pause_start = time.monotonic()
            else:
                if hitl_pause_start is not None:
                    total_hitl_seconds += time.monotonic() - hitl_pause_start
                    hitl_pause_start = None

            elapsed = time.monotonic() - wall_start
            active_elapsed = elapsed - total_hitl_seconds
            if hitl_pause_start is not None:
                active_elapsed -= (time.monotonic() - hitl_pause_start)

            if active_elapsed >= timeout:
                inner_task.cancel()
                try:
                    await inner_task
                except (asyncio.CancelledError, Exception):
                    pass
                raise TimeoutError(
                    f"Task timed out after {timeout}s active time "
                    f"({total_hitl_seconds:.0f}s HITL paused)"
                )

        if loop_error is not None:
            raise loop_error
        return loop_result

    async def _run_harness_loop(
        self,
        task_id: uuid.UUID,
        session_id: Optional[uuid.UUID],
        harness,
        custom_tool_names: set[str],
        mcp_server_names: set[str],
    ) -> dict[str, Any]:
        from app.core.events.event_mapping import (
            map_harness_event,
            is_control_request,
        )

        seq = 0
        requires_action_pending = False
        last_tool_use_event_id: Optional[str] = None
        buffered_events: list[dict] = []

        async def _process_mapped_event(
            mapped_type: str, mapped_payload: dict
        ) -> Optional[str]:
            nonlocal seq, last_tool_use_event_id
            seq += 1

            ws_msg = WsOutMessage(
                type="event",
                payload={"type": mapped_type, **mapped_payload},
            )
            await self._bridge.broadcast_to_task(task_id, ws_msg)

            # Cross-instance: publish task event to Redis
            from app.core.lifespan import get_redis_coordinator
            coordinator = get_redis_coordinator()
            if coordinator:
                import json as _json
                await coordinator.publish_event(
                    task_id,
                    _json.dumps({"type": ws_msg.type, **ws_msg.payload}),
                )

            event_id = None
            if session_id:
                await self._event_buffer.send(
                    BufferedEvent(
                        session_id=session_id,
                        event_type=mapped_type,
                        payload=mapped_payload,
                        seq=seq,
                    )
                )
                event_id = str(seq)

                from app.core.lifespan import get_session_broadcaster

                broadcaster = get_session_broadcaster()
                if broadcaster:
                    broadcast_data = {"type": mapped_type, "seq": seq}
                    if isinstance(mapped_payload, dict):
                        broadcast_data.update(mapped_payload)
                    await broadcaster.send(session_id, broadcast_data)

            if mapped_type in (
                "agent.tool_use",
                "agent.custom_tool_use",
                "agent.mcp_tool_use",
            ):
                last_tool_use_event_id = event_id

            return event_id

        async def _enter_requires_action(event_ids: list[str]) -> None:
            nonlocal requires_action_pending
            requires_action_pending = True
            self._bridge._requires_action_pending = True

            if session_id:
                from app.core.database import AsyncSessionLocal
                from app.services.session_service import SessionService
                from app.models.session import SessionStatus

                stop_reason = {
                    "type": "requires_action",
                    "event_ids": event_ids,
                }
                async with AsyncSessionLocal() as db:
                    svc = SessionService(db)
                    await svc.update_session_status(
                        session_id,
                        SessionStatus.IDLE.value,
                        stop_reason=stop_reason,
                    )

                from app.core.lifespan import get_session_broadcaster

                broadcaster = get_session_broadcaster()
                if broadcaster:
                    await broadcaster.send(
                        session_id,
                        {
                            "type": "session.status_idle",
                            "stop_reason": stop_reason,
                            "seq": seq + 1,
                        },
                    )

        async def _exit_requires_action() -> None:
            nonlocal requires_action_pending
            requires_action_pending = False
            self._bridge._requires_action_pending = False
            self._bridge.confirmation_event.clear()

            if session_id:
                from app.core.database import AsyncSessionLocal
                from app.services.session_service import SessionService
                from app.models.session import SessionStatus

                async with AsyncSessionLocal() as db:
                    svc = SessionService(db)
                    await svc.update_session_status(
                        session_id, SessionStatus.RUNNING.value
                    )

                from app.core.lifespan import get_session_broadcaster

                broadcaster = get_session_broadcaster()
                if broadcaster:
                    await broadcaster.send(
                        session_id,
                        {
                            "type": "session.status_running",
                            "seq": seq + 1,
                        },
                    )

            for raw_event in buffered_events:
                mapped_list = map_harness_event(
                    raw_event, custom_tool_names, mcp_server_names
                )
                for mtype, mpayload in mapped_list:
                    await _process_mapped_event(mtype, mpayload)
            buffered_events.clear()

        async def _stream_events():
            nonlocal requires_action_pending
            async for event in harness.events():
                raw = event.payload

                if requires_action_pending:
                    buffered_events.append(raw)
                    continue

                mapped_list = map_harness_event(
                    raw, custom_tool_names, mcp_server_names
                )
                for mapped_type, mapped_payload in mapped_list:
                    if mapped_type == "memory_sync":
                        asyncio.create_task(
                            self._handle_memory_sync(
                                session_id, mapped_payload
                            )
                        )
                        continue

                    if mapped_type in (
                        "agent.tool_use",
                        "agent.mcp_tool_use",
                    ) and is_control_request(mapped_payload):
                        call_id = mapped_payload.get("_call_id") or mapped_payload.get("id", "")
                        ref_id = last_tool_use_event_id or str(seq + 1)
                        self._bridge.pending_control_request_ids[ref_id] = (
                            call_id
                        )
                        await _enter_requires_action([ref_id])
                        continue

                    event_id = await _process_mapped_event(
                        mapped_type, mapped_payload
                    )

                    if mapped_type == "agent.custom_tool_use" and event_id:
                        await _enter_requires_action([event_id])

        async def _handle_control_inputs():
            while not harness._done.is_set():
                try:
                    content = await asyncio.wait_for(
                        self._bridge._control_queue.get(), timeout=1.0
                    )
                    if requires_action_pending:
                        await _exit_requires_action()
                    await self._adapter.send_input(harness, content)
                except asyncio.TimeoutError:
                    if (
                        requires_action_pending
                        and self._bridge.confirmation_event.is_set()
                    ):
                        await _exit_requires_action()
                except Exception as e:
                    logger.warning("Control input error: %s", e)

        async def _watch_cancel():
            await self._bridge._cancel_event.wait()
            await self._adapter.cancel(harness)

        stream_task = asyncio.create_task(_stream_events())
        control_task = asyncio.create_task(_handle_control_inputs())
        cancel_task = asyncio.create_task(_watch_cancel())

        try:
            result = await harness.wait()
            stream_task.cancel()
            control_task.cancel()
            cancel_task.cancel()
            for t in (stream_task, control_task, cancel_task):
                try:
                    await t
                except asyncio.CancelledError:
                    pass

            await self._event_buffer.flush()

            return {
                "output": result.output,
                "error": result.error,
                "usage": result.usage,
                "session_id": result.session_id,
                "work_dir": result.work_dir,
                "status": result.status.value if result.status else "completed",
                "duration_ms": result.duration_ms,
            }
        except Exception as e:
            for t in (stream_task, control_task, cancel_task):
                t.cancel()
            raise

    def stop(self) -> None:
        self._running = False
        self._cancel.set()
