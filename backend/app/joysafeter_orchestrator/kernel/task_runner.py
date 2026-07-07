import asyncio
import logging
import random
import uuid
from typing import Any, Optional

from app.joysafeter_orchestrator.kernel.queue import QueueBackend
from app.joysafeter_orchestrator.kernel.sandbox_bridge import (
    SandboxBridge,
    SandboxBridgeRegistry,
    SandboxBridgeStatus,
    WsOutMessage,
)
from app.joysafeter_orchestrator.runtime.adapter import HarnessAdapter, HarnessInput
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_worker.events.batch_writer import BufferedEvent, EventBatchSender

logger = logging.getLogger(__name__)

_TASK_SCOPED_STATUS_EVENTS = {
    "session.status_running": "running",
    "session.status_idle": "idle",
}


def _log_task_runner_boundary_failure(
    *,
    code: str,
    message: str,
    operation: str,
    error: Exception | None = None,
    data: dict[str, object] | None = None,
    retryable: bool = True,
    user_action: str | None = "retry",
) -> None:
    logger.warning(
        message,
        extra={
            "error": async_boundary_error_payload(
                code=code,
                message=message,
                boundary="task_runner",
                operation=operation,
                data=data,
                detail=error.__class__.__name__ if error is not None else None,
                retryable=retryable,
                user_action=user_action,
            )
        },
        exc_info=error is not None,
    )


async def persist_task_scoped_session_status_event(
    *,
    session_id: uuid.UUID,
    task_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
):
    status = _TASK_SCOPED_STATUS_EVENTS.get(event_type)
    if status is None:
        return None

    from app.joysafeter_orchestrator.services import SessionService
    from app.joysafeter_shared.database import AsyncSessionLocal

    stop_reason = payload.get("stop_reason") if isinstance(payload, dict) else None
    status_payload = dict(payload or {})
    status_payload["task_id"] = str(task_id)
    async with AsyncSessionLocal() as db:
        svc = SessionService(db)
        accepted = await svc.update_session_status_for_task_event(
            session_id,
            status,
            task_id,
            stop_reason=stop_reason,
        )
        if not accepted:
            return None
        return await svc.send_event(session_id, event_type, status_payload)


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
        from app.joysafeter_shared.config.settings import joysafeter_config

        sandbox_id = self._bridge.sandbox_db_id
        logger.info("TaskRunner started for sandbox %s", sandbox_id)
        idle_wait_secs = 1.0

        while self._running:
            claimed = await self._claim_next_sandbox_task_from_db(sandbox_id)
            if claimed is None:
                await self._queue.wait_for_sandbox_wakeup(
                    sandbox_id,
                    self._cancel,
                    timeout_secs=idle_wait_secs + random.uniform(0, 0.25),
                )
                claimed = await self._claim_next_sandbox_task_from_db(sandbox_id)
            if claimed is None:
                if self._cancel.is_set():
                    break
                idle_wait_secs = min(idle_wait_secs * 1.5, 5.0)
                continue

            idle_wait_secs = 1.0
            task_id, owner_epoch = claimed
            await self._execute_task(task_id, owner_epoch)

            from app.joysafeter_orchestrator.lifespan import get_runtime_config

            rc = get_runtime_config()
            threshold = rc.sandbox_failure_threshold if rc else joysafeter_config.sandbox_failure_threshold
            if self._consecutive_failures >= threshold:
                _log_task_runner_boundary_failure(
                    code="TASK_RUNNER_SANDBOX_FAILURE_THRESHOLD_EXCEEDED",
                    message="Sandbox hit failure threshold; ejecting",
                    operation="eject_failed_sandbox",
                    data={
                        "sandbox_id": str(sandbox_id),
                        "consecutive_failures": self._consecutive_failures,
                        "threshold": threshold,
                    },
                    retryable=True,
                    user_action="retry",
                )
                await self._cleanup_sandbox(sandbox_id)
                break

        logger.info("TaskRunner stopped for sandbox %s", sandbox_id)

    async def _claim_next_sandbox_task_from_db(self, sandbox_id: uuid.UUID) -> Optional[tuple[uuid.UUID, int]]:
        from app.joysafeter_orchestrator.services import TaskService
        from app.joysafeter_shared.database import AsyncSessionLocal

        try:
            async with AsyncSessionLocal() as db:
                return await TaskService(db).claim_next_sandbox_task_for_running(sandbox_id)
        except Exception as e:
            _log_task_runner_boundary_failure(
                code="TASK_RUNNER_DB_CLAIM_FAILED",
                message="Failed to claim next scheduling task for sandbox",
                operation="claim_next_sandbox_task",
                error=e,
                data={"sandbox_id": str(sandbox_id)},
            )
            return None

    async def _execute_task(self, task_id: uuid.UUID, owner_epoch: int) -> None:
        from app.joysafeter_domain.models.joysafeter_session import SessionStatus
        from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus
        from app.joysafeter_orchestrator.services import AgentService, SessionService, TaskService
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from app.joysafeter_shared.config.settings import joysafeter_config
        from app.joysafeter_shared.database import AsyncSessionLocal

        sandbox_id = self._bridge.sandbox_db_id
        self._bridge.status = SandboxBridgeStatus.BUSY
        self._bridge.current_task_id = task_id
        harness = None

        await self._bridge.broadcast_to_task(task_id, WsOutMessage(type="status", payload={"status": "running"}))

        try:
            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                agent_svc = AgentService(db)
                session_svc = SessionService(db)
                sandbox_svc = SandboxService(db)

                task = await task_svc.get_task(task_id)
                if not task:
                    _log_task_runner_boundary_failure(
                        code="TASK_RUNNER_TASK_NOT_FOUND",
                        message="Task not found during runner execution",
                        operation="load_task_for_execution",
                        data={"task_id": str(task_id), "sandbox_id": str(sandbox_id)},
                        retryable=False,
                        user_action="refresh",
                    )
                    return

                agent = await agent_svc.get_agent(task.agent_id, project_id=getattr(task, "project_id", None))
                if not agent:
                    await task_svc.update_task_error(
                        task_id,
                        "Agent not found",
                        TaskStatus.FAILED,
                        expected_epoch=owner_epoch,
                    )
                    return

                if task.status != TaskStatus.RUNNING.value:
                    logger.info(
                        "Task %s was not running after sandbox claim (status=%s), skipping execution",
                        task_id,
                        task.status,
                    )
                    return

                if task.chat_session_id:
                    await session_svc.update_session_status_for_task_event(
                        task.chat_session_id,
                        SessionStatus.RUNNING.value,
                        task_id,
                    )

                await sandbox_svc.touch(sandbox_id, task_id)

            from app.joysafeter_orchestrator.kernel.harness_input_builder import (
                build_harness_input,
                extract_tool_name_sets,
            )

            harness_input = await build_harness_input(
                task,
                agent,
                task.chat_session_id,
                self._bridge.external_id,
                self._bridge.sandbox_db_id,
            )
            harness = await self._adapter.start(harness_input)

            custom_tool_names, mcp_server_names = extract_tool_name_sets(agent)

            task_timeout = task.timeout_sec or joysafeter_config.task_default_timeout
            result = await self._run_with_pausable_deadline(
                task_id,
                task.chat_session_id,
                harness,
                custom_tool_names,
                mcp_server_names,
                task_timeout,
            )

            final_status = TaskStatus.COMPLETED if not result.get("error") else TaskStatus.FAILED
            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                session_svc = SessionService(db)
                sandbox_svc = SandboxService(db)

                error_msg = result.get("error")
                if not await task_svc.update_task_output(task_id, result.get("output", ""), expected_epoch=owner_epoch):
                    _log_task_runner_boundary_failure(
                        code="TASK_RUNNER_RESULT_OUTPUT_CAS_CONFLICT",
                        message="CAS conflict writing output; ignoring adapter result",
                        operation="persist_adapter_result_output",
                        data={"task_id": str(task_id), "owner_epoch": owner_epoch},
                        retryable=False,
                        user_action=None,
                    )
                    return
                task_usage = result.get("usage")
                if task_usage:
                    if not await task_svc.update_task_usage(task_id, task_usage, expected_epoch=owner_epoch):
                        _log_task_runner_boundary_failure(
                            code="TASK_RUNNER_RESULT_USAGE_CAS_CONFLICT",
                            message="CAS conflict writing usage; ignoring adapter result",
                            operation="persist_adapter_result_usage",
                            data={"task_id": str(task_id), "owner_epoch": owner_epoch},
                            retryable=False,
                            user_action=None,
                        )
                        return
                if error_msg:
                    task_status_updated = await task_svc.update_task_error(
                        task_id,
                        error_msg,
                        final_status,
                        expected_epoch=owner_epoch,
                    )
                else:
                    task_status_updated = await task_svc.update_task_status(
                        task_id,
                        final_status,
                        expected_epoch=owner_epoch,
                    )
                if not task_status_updated:
                    _log_task_runner_boundary_failure(
                        code="TASK_RUNNER_RESULT_FINALIZE_CAS_CONFLICT",
                        message="CAS conflict finalizing task; ignoring adapter result",
                        operation="finalize_adapter_result",
                        data={"task_id": str(task_id), "owner_epoch": owner_epoch, "status": final_status.value},
                        retryable=False,
                        user_action=None,
                    )
                    return

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
                            model_id = agent.model.get("id") if isinstance(agent.model, dict) else str(agent.model)
                            if model_id:
                                task_usage["model"] = model_id
                        await session_svc.accumulate_usage(task.chat_session_id, task_usage)

                    stop_reason: dict[str, Any] = (
                        {"type": "end_turn"}
                        if not result.get("error")
                        else {
                            "type": "retries_exhausted",
                            "error": result.get("error"),
                        }
                    )
                    await session_svc.update_session_status_for_task_event(
                        task.chat_session_id,
                        SessionStatus.IDLE.value,
                        task_id,
                        stop_reason=stop_reason,
                    )

                await sandbox_svc.update_status_cas(sandbox_id, "running", "idle")

            # HA: update coordinator state
            from app.joysafeter_orchestrator.lifespan import get_redis_coordinator

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
                await task_svc.update_task_error(task_id, "Cancelled", TaskStatus.ABORTED, expected_epoch=owner_epoch)
        except TimeoutError:
            _log_task_runner_boundary_failure(
                code="TASK_RUNNER_TASK_DEADLINE_EXCEEDED",
                message="Task exceeded server-side deadline; cancelling",
                operation="cancel_deadline_exceeded_task",
                data={"task_id": str(task_id), "owner_epoch": owner_epoch},
                retryable=True,
                user_action="retry",
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
                    expected_epoch=owner_epoch,
                )
            await self._bridge.broadcast_to_task(
                task_id,
                WsOutMessage(
                    type="complete",
                    payload={"error": "Task timed out (server-side deadline)"},
                ),
            )
        except Exception as e:
            _log_task_runner_boundary_failure(
                code="TASK_RUNNER_EXECUTION_FAILED",
                message="Task execution failed in runner",
                operation="execute_task",
                error=e,
                data={"task_id": str(task_id), "sandbox_id": str(sandbox_id)},
            )
            self._consecutive_failures += 1

            from app.joysafeter_orchestrator.kernel.task_controller import TaskController
            from app.joysafeter_shared.retry import compute_retry_delay

            retryable = await TaskController.failover_or_fail_task(task_id, str(e), expected_epoch=owner_epoch)
            if retryable is not None:
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
        from app.joysafeter_orchestrator.kernel.task_controller import TaskController
        from app.joysafeter_orchestrator.lifespan import (
            get_memory_subscribers,
            get_redis_coordinator,
        )
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from app.joysafeter_shared.database import AsyncSessionLocal
        from app.joysafeter_shared.retry import compute_retry_delay

        mem_subs = get_memory_subscribers()
        if mem_subs and self._bridge.current_task_id:
            from app.joysafeter_orchestrator.services import TaskService

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

        await self._queue.drain_sandbox(sandbox_id)

        async with AsyncSessionLocal() as db:
            from app.joysafeter_orchestrator.services import TaskService

            task_svc = TaskService(db)
            recoverable_ids = await task_svc.list_recoverable_tasks_by_sandbox(sandbox_id)

        for tid in recoverable_ids:
            retryable = await TaskController.failover_or_fail_task(tid, f"Sandbox {sandbox_id} ejected")
            if retryable is not None:
                async with AsyncSessionLocal() as db:
                    from app.joysafeter_orchestrator.services import TaskService

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

        logger.info("Sandbox %s cleaned up, %d tasks failovered", sandbox_id, len(recoverable_ids))

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
        except Exception as e:
            _log_task_runner_boundary_failure(
                code="TASK_RUNNER_PROVIDER_STATUS_FAILED",
                message="Provider status probe failed after task failure",
                operation="probe_sandbox_status",
                error=e,
                data={"sandbox_id": str(sandbox_id), "external_id": external_id, "probe": "initial"},
            )
            status = "unknown"

        if status not in ("running", "created"):
            _log_task_runner_boundary_failure(
                code="TASK_RUNNER_SANDBOX_DEAD_AFTER_DISCONNECT",
                message="Sandbox container dead after disconnect; cleaning up",
                operation="cleanup_dead_sandbox_after_disconnect",
                data={"sandbox_id": str(sandbox_id), "external_id": external_id, "status": status},
                retryable=True,
                user_action="retry",
            )
            await self._cleanup_sandbox(sandbox_id)
            self._running = False
            return

        await asyncio.sleep(2)

        try:
            status = await self._provider.status(external_id)
        except Exception as e:
            _log_task_runner_boundary_failure(
                code="TASK_RUNNER_PROVIDER_STATUS_FAILED",
                message="Provider status probe failed during grace check",
                operation="probe_sandbox_status",
                error=e,
                data={"sandbox_id": str(sandbox_id), "external_id": external_id, "probe": "grace"},
            )
            status = "unknown"

        if status not in ("running", "created"):
            _log_task_runner_boundary_failure(
                code="TASK_RUNNER_SANDBOX_DIED_DURING_GRACE",
                message="Sandbox container died during grace; cleaning up",
                operation="cleanup_dead_sandbox_during_grace",
                data={"sandbox_id": str(sandbox_id), "external_id": external_id, "status": status},
                retryable=True,
                user_action="retry",
            )
            await self._cleanup_sandbox(sandbox_id)
            self._running = False
            return

        # Container is still alive — start grace period as background task
        asyncio.create_task(
            self._grace_period_cleanup(sandbox_id, external_id),
            name=f"grace-cleanup-{sandbox_id}",
        )

    async def _grace_period_cleanup(self, sandbox_id: uuid.UUID, external_id: str) -> None:
        grace_seconds = 120
        check_interval = 15

        elapsed = 0
        while elapsed < grace_seconds:
            await asyncio.sleep(check_interval)
            elapsed += check_interval

            if self._bridge.status == SandboxBridgeStatus.BUSY:
                logger.info("Sandbox %s reconnected during grace period", sandbox_id)
                return

            try:
                status = await self._provider.status(external_id)
            except Exception as e:
                _log_task_runner_boundary_failure(
                    code="TASK_RUNNER_PROVIDER_STATUS_FAILED",
                    message="Provider status probe failed during grace period",
                    operation="probe_sandbox_status",
                    error=e,
                    data={"sandbox_id": str(sandbox_id), "external_id": external_id, "probe": "periodic"},
                )
                status = "unknown"

            if status not in ("running", "created"):
                break

        if self._bridge.status != SandboxBridgeStatus.BUSY:
            _log_task_runner_boundary_failure(
                code="TASK_RUNNER_GRACE_PERIOD_EXPIRED",
                message="Sandbox grace period expired, cleaning up",
                operation="grace_period_cleanup",
                data={"sandbox_id": str(sandbox_id), "external_id": external_id},
                retryable=False,
                user_action=None,
            )
            await self._cleanup_sandbox(sandbox_id)
            self._running = False

    async def _handle_memory_sync(self, session_id: Optional[uuid.UUID], payload: dict) -> None:
        if not session_id:
            return

        mount_name = payload.get("store_mount_name", "")
        rel_path = payload.get("relative_path", "")
        content = payload.get("content", "")
        operation = payload.get("operation", "upsert")

        try:
            from app.joysafeter_orchestrator.services import MemoryService, SessionService
            from app.joysafeter_shared.database import AsyncSessionLocal

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
                        existing = await mem_svc.get_memory_by_path(sms.store_id, rel_path)
                        if existing:
                            await mem_svc.delete_memory(sms.store_id, existing.id, session_id)
                    else:
                        await mem_svc.upsert_memory_from_agent(sms.store_id, rel_path, content, session_id)
                    return
        except Exception as e:
            _log_task_runner_boundary_failure(
                code="TASK_RUNNER_MEMORY_SYNC_FAILED",
                message="Memory sync failed",
                operation="handle_memory_sync",
                error=e,
                data={
                    "session_id": str(session_id),
                    "mount_name": str(mount_name),
                    "relative_path": str(rel_path),
                    "operation_type": str(operation),
                },
            )

    async def _build_harness_input(self, task, agent, session_id: Optional[uuid.UUID]) -> HarnessInput:
        from app.joysafeter_orchestrator.kernel.harness_input_builder import build_harness_input

        return await build_harness_input(
            task,
            agent,
            session_id,
            self._bridge.external_id,
            self._bridge.sandbox_db_id,
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

        loop_result: dict[str, Any] = {}
        loop_done = asyncio.Event()
        loop_error: Optional[BaseException] = None

        async def _run_inner():
            nonlocal loop_result, loop_error
            try:
                loop_result = await self._run_harness_loop(
                    task_id,
                    session_id,
                    harness,
                    custom_tool_names,
                    mcp_server_names,
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
                await asyncio.wait_for(asyncio.shield(loop_done.wait()), timeout=1.0)
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
                active_elapsed -= time.monotonic() - hitl_pause_start

            if active_elapsed >= timeout:
                inner_task.cancel()
                try:
                    await inner_task
                except (asyncio.CancelledError, Exception):
                    pass
                raise TimeoutError(
                    f"Task timed out after {timeout}s active time ({total_hitl_seconds:.0f}s HITL paused)"
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
        from app.joysafeter_orchestrator.events.event_mapping import (
            is_control_request,
            map_harness_event,
        )

        seq = 0
        requires_action_pending = False
        last_tool_use_event_id: Optional[str] = None
        buffered_events: list[dict] = []

        async def _process_mapped_event(mapped_type: str, mapped_payload: dict) -> Optional[str]:
            nonlocal seq, last_tool_use_event_id
            seq += 1

            ws_msg = WsOutMessage(
                type="event",
                payload={"type": mapped_type, **mapped_payload},
            )
            await self._bridge.broadcast_to_task(task_id, ws_msg)

            # Cross-instance: publish task event to Redis
            from app.joysafeter_orchestrator.lifespan import get_redis_coordinator

            coordinator = get_redis_coordinator()
            if coordinator:
                import json as _json

                await coordinator.publish_event(
                    task_id,
                    _json.dumps({"type": ws_msg.type, **ws_msg.payload}),
                )

            event_id = None
            if session_id:
                if mapped_type in ("session.status_running", "session.status_idle"):
                    event = await persist_task_scoped_session_status_event(
                        session_id=session_id,
                        task_id=task_id,
                        event_type=mapped_type,
                        payload=mapped_payload,
                    )
                    if event is not None:
                        event_id = f"evt_{event.id}"
                        from app.joysafeter_orchestrator.lifespan import get_session_broadcaster

                        broadcaster = get_session_broadcaster()
                        if broadcaster:
                            broadcast_data = {
                                "id": event_id,
                                "type": event.event_type,
                                "seq": event.seq,
                            }
                            if isinstance(event.payload, dict):
                                broadcast_data.update(event.payload)
                            await broadcaster.send(session_id, broadcast_data)
                    return event_id

                await self._event_buffer.send(
                    BufferedEvent(
                        session_id=session_id,
                        event_type=mapped_type,
                        payload=mapped_payload,
                        seq=seq,
                    )
                )
                event_id = str(seq)

                from app.joysafeter_orchestrator.lifespan import get_session_broadcaster

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
                from app.joysafeter_domain.models.joysafeter_session import SessionStatus
                from app.joysafeter_orchestrator.services import SessionService
                from app.joysafeter_shared.database import AsyncSessionLocal

                stop_reason = {
                    "type": "requires_action",
                    "event_ids": event_ids,
                }
                async with AsyncSessionLocal() as db:
                    svc = SessionService(db)
                    await svc.update_session_status_for_task_event(
                        session_id,
                        SessionStatus.IDLE.value,
                        task_id,
                        stop_reason=stop_reason,
                    )

                from app.joysafeter_orchestrator.lifespan import get_session_broadcaster

                broadcaster = get_session_broadcaster()
                if broadcaster:
                    await broadcaster.send(
                        session_id,
                        {
                            "type": "session.status_idle",
                            "task_id": str(task_id),
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
                from app.joysafeter_domain.models.joysafeter_session import SessionStatus
                from app.joysafeter_orchestrator.services import SessionService
                from app.joysafeter_shared.database import AsyncSessionLocal

                async with AsyncSessionLocal() as db:
                    svc = SessionService(db)
                    running_accepted = await svc.update_session_status_for_task_event(
                        session_id,
                        SessionStatus.RUNNING.value,
                        task_id,
                    )
                    if running_accepted:
                        await svc.send_event(
                            session_id,
                            "session.status_running",
                            {"task_id": str(task_id)},
                        )

                from app.joysafeter_orchestrator.lifespan import get_session_broadcaster

                broadcaster = get_session_broadcaster()
                if broadcaster and running_accepted:
                    await broadcaster.send(
                        session_id,
                        {
                            "type": "session.status_running",
                            "task_id": str(task_id),
                            "seq": seq + 1,
                        },
                    )

            for raw_event in buffered_events:
                mapped_list = map_harness_event(raw_event, custom_tool_names, mcp_server_names)
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

                mapped_list = map_harness_event(raw, custom_tool_names, mcp_server_names)
                for mapped_type, mapped_payload in mapped_list:
                    if mapped_type == "memory_sync":
                        asyncio.create_task(self._handle_memory_sync(session_id, mapped_payload))
                        continue

                    if mapped_type in (
                        "agent.tool_use",
                        "agent.mcp_tool_use",
                    ) and is_control_request(mapped_payload):
                        call_id = mapped_payload.get("_call_id") or mapped_payload.get("id", "")
                        ref_id = last_tool_use_event_id or str(seq + 1)
                        self._bridge.pending_control_request_ids[ref_id] = call_id
                        await _enter_requires_action([ref_id])
                        continue

                    event_id = await _process_mapped_event(mapped_type, mapped_payload)

                    if mapped_type == "agent.custom_tool_use" and event_id:
                        await _enter_requires_action([event_id])

        async def _handle_control_inputs():
            while not harness._done.is_set():
                try:
                    content = await asyncio.wait_for(self._bridge._control_queue.get(), timeout=1.0)
                    if requires_action_pending:
                        await _exit_requires_action()
                    await self._adapter.send_input(harness, content)
                except asyncio.TimeoutError:
                    if requires_action_pending and self._bridge.confirmation_event.is_set():
                        await _exit_requires_action()
                except Exception as e:
                    _log_task_runner_boundary_failure(
                        code="TASK_RUNNER_CONTROL_INPUT_FAILED",
                        message="Control input dispatch failed",
                        operation="send_control_input",
                        error=e,
                        data={"task_id": str(task_id), "session_id": str(session_id or "")},
                    )

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
        except Exception:
            for t in (stream_task, control_task, cancel_task):
                t.cancel()
            raise

    def stop(self) -> None:
        self._running = False
        self._cancel.set()
