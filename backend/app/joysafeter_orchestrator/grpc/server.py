"""gRPC AgentBridge server — bidirectional streaming between runner and orchestrator.

Ported 1:1 from joysafeter-kernel/src/grpc.rs Session handler.
Architecture: DB-driven pull. The Session handler claims work from
joysafeter_tasks; Redis/local sandbox queues are wakeup signals only.
"""

import asyncio
import json
import logging
import random
import uuid
from typing import TYPE_CHECKING, Any, Optional

import grpc
from grpc import aio as grpc_aio
from uuid_utils import uuid7

from app.joysafeter_orchestrator.events.envelope import JoySafeterEventEnvelope
from app.joysafeter_orchestrator.grpc.proto import joysafeter_pb2, joysafeter_pb2_grpc
from app.joysafeter_orchestrator.kernel.queue import QueueBackend
from app.joysafeter_orchestrator.kernel.sandbox_bridge import (
    SandboxBridge,
    SandboxBridgeRegistry,
    SandboxBridgeStatus,
    WsOutMessage,
)
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.common.stream_errors import async_error_payload
from app.joysafeter_worker.events.batch_writer import BufferedEvent, EventBatchSender

if TYPE_CHECKING:
    from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus

logger = logging.getLogger(__name__)

_HEARTBEAT_TIMEOUT_DEFAULT = 120
TASK_DEFAULT_TIMEOUT_SEC = 7200


async def _best_effort_redis(label: str, operation) -> None:
    try:
        await operation
    except Exception as exc:
        logger.warning(
            "Redis coordinator %s failed",
            label,
            extra={
                "error": async_boundary_error_payload(
                    code="GRPC_REDIS_COORDINATOR_FAILED",
                    message="Redis coordinator operation failed",
                    boundary="grpc_agent_bridge",
                    operation=label,
                    detail=exc.__class__.__name__,
                )
            },
            exc_info=True,
        )


async def _best_effort_publish_event(coordinator, task_id: uuid.UUID, payload: str) -> None:
    if coordinator:
        await _best_effort_redis("publish_event", coordinator.publish_event(task_id, payload))


def _log_grpc_boundary_failure(
    *,
    code: str,
    message: str,
    operation: str,
    error: Exception | None = None,
    data: dict[str, object] | None = None,
    retryable: bool = True,
    user_action: str | None = "retry",
    level: str = "warning",
) -> None:
    log_method = logger.error if level == "error" else logger.warning
    log_method(
        message,
        extra={
            "error": async_boundary_error_payload(
                code=code,
                message=message,
                boundary="grpc_agent_bridge",
                operation=operation,
                data=data,
                retryable=retryable,
                user_action=user_action,
                detail=error.__class__.__name__ if error is not None else None,
            )
        },
        exc_info=error is not None,
    )


def _task_error_stop_reason(
    *,
    code: str,
    message: str,
    task_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    sandbox_id: uuid.UUID | None = None,
    retryable: bool = False,
    user_action: str | None = "refresh",
    detail: str | None = None,
) -> dict[str, Any]:
    data: dict[str, object] = {}
    if task_id is not None:
        data["task_id"] = str(task_id)
    if session_id is not None:
        data["session_id"] = str(session_id)
    if sandbox_id is not None:
        data["sandbox_id"] = str(sandbox_id)
    return async_error_payload(
        code=code,
        message=message,
        data=data or None,
        source="runtime",
        retryable=retryable,
        user_action=user_action,
        detail=detail,
    )


def _get_heartbeat_timeout() -> int:
    from app.joysafeter_orchestrator.lifespan import get_runtime_config

    rc = get_runtime_config()
    if rc:
        return int(rc.heartbeat_timeout_sec)
    return _HEARTBEAT_TIMEOUT_DEFAULT


class AgentBridgeServicer(joysafeter_pb2_grpc.AgentBridgeServicer):
    def __init__(
        self,
        bridge_registry: SandboxBridgeRegistry,
        event_buffer: EventBatchSender,
        queue: QueueBackend,
        vault_provider: Optional[Any] = None,
        execution_semaphore: Optional[asyncio.Semaphore] = None,
        event_bus: Optional[Any] = None,
    ):
        self._bridge_registry = bridge_registry
        self._event_buffer = event_buffer
        self._queue = queue
        self._vault_provider = vault_provider
        self._execution_semaphore = execution_semaphore or asyncio.Semaphore(1000)
        self._connection_semaphore = asyncio.Semaphore(2000)
        self._event_bus = event_bus

    async def Session(self, request_iterator, context):
        """Bidirectional streaming RPC — 1:1 port of agentd's grpc.rs Session handler.

        Architecture:
        - Receive RunnerReady
        - Send SetupSandbox
        - Enter outer loop: query DB for sandbox scheduling tasks, waiting on wakeups
        - Per task: send StartTask, enter inner loop reading events until Result+Idle
        - On disconnect: cleanup
        """
        # Connection-level rate limiting (atomic try-acquire, no TOCTOU race)
        if self._connection_semaphore.locked():
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Too many concurrent connections",
            )
            return
        try:
            self._connection_semaphore.acquire_nowait()
        except ValueError:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Too many concurrent connections",
            )
            return
        try:
            await self._session_impl(request_iterator, context)
        finally:
            self._connection_semaphore.release()

    async def _session_impl(self, request_iterator, context):
        await context.send_initial_metadata(())

        bridge: Optional[SandboxBridge] = None
        sandbox_id: Optional[uuid.UUID] = None
        stream_cancel = asyncio.Event()
        # Track session_id at the Session level for cleanup
        linked_session_id: Optional[uuid.UUID] = None
        failover_pending_tasks: list[tuple[uuid.UUID, int]] = []
        failure_ejected = False

        try:
            # --- Handshake: read RunnerReady ---
            first_msg = await context.read()
            if first_msg == grpc_aio.EOF:
                return

            payload_type = first_msg.WhichOneof("payload")
            if payload_type != "ready":
                logger.warning("First message must be RunnerReady, got %s", payload_type)
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    "First message must be RunnerReady",
                )
                return

            ready = first_msg.ready
            raw_id = ready.sandbox_id
            try:
                sandbox_id = uuid.UUID(raw_id)
            except ValueError:
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    f"Invalid sandbox_id: {raw_id}",
                )
                return

            logger.info(
                "Runner connected: sandbox=%s version=%s reconnect=%s",
                sandbox_id,
                ready.runner_version,
                ready.is_reconnect,
            )

            # Authenticate runner token
            import hmac

            from app.joysafeter_orchestrator.services import SandboxRecordService as _SbxSvc_auth
            from app.joysafeter_shared.database import AsyncSessionLocal as _ASL_auth

            runner_token = ready.runner_token if ready.HasField("runner_token") else ""
            async with _ASL_auth() as _db_auth:
                _svc_auth = _SbxSvc_auth(_db_auth)
                _sandbox_auth = await _svc_auth.get_sandbox(sandbox_id)
                if _sandbox_auth:
                    expected_token = (_sandbox_auth.config or {}).get("runner_token", "")
                    if expected_token and runner_token and not hmac.compare_digest(runner_token, expected_token):
                        _log_grpc_boundary_failure(
                            code="GRPC_RUNNER_TOKEN_MISMATCH",
                            message="Runner token mismatch; rejecting runner",
                            operation="authenticate_runner",
                            data={"sandbox_id": str(sandbox_id)},
                            retryable=False,
                            user_action="check_runner_configuration",
                        )
                        await context.abort(
                            grpc.StatusCode.UNAUTHENTICATED,
                            "Invalid runner token",
                        )
                        return
                    if expected_token and not runner_token:
                        _log_grpc_boundary_failure(
                            code="GRPC_RUNNER_TOKEN_MISSING",
                            message="Runner did not provide runner token; allowing legacy runner",
                            operation="authenticate_runner",
                            data={"sandbox_id": str(sandbox_id)},
                            retryable=False,
                            user_action="upgrade_runner",
                        )
                elif runner_token == "":
                    # Unknown sandbox with no token — reject
                    _log_grpc_boundary_failure(
                        code="GRPC_UNKNOWN_SANDBOX_NO_TOKEN",
                        message="Unknown sandbox connected without runner token",
                        operation="authenticate_runner",
                        data={"sandbox_id": str(sandbox_id)},
                        retryable=False,
                        user_action=None,
                    )
                    await context.abort(
                        grpc.StatusCode.NOT_FOUND,
                        "Unknown sandbox_id",
                    )
                    return

            # Register bridge (always create fresh, matching Rust sandbox_bridges.insert)
            bridge = await self._bridge_registry.register(sandbox_id, str(sandbox_id))

            bridge.runner_stream = context
            bridge.runner_connected.set()
            bridge.runner_capabilities = set(ready.capabilities) if ready.capabilities else set()
            if ready.available_providers:
                logger.info(
                    "Runner %s connected with providers: %s",
                    sandbox_id,
                    list(ready.available_providers),
                )

            # Register Redis owner (Rust: redis.register_sandbox_owner)
            from app.joysafeter_orchestrator.lifespan import get_redis_coordinator as _get_rc_init

            _coord_init = _get_rc_init()
            if _coord_init:
                await _best_effort_redis("register_sandbox_owner", _coord_init.register_sandbox_owner(sandbox_id))

            # DB status CAS: reject terminal sandboxes, skip CAS for pooled, otherwise CAS to idle
            from app.joysafeter_orchestrator.services import SandboxRecordService as _SbxSvc_init
            from app.joysafeter_shared.database import AsyncSessionLocal as _ASL_init

            async with _ASL_init() as _db_init:
                _svc_init = _SbxSvc_init(_db_init)
                _sandbox_rec = await _svc_init.get_sandbox(sandbox_id)
                if _sandbox_rec:
                    _current_status = _sandbox_rec.status
                    if _current_status in ("destroyed", "error"):
                        _log_grpc_boundary_failure(
                            code="GRPC_RUNNER_TERMINAL_SANDBOX_REJECTED",
                            message="Runner connected to terminal sandbox; rejecting",
                            operation="attach_runner",
                            data={"sandbox_id": str(sandbox_id), "status": _current_status},
                            retryable=False,
                            user_action="restart_sandbox",
                        )
                        await bridge.write_to_runner(
                            joysafeter_pb2.OrchestratorMessage(
                                shutdown=joysafeter_pb2.Shutdown(reason=f"sandbox terminal: {_current_status}")
                            )
                        )
                        await self._bridge_registry.remove(sandbox_id)
                        return
                    if _current_status in ("stopping", "stopped"):
                        _log_grpc_boundary_failure(
                            code="GRPC_RUNNER_STOPPING_SANDBOX_REJECTED",
                            message="Runner connected to sandbox being stopped; rejecting",
                            operation="attach_runner",
                            data={"sandbox_id": str(sandbox_id), "status": _current_status},
                            retryable=False,
                            user_action="restart_sandbox",
                        )
                        await bridge.write_to_runner(
                            joysafeter_pb2.OrchestratorMessage(
                                shutdown=joysafeter_pb2.Shutdown(reason=f"sandbox stopped: {_current_status}")
                            )
                        )
                        await self._bridge_registry.remove(sandbox_id)
                        return
                    if _current_status == "pooled":
                        pass  # skip CAS for pooled
                    else:
                        await _svc_init.update_status_cas(sandbox_id, _current_status, "idle")
                else:
                    await _svc_init.update_status(sandbox_id, "idle")

                await _svc_init.touch(sandbox_id)
                # Successful runner attach → clear any stale disconnect
                # marker left by an earlier crash, so the fallback sweeper
                # doesn't reap a sandbox that just reconnected.
                await _svc_init.mark_bridge_connected(sandbox_id)

            bridge.status = SandboxBridgeStatus.IDLE

            # --- Send SetupSandbox or resolve session (BEFORE active_task_id, matching Rust) ---
            if not bridge.setup_done:
                # Poll up to 50 times (100ms each) waiting for sandbox.chat_session_id
                _sandbox_linked = None
                async with _ASL_init() as _db_poll:
                    _svc_poll = _SbxSvc_init(_db_poll)
                    for _attempt in range(50):
                        _rec = await _svc_poll.get_sandbox(sandbox_id)
                        if _rec and _rec.chat_session_id:
                            _sandbox_linked = _rec
                            linked_session_id = _rec.chat_session_id
                            break
                        if _attempt < 49:
                            await asyncio.sleep(0.1)

                if _sandbox_linked is None:
                    _log_grpc_boundary_failure(
                        code="GRPC_SETUP_SANDBOX_LINK_TIMEOUT",
                        message="Timed out waiting for sandbox to link with session; SetupSandbox will be skipped",
                        operation="wait_for_sandbox_session_link",
                        data={"sandbox_id": str(sandbox_id), "attempts": 50},
                        retryable=True,
                        user_action="retry",
                    )
                else:
                    await self._send_setup(bridge, sandbox_id)
            else:
                logger.info("Runner reconnecting sandbox %s (setup already done), skipping setup", sandbox_id)
                # Resolve session from DB on reconnect
                async with _ASL_init() as _db_resolve:
                    _svc_resolve = _SbxSvc_init(_db_resolve)
                    _rec_resolve = await _svc_resolve.get_sandbox(sandbox_id)
                    if _rec_resolve:
                        linked_session_id = _rec_resolve.chat_session_id

            # Register memory subscribers for this session
            if linked_session_id:
                from app.joysafeter_orchestrator.kernel.memory_sync import MemorySessionEntry
                from app.joysafeter_orchestrator.lifespan import get_memory_subscribers

                mem_subs = get_memory_subscribers()
                if mem_subs:
                    from app.joysafeter_orchestrator.services import SessionService as _SessSvc

                    async with _ASL_init() as _db_mem:
                        _sess_svc = _SessSvc(_db_mem)
                        _mounts = await _sess_svc.list_session_memory_stores(linked_session_id)
                        for _sms in _mounts:
                            store_id = _sms.store_id
                            await mem_subs.register(
                                store_id,
                                MemorySessionEntry(
                                    session_id=linked_session_id,
                                    sandbox_db_id=sandbox_id,
                                    mount_name=_sms.mount_name,
                                ),
                            )

            # --- Handle reconnection with active_task_id (AFTER session resolution, matching Rust line 479) ---
            if ready.HasField("active_task_id") and ready.active_task_id:
                await self._handle_reconnect_active_task(
                    bridge,
                    sandbox_id,
                    ready.active_task_id,
                    context,
                    stream_cancel,
                    failover_pending_tasks,
                )
            elif ready.is_reconnect:
                # Runner reconnected without active_task_id — rescue orphaned running tasks
                await self._rescue_orphaned_tasks(sandbox_id)

            # --- Outer task-dispatch loop (matches agentd) ---
            # Blocks on pop_for_sandbox until a task arrives or stream disconnects.
            # Shield from gRPC cancellation — we handle stream EOF internally.
            failure_ejected = await asyncio.shield(
                self._multi_task_loop(
                    bridge,
                    sandbox_id,
                    context,
                    stream_cancel,
                    failover_pending_tasks,
                    linked_session_id,
                )
            )

        except grpc_aio.AioRpcError as e:
            _log_grpc_boundary_failure(
                code="GRPC_SESSION_RPC_ERROR",
                message="gRPC runner session ended with RPC error",
                operation="runner_session",
                error=e,
                data={"sandbox_id": str(sandbox_id), "grpc_code": str(e.code()), "grpc_details": str(e.details())},
            )
        except asyncio.CancelledError:
            _log_grpc_boundary_failure(
                code="GRPC_SESSION_CANCELLED",
                message="gRPC runner session cancelled",
                operation="runner_session",
                data={"sandbox_id": str(sandbox_id)},
                retryable=False,
                user_action=None,
            )
        except Exception as e:
            _log_grpc_boundary_failure(
                code="GRPC_SESSION_FAILED",
                message="gRPC runner session failed",
                operation="runner_session",
                error=e,
                data={"sandbox_id": str(sandbox_id)},
                level="error",
            )
        finally:
            stream_cancel.set()
            if bridge:
                bridge.runner_connected.clear()
                bridge.runner_stream = None
                bridge.status = SandboxBridgeStatus.DISCONNECTED
                logger.info("Runner disconnected: sandbox=%s", sandbox_id)
            if sandbox_id:
                # Stamp disconnected_at so the fallback sweeper can reap this
                # sandbox after the grace window if no reconnect arrives. Best
                # effort — a failure here just means the sweeper waits for
                # idle_timeout / hard_timeout instead.
                try:
                    from app.joysafeter_orchestrator.services import (
                        SandboxRecordService as SandboxService,
                    )
                    from app.joysafeter_shared.database import AsyncSessionLocal

                    async with AsyncSessionLocal() as _dc_db:
                        await SandboxService(_dc_db).mark_bridge_disconnected(sandbox_id)
                except Exception as _dc_err:
                    _log_grpc_boundary_failure(
                        code="GRPC_MARK_BRIDGE_DISCONNECTED_FAILED",
                        message="Failed to mark sandbox bridge disconnected",
                        operation="mark_bridge_disconnected",
                        error=_dc_err,
                        data={"sandbox_id": str(sandbox_id)},
                    )
                await self._cleanup_sandbox(
                    sandbox_id,
                    session_id=linked_session_id,
                    failover_pending_tasks=failover_pending_tasks,
                    is_error=failure_ejected,
                    external_id=bridge.external_id if bridge else None,
                )

    # --- Fix 1: Full reconnect with active_task_id ---

    async def _handle_reconnect_active_task(
        self,
        bridge: SandboxBridge,
        sandbox_id: uuid.UUID,
        active_task_id_str: str,
        context,
        stream_cancel: asyncio.Event,
        failover_pending_tasks: list,
    ) -> None:
        """Handle RunnerReady.active_task_id -- full reconnect loop matching Rust lines 479-712.

        Runs a complete inner event loop for the resumed task BEFORE returning
        to the caller (which then enters the multi-task loop).  Sets
        bridge.setup_done = True so that _send_setup is skipped on reconnect.
        """
        from app.joysafeter_domain.models.joysafeter_session import SessionStatus
        from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus
        from app.joysafeter_orchestrator.events.event_mapping import is_control_request, map_harness_event
        from app.joysafeter_orchestrator.kernel.harness_input_builder import extract_tool_name_sets
        from app.joysafeter_orchestrator.kernel.task_controller import TaskController
        from app.joysafeter_orchestrator.lifespan import get_redis_coordinator, get_session_broadcaster
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from app.joysafeter_orchestrator.services import SessionService, TaskService
        from app.joysafeter_shared.database import AsyncSessionLocal

        bridge.setup_done = True  # skip SetupSandbox on reconnect

        try:
            active_task_id = uuid.UUID(active_task_id_str)
        except ValueError:
            logger.warning(
                "Invalid active_task_id on reconnect: %s",
                active_task_id_str,
            )
            return

        # Check if task is already terminal
        async with AsyncSessionLocal() as db:
            task_svc = TaskService(db)
            task = await task_svc.get_task(active_task_id)
            if not task:
                logger.warning(
                    "Reconnect: active task %s not found, ignoring",
                    active_task_id,
                )
                return
            # Verify task belongs to this sandbox
            if task.sandbox_id and task.sandbox_id != sandbox_id:
                _log_grpc_boundary_failure(
                    code="GRPC_RECONNECT_TASK_SANDBOX_MISMATCH",
                    message="Reconnect task belongs to a different sandbox; rejecting",
                    operation="reconnect_active_task",
                    data={
                        "task_id": str(active_task_id),
                        "task_sandbox_id": str(task.sandbox_id),
                        "runner_sandbox_id": str(sandbox_id),
                    },
                    retryable=False,
                    user_action="retry",
                )
                return
            if TaskStatus.from_str_lossy(task.status).is_terminal():
                logger.info(
                    "Reconnect: active task %s already terminal (%s), ignoring",
                    active_task_id,
                    task.status,
                )
                return

        # Acquire execution semaphore
        await self._execution_semaphore.acquire()
        try:
            logger.info(
                "Resuming active task %s from reconnecting runner on sandbox %s",
                active_task_id,
                sandbox_id,
            )

            # Set Redis task->sandbox mapping
            coordinator = get_redis_coordinator()
            if coordinator:
                await _best_effort_redis("set_task_sandbox", coordinator.set_task_sandbox(active_task_id, sandbox_id))

            bridge.status = SandboxBridgeStatus.BUSY
            bridge.current_task_id = active_task_id

            # Resolve session_id and timeout for the task
            task_session_id: Optional[uuid.UUID] = None
            task_timeout_sec = TASK_DEFAULT_TIMEOUT_SEC
            custom_names: set[str] = set()
            mcp_names: set[str] = set()
            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                task = await task_svc.get_task(active_task_id)
                if task:
                    bridge.current_owner_epoch = task.owner_epoch
                    task_session_id = task.chat_session_id
                    task_timeout_sec = task.timeout_sec or TASK_DEFAULT_TIMEOUT_SEC
                    from app.joysafeter_orchestrator.services import AgentService

                    agent_svc = AgentService(db)
                    agent = await agent_svc.get_agent(task.agent_id, project_id=getattr(task, "project_id", None))
                    if agent:
                        custom_names, mcp_names = extract_tool_name_sets(agent)

            # Replay pending control inputs submitted during disconnection
            if task_session_id:
                async with AsyncSessionLocal() as db:
                    session_svc = SessionService(db)
                    control_types = [
                        "user.tool_confirmation",
                        "user.custom_tool_result",
                        "user.interrupt",
                    ]
                    pending_events = await session_svc.list_unprocessed_events(task_session_id, control_types)
                    for evt in pending_events:
                        content = ""
                        if isinstance(evt.payload, dict):
                            content = evt.payload.get("content", "")
                        input_msg = joysafeter_pb2.OrchestratorMessage(input=joysafeter_pb2.SendInput(content=content))
                        await bridge.write_to_runner(input_msg)
                        await session_svc.mark_event_processed(evt.id)

            # --- Inner event loop for resumed task ---
            task_done = False
            got_idle = False
            heartbeat_timed_out = False
            requires_action_pending = False
            post_stop_reason: dict[str, Any] = {"type": "end_turn"}
            buffered_events: list[tuple[str, dict]] = []
            last_tool_use_event_id: Optional[str] = None

            # I4 fix: emit session.status_running on reconnect (Rust parity: server.rs lines 1247-1257)
            if task_session_id and self._event_bus:
                await self._event_bus.publish(
                    JoySafeterEventEnvelope(
                        session_id=task_session_id,
                        event_type="session.status_running",
                        payload={},
                        task_id=active_task_id,
                        sandbox_id=sandbox_id,
                        is_status_change=True,
                    )
                )

            import time as _time_reconnect

            heartbeat_deadline_rc = _time_reconnect.monotonic() + _get_heartbeat_timeout()
            task_deadline_rc = _time_reconnect.monotonic() + task_timeout_sec

            while True:
                read_fut = asyncio.ensure_future(context.read())
                cancel_fut = asyncio.ensure_future(bridge._cancel_event.wait())

                hb_remaining_rc = max(heartbeat_deadline_rc - _time_reconnect.monotonic(), 0.01)
                heartbeat_fut = asyncio.ensure_future(asyncio.sleep(hb_remaining_rc))

                waitables = [read_fut, heartbeat_fut, cancel_fut]
                if requires_action_pending:
                    confirm_fut = asyncio.ensure_future(bridge.confirmation_event.wait())
                    waitables.append(confirm_fut)
                else:
                    confirm_fut = None
                    dl_remaining_rc = max(task_deadline_rc - _time_reconnect.monotonic(), 0.01)
                    deadline_fut = asyncio.ensure_future(asyncio.sleep(dl_remaining_rc))
                    waitables.append(deadline_fut)

                done, pending = await asyncio.wait(
                    waitables,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for p in pending:
                    p.cancel()
                    try:
                        await p
                    except (asyncio.CancelledError, Exception):
                        pass

                # Cancel requested
                if cancel_fut in done:
                    bridge._cancel_event.clear()
                    logger.info("Cancel requested for resumed task %s, sending CancelTask", active_task_id)
                    cancel_msg = joysafeter_pb2.OrchestratorMessage(
                        cancel=joysafeter_pb2.CancelTask(reason="Cancelled by user")
                    )
                    await bridge.write_to_runner(cancel_msg)
                    continue

                # Confirmation received
                if confirm_fut in done and requires_action_pending:
                    requires_action_pending = False
                    bridge.confirmation_event.clear()
                    bridge._requires_action_pending = False
                    logger.info("Confirmation received for resumed task %s, resuming", active_task_id)
                    while not bridge._control_queue.empty():
                        try:
                            content = bridge._control_queue.get_nowait()
                            input_msg = joysafeter_pb2.OrchestratorMessage(
                                input=joysafeter_pb2.SendInput(content=content)
                            )
                            await bridge.write_to_runner(input_msg)
                        except asyncio.QueueEmpty:
                            break

                    if task_session_id:
                        if self._event_bus:
                            await self._event_bus.publish(
                                JoySafeterEventEnvelope(
                                    session_id=task_session_id,
                                    event_type="session.status_running",
                                    payload={},
                                    is_status_change=True,
                                    task_id=active_task_id,
                                    sandbox_id=sandbox_id,
                                )
                            )
                        else:
                            running_accepted = False
                            async with AsyncSessionLocal() as db:
                                svc = SessionService(db)
                                running_accepted = await svc.update_session_status_for_task_event(
                                    task_session_id,
                                    SessionStatus.RUNNING.value,
                                    active_task_id,
                                )
                                if running_accepted:
                                    await svc.send_event(
                                        task_session_id,
                                        "session.status_running",
                                        {"task_id": str(active_task_id)},
                                    )
                            broadcaster = get_session_broadcaster()
                            if broadcaster and running_accepted:
                                await broadcaster.send(
                                    task_session_id,
                                    {"type": "session.status_running", "task_id": str(active_task_id)},
                                )

                    if buffered_events and task_session_id:
                        for buf_type, buf_payload in buffered_events:
                            if self._event_bus:
                                await self._event_bus.publish(
                                    JoySafeterEventEnvelope(
                                        session_id=task_session_id,
                                        event_type=buf_type,
                                        payload=buf_payload,
                                        task_id=active_task_id,
                                        sandbox_id=sandbox_id,
                                        task_broadcast_payload={"type": buf_type, **buf_payload},
                                    )
                                )
                            else:
                                ws_msg = WsOutMessage(type="event", payload={"type": buf_type, **buf_payload})
                                await bridge.broadcast_to_task(active_task_id, ws_msg)
                                await _best_effort_publish_event(
                                    coordinator,
                                    active_task_id,
                                    json.dumps({"type": ws_msg.type, **ws_msg.payload}),
                                )
                                async with AsyncSessionLocal() as db:
                                    svc = SessionService(db)
                                    await svc.send_event(task_session_id, buf_type, buf_payload)
                                broadcaster = get_session_broadcaster()
                                if broadcaster:
                                    await broadcaster.send(
                                        task_session_id,
                                        {
                                            **{"type": buf_type},
                                            **(buf_payload if isinstance(buf_payload, dict) else {}),
                                        },
                                    )
                    buffered_events.clear()
                    continue

                # Heartbeat timeout
                if heartbeat_fut in done:
                    _log_grpc_boundary_failure(
                        code="GRPC_RESUMED_TASK_HEARTBEAT_TIMEOUT",
                        message="Heartbeat timeout during resumed task",
                        operation="run_resumed_task",
                        data={"task_id": str(active_task_id), "sandbox_id": str(sandbox_id)},
                        retryable=True,
                        user_action="retry",
                    )
                    heartbeat_timed_out = True
                    break

                # Task deadline
                if deadline_fut in done and not requires_action_pending:
                    _log_grpc_boundary_failure(
                        code="GRPC_RESUMED_TASK_DEADLINE_EXCEEDED",
                        message="Task deadline exceeded for resumed task",
                        operation="run_resumed_task",
                        data={
                            "task_id": str(active_task_id),
                            "sandbox_id": str(sandbox_id),
                            "timeout_sec": task_timeout_sec,
                        },
                        retryable=True,
                        user_action="retry",
                    )
                    cancel_msg = joysafeter_pb2.OrchestratorMessage(
                        cancel=joysafeter_pb2.CancelTask(reason=f"Server-side deadline exceeded ({task_timeout_sec}s)")
                    )
                    await bridge.write_to_runner(cancel_msg)
                    async with AsyncSessionLocal() as db:
                        task_svc = TaskService(db)
                        timeout_ok = await task_svc.update_task_error(
                            active_task_id,
                            f"Task timed out after {task_timeout_sec}s (server-side deadline)",
                            TaskStatus.TIMEOUT,
                            expected_epoch=bridge.current_owner_epoch,
                        )
                    if not timeout_ok:
                        _log_grpc_boundary_failure(
                            code="GRPC_RESUMED_TASK_TIMEOUT_CAS_CONFLICT",
                            message="CAS conflict timing out resumed task; ignoring stale deadline",
                            operation="timeout_resumed_task",
                            data={
                                "task_id": str(active_task_id),
                                "sandbox_id": str(sandbox_id),
                                "owner_epoch": bridge.current_owner_epoch,
                            },
                            retryable=False,
                            user_action=None,
                        )
                        stream_cancel.set()
                        return
                    post_stop_reason = {"type": "timeout"}
                    task_done = True
                    break

                # Stream message
                if read_fut not in done:
                    continue
                msg = read_fut.result()
                if msg == grpc_aio.EOF:
                    break

                # Reset heartbeat deadline on ANY message (Rust line 983)
                heartbeat_deadline_rc = _time_reconnect.monotonic() + _get_heartbeat_timeout()

                payload_type = msg.WhichOneof("payload")
                if payload_type is None:
                    continue

                if payload_type == "heartbeat":
                    continue
                elif payload_type == "event":
                    event = msg.event
                    raw_event = _proto_event_to_dict(event)
                    mapped_list = map_harness_event(raw_event, custom_names, mcp_names)

                    for mapped_type, mapped_payload in mapped_list:
                        if mapped_type == "memory_sync":
                            asyncio.create_task(_handle_memory_sync_standalone(task_session_id, mapped_payload))
                            continue

                        if mapped_type == "error":
                            bridge.last_error = mapped_payload.get("error") or mapped_payload.get("message")

                        if requires_action_pending:
                            if len(buffered_events) < 1000:
                                buffered_events.append((mapped_type, mapped_payload))
                            continue

                        if mapped_type in ("agent.tool_use", "agent.mcp_tool_use") and is_control_request(
                            mapped_payload
                        ):
                            call_id = (
                                mapped_payload.get("_call_id")
                                or mapped_payload.get("request_id")
                                or mapped_payload.get("id")
                                or mapped_payload.get("call_id")
                                or ""
                            )

                            event_id = f"evt_{uuid7()}"
                            persisted_id = uuid.UUID(str(uuid7())) if task_session_id else None
                            if self._event_bus and task_session_id:
                                await self._event_bus.publish(
                                    JoySafeterEventEnvelope(
                                        session_id=task_session_id,
                                        event_type=mapped_type,
                                        payload=mapped_payload,
                                        task_id=active_task_id,
                                        sandbox_id=sandbox_id,
                                        event_id=persisted_id,
                                        seq=event.seq,
                                        flush_immediately=True,
                                        task_broadcast_payload={"type": mapped_type, **mapped_payload},
                                    )
                                )
                                event_id = f"evt_{persisted_id}"
                                last_tool_use_event_id = event_id
                            else:
                                ws_msg = WsOutMessage(type="event", payload={"type": mapped_type, **mapped_payload})
                                await bridge.broadcast_to_task(active_task_id, ws_msg)
                                await _best_effort_publish_event(
                                    coordinator,
                                    active_task_id,
                                    json.dumps({"type": ws_msg.type, **ws_msg.payload}),
                                )

                                if task_session_id:
                                    buffered = BufferedEvent(
                                        session_id=task_session_id,
                                        event_type=mapped_type,
                                        payload=mapped_payload,
                                        seq=event.seq,
                                        id=persisted_id,
                                    )
                                    await self._event_buffer.send(buffered)
                                    await self._event_buffer.flush()
                                    event_id = f"evt_{persisted_id}"
                                    last_tool_use_event_id = event_id
                                    broadcaster = get_session_broadcaster()
                                    if broadcaster:
                                        await broadcaster.send(
                                            task_session_id,
                                            {
                                                **{"type": mapped_type, "seq": event.seq},
                                                **(mapped_payload if isinstance(mapped_payload, dict) else {}),
                                            },
                                        )

                            if call_id:
                                bridge.pending_control_request_ids[event_id] = call_id
                            requires_action_pending = True
                            bridge._requires_action_pending = True
                            if task_session_id:
                                stop_reason = {"type": "requires_action", "event_ids": [event_id]}
                                # Agentd three-step: direct DB write first, then broadcast
                                async with AsyncSessionLocal() as db:
                                    svc = SessionService(db)
                                    await svc.update_session_status_for_task_event(
                                        task_session_id,
                                        SessionStatus.IDLE.value,
                                        active_task_id,
                                        stop_reason=stop_reason,
                                    )
                                    await svc.send_event(
                                        task_session_id,
                                        "session.status_idle",
                                        {"task_id": str(active_task_id), "stop_reason": stop_reason},
                                    )
                                if self._event_bus:
                                    await self._event_bus.publish(
                                        JoySafeterEventEnvelope(
                                            session_id=task_session_id,
                                            event_type="session.status_idle",
                                            payload={"task_id": str(active_task_id), "stop_reason": stop_reason},
                                            is_status_change=True,
                                            stop_reason=stop_reason,
                                            task_id=active_task_id,
                                            sandbox_id=sandbox_id,
                                        )
                                    )
                                broadcaster = get_session_broadcaster()
                                if broadcaster:
                                    await broadcaster.send(
                                        task_session_id,
                                        {
                                            "type": "session.status_idle",
                                            "task_id": str(active_task_id),
                                            "stop_reason": stop_reason,
                                        },
                                    )
                            continue

                        if mapped_type in ("session.status_running", "session.status_idle") and task_session_id:
                            await self._emit_task_scoped_status_event(
                                session_id=task_session_id,
                                task_id=active_task_id,
                                mapped_type=mapped_type,
                                mapped_payload=mapped_payload,
                                sandbox_id=sandbox_id,
                                seq=event.seq,
                                bridge=bridge,
                            )
                            continue

                        if self._event_bus and task_session_id:
                            await self._event_bus.publish(
                                JoySafeterEventEnvelope(
                                    session_id=task_session_id,
                                    event_type=mapped_type,
                                    payload=mapped_payload,
                                    task_id=active_task_id,
                                    sandbox_id=sandbox_id,
                                    seq=event.seq,
                                    task_broadcast_payload={"type": mapped_type, **mapped_payload},
                                )
                            )
                        else:
                            ws_msg = WsOutMessage(
                                type="event",
                                payload={"type": mapped_type, **mapped_payload},
                            )
                            await bridge.broadcast_to_task(active_task_id, ws_msg)

                            await _best_effort_publish_event(
                                coordinator,
                                active_task_id,
                                json.dumps({"type": ws_msg.type, **ws_msg.payload}),
                            )

                            if task_session_id:
                                async with AsyncSessionLocal() as db:
                                    svc = SessionService(db)
                                    await svc.send_event(
                                        task_session_id,
                                        mapped_type,
                                        mapped_payload,
                                    )

                                broadcaster = get_session_broadcaster()
                                if broadcaster:
                                    await broadcaster.send(
                                        task_session_id,
                                        {
                                            **{"type": mapped_type, "seq": event.seq},
                                            **(mapped_payload if isinstance(mapped_payload, dict) else {}),
                                        },
                                    )

                        if mapped_type == "agent.custom_tool_use" and not requires_action_pending:
                            call_id = (
                                mapped_payload.get("_call_id")
                                or mapped_payload.get("request_id")
                                or mapped_payload.get("id")
                                or mapped_payload.get("call_id")
                                or ""
                            )
                            event_id = last_tool_use_event_id or f"evt_{uuid7()}"
                            if call_id:
                                bridge.pending_control_request_ids[event_id] = call_id
                            requires_action_pending = True
                            bridge._requires_action_pending = True
                            if task_session_id:
                                await self._event_buffer.flush()
                                stop_reason = {"type": "requires_action", "event_ids": [event_id]}
                                if self._event_bus:
                                    await self._event_bus.publish(
                                        JoySafeterEventEnvelope(
                                            session_id=task_session_id,
                                            event_type="session.status_idle",
                                            payload={"task_id": str(active_task_id), "stop_reason": stop_reason},
                                            is_status_change=True,
                                            stop_reason=stop_reason,
                                            task_id=active_task_id,
                                            sandbox_id=sandbox_id,
                                        )
                                    )
                                else:
                                    async with AsyncSessionLocal() as db:
                                        svc = SessionService(db)
                                        await svc.update_session_status_for_task_event(
                                            task_session_id,
                                            SessionStatus.IDLE.value,
                                            active_task_id,
                                            stop_reason=stop_reason,
                                        )
                                        await svc.send_event(
                                            task_session_id,
                                            "session.status_idle",
                                            {"task_id": str(active_task_id), "stop_reason": stop_reason},
                                        )
                                    broadcaster = get_session_broadcaster()
                                    if broadcaster:
                                        await broadcaster.send(
                                            task_session_id,
                                            {
                                                "type": "session.status_idle",
                                                "task_id": str(active_task_id),
                                                "stop_reason": stop_reason,
                                            },
                                        )

                elif payload_type == "result":
                    result = msg.result
                    result_accepted = await self._handle_reconnect_result(
                        bridge,
                        sandbox_id,
                        active_task_id,
                        task_session_id,
                        result,
                        coordinator,
                    )
                    if not result_accepted:
                        _log_grpc_boundary_failure(
                            code="GRPC_STALE_RECONNECT_RESULT_IGNORED",
                            message="Ignoring stale reconnect result",
                            operation="handle_reconnect_result",
                            data={"task_id": str(active_task_id), "sandbox_id": str(sandbox_id)},
                            retryable=False,
                            user_action=None,
                        )
                        stream_cancel.set()
                        return
                    task_done = True

                elif payload_type == "idle":
                    if not task_done:
                        _log_grpc_boundary_failure(
                            code="GRPC_RESUMED_RUNNER_IDLE_BEFORE_RESULT",
                            message="Runner idle before result for resumed task",
                            operation="run_resumed_task",
                            data={"task_id": str(active_task_id), "sandbox_id": str(sandbox_id)},
                            retryable=True,
                            user_action="retry",
                        )
                        break
                    idle_msg = msg.idle
                    bridge.status = SandboxBridgeStatus.IDLE
                    bridge.current_task_id = None
                    logger.info("Runner idle after resumed task: sandbox=%s", sandbox_id)

                    async with AsyncSessionLocal() as db:
                        sandbox_svc = SandboxService(db)
                        await sandbox_svc.update_status(sandbox_id, "idle")
                        await sandbox_svc.touch(sandbox_id)

                    if coordinator:
                        await _best_effort_redis("refresh_sandbox_owner", coordinator.refresh_sandbox_owner(sandbox_id))

                    async with AsyncSessionLocal() as db:
                        sandbox_svc2 = SandboxService(db)
                        sandbox_record = await sandbox_svc2.get_sandbox(sandbox_id)
                        if sandbox_record and sandbox_record.chat_session_id:
                            harness_session_id = idle_msg.session_id if idle_msg.HasField("session_id") else None
                            work_dir = idle_msg.work_dir if idle_msg.HasField("work_dir") else None
                            svc = SessionService(db)
                            await svc.update_session_sandbox(
                                sandbox_record.chat_session_id,
                                sandbox_id,
                                harness_session_id=harness_session_id,
                                work_dir=work_dir,
                            )

                    got_idle = True

                elif payload_type == "memory_sync":
                    ms = msg.memory_sync
                    asyncio.create_task(
                        _handle_memory_sync_standalone(
                            task_session_id,
                            {
                                "store_mount_name": ms.store_mount_name,
                                "relative_path": ms.relative_path,
                                "content": ms.content,
                                "operation": ms.operation,
                            },
                        )
                    )

                if task_done:
                    break

            # --- Post resumed-task handling ---
            if not task_done:
                await self._event_buffer.flush()
                last_err = bridge.last_error
                if heartbeat_timed_out and last_err:
                    reason = f"Heartbeat timeout — sandbox unresponsive after reconnect (last error: {last_err})"
                elif heartbeat_timed_out:
                    reason = "Heartbeat timeout — sandbox unresponsive (after reconnect)"
                elif last_err:
                    reason = f"Sandbox disconnected after reconnect (last error: {last_err})"
                else:
                    reason = "Sandbox disconnected after reconnect"
                _log_grpc_boundary_failure(
                    code="GRPC_RESUMED_TASK_INCOMPLETE",
                    message="Resumed task incomplete after sandbox disconnect",
                    operation="failover_resumed_task",
                    data={
                        "task_id": str(active_task_id),
                        "sandbox_id": str(sandbox_id),
                        "reason": reason,
                        "owner_epoch": bridge.current_owner_epoch,
                    },
                    retryable=True,
                    user_action="retry",
                )
                retry_count = await TaskController.failover_or_fail_task(
                    active_task_id,
                    reason,
                    expected_epoch=bridge.current_owner_epoch,
                )
                if retry_count is not None:
                    failover_pending_tasks.append((active_task_id, retry_count))
                bridge.remove_task_subscribers(active_task_id)
                if coordinator:
                    await _best_effort_redis("remove_task_sandbox", coordinator.remove_task_sandbox(active_task_id))
                if not got_idle:
                    # Stream broken -- signal cleanup
                    stream_cancel.set()

            if task_done and not got_idle:
                bridge.status = SandboxBridgeStatus.IDLE
                bridge.current_task_id = None
                await self._event_buffer.flush()
                if self._event_bus:
                    await self._event_bus.flush()
                async with AsyncSessionLocal() as db:
                    sandbox_svc = SandboxService(db)
                    await sandbox_svc.update_status(sandbox_id, "idle")
                bridge.remove_task_subscribers(active_task_id)
                if coordinator:
                    await _best_effort_redis("remove_task_sandbox", coordinator.remove_task_sandbox(active_task_id))

                # Emit session.status_idle — matches main task loop and Rust behavior
                # Agentd three-step: direct DB write + event insert + broadcast
                stop_reason = post_stop_reason
                if task_session_id:
                    async with AsyncSessionLocal() as idle_db:
                        session_svc = SessionService(idle_db)
                        await session_svc.update_session_status_for_task_event(
                            task_session_id,
                            SessionStatus.IDLE.value,
                            active_task_id,
                            stop_reason,
                        )
                        await session_svc.send_event(
                            task_session_id,
                            "session.status_idle",
                            {"task_id": str(active_task_id), "stop_reason": stop_reason},
                        )
                    # Also broadcast for SSE delivery
                    if self._event_bus:
                        await self._event_bus.publish(
                            JoySafeterEventEnvelope(
                                session_id=task_session_id,
                                event_type="session.status_idle",
                                payload={"task_id": str(active_task_id), "stop_reason": stop_reason},
                                task_id=active_task_id,
                                sandbox_id=sandbox_id,
                                is_status_change=True,
                                stop_reason=stop_reason,
                            )
                        )

        finally:
            self._execution_semaphore.release()

    async def _rescue_orphaned_tasks(self, sandbox_id: uuid.UUID) -> None:
        """Re-queue running tasks orphaned by a runner that reconnected without active_task_id."""
        from sqlalchemy import and_, select

        from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
        from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus
        from app.joysafeter_orchestrator.kernel.task_controller import TaskController
        from app.joysafeter_shared.database import AsyncSessionLocal

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(JoySafeterTask.id).where(
                        and_(
                            JoySafeterTask.sandbox_id == sandbox_id,
                            JoySafeterTask.status == TaskStatus.RUNNING.value,
                        )
                    )
                )
                orphaned_ids = [row[0] for row in result.fetchall()]

                if not orphaned_ids:
                    return

                logger.info(
                    "Rescuing %d orphaned running task(s) for sandbox %s: %s",
                    len(orphaned_ids),
                    sandbox_id,
                    orphaned_ids,
                )

                for tid in orphaned_ids:
                    retry_count = await TaskController.failover_or_fail_task(
                        tid,
                        "Runner reconnected without active task",
                    )
                    if retry_count is not None:
                        await self._queue.push_to_global(tid)
                        logger.info("Orphaned task %s reset to pending and re-queued", tid)
                    else:
                        _log_grpc_boundary_failure(
                            code="GRPC_ORPHAN_TASK_FAILOVER_SKIPPED",
                            message="Could not fail over orphaned task",
                            operation="rescue_orphaned_task",
                            data={"sandbox_id": str(sandbox_id), "task_id": str(tid)},
                            retryable=False,
                            user_action="refresh",
                        )
        except Exception as e:
            _log_grpc_boundary_failure(
                code="GRPC_ORPHAN_TASK_RESCUE_FAILED",
                message="Failed to rescue orphaned tasks for sandbox",
                operation="rescue_orphaned_tasks",
                error=e,
                data={"sandbox_id": str(sandbox_id)},
                level="error",
            )

    async def _multi_task_loop(
        self,
        bridge: SandboxBridge,
        sandbox_id: uuid.UUID,
        context,
        stream_cancel: asyncio.Event,
        failover_pending_tasks: list,
        linked_session_id: Optional[uuid.UUID] = None,
    ) -> bool:
        """Outer loop: block on pop_for_sandbox, dispatch tasks one at a time.

        Returns True if the sandbox was failure-ejected.

        Uses a single persistent read coroutine that is reused across idle and
        task phases to avoid corrupting the gRPC stream. The pending read future
        is passed into _run_single_task so it can consume the first message.
        """
        import time as _time

        from app.joysafeter_shared.config.settings import joysafeter_config

        heartbeat_deadline = _time.monotonic() + _get_heartbeat_timeout()
        consecutive_failures: int = 0
        failure_ejected = False

        pending_read: Optional[asyncio.Future] = None
        idle_wait_secs = 1.0

        logger.info("Entering multi-task loop for sandbox %s (stream_cancel=%s)", sandbox_id, stream_cancel.is_set())
        while not stream_cancel.is_set():
            # Idle phase: DB is the durable source of tasks. The sandbox queue is
            # only a wakeup signal so a lost Redis/local queue item cannot lose work.
            claimed = await self._claim_next_sandbox_task_from_db(sandbox_id)
            task_id: Optional[uuid.UUID] = None
            owner_epoch: int = 0
            if claimed is not None:
                task_id, owner_epoch = claimed
            pop_task: Optional[asyncio.Task] = None
            if task_id is None:
                pop_task = asyncio.create_task(
                    self._queue.wait_for_sandbox_wakeup(
                        sandbox_id,
                        stream_cancel,
                        timeout_secs=idle_wait_secs + random.uniform(0, 0.25),
                    ),
                    name=f"wakeup-{sandbox_id}",
                )

            while not stream_cancel.is_set():
                if task_id is not None:
                    break

                if pending_read is None:
                    pending_read = asyncio.ensure_future(context.read())

                waitables = {pending_read}
                if pop_task is not None:
                    waitables.add(pop_task)

                hb_remaining = max(heartbeat_deadline - _time.monotonic(), 0.01)
                hb_timer = asyncio.create_task(asyncio.sleep(hb_remaining))
                waitables.add(hb_timer)

                done, pending = await asyncio.wait(
                    waitables,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for p in pending:
                    if p is not pending_read and p is not pop_task:
                        p.cancel()
                        try:
                            await p
                        except (asyncio.CancelledError, Exception):
                            pass

                if pending_read in done:
                    msg = pending_read.result()
                    pending_read = None
                    if msg == grpc_aio.EOF:
                        stream_cancel.set()
                        if pop_task is not None:
                            pop_task.cancel()
                            try:
                                await pop_task
                            except (asyncio.CancelledError, Exception):
                                pass
                        break
                    payload_type = msg.WhichOneof("payload")
                    if payload_type == "heartbeat":
                        heartbeat_deadline = _time.monotonic() + _get_heartbeat_timeout()
                        # Heartbeats no longer touch last_used_at: the idle
                        # sweep now drives off idle_since (set on RunnerIdle)
                        # plus a disconnect/hard-timeout fallback, so the
                        # row doesn't need a per-heartbeat write to stay
                        # alive. This eliminates the per-row bloat we used
                        # to see on long-running sandboxes.
                    continue

                if pop_task in done:
                    claimed = await self._claim_next_sandbox_task_from_db(sandbox_id)
                    if claimed is not None:
                        task_id, owner_epoch = claimed
                        idle_wait_secs = 1.0
                        break
                    idle_wait_secs = min(idle_wait_secs * 1.5, 5.0)
                    pop_task = asyncio.create_task(
                        self._queue.wait_for_sandbox_wakeup(
                            sandbox_id,
                            stream_cancel,
                            timeout_secs=idle_wait_secs + random.uniform(0, 0.25),
                        ),
                        name=f"wakeup-{sandbox_id}",
                    )
                    continue

                if hb_timer in done:
                    now = _time.monotonic()
                    if now >= heartbeat_deadline:
                        _log_grpc_boundary_failure(
                            code="GRPC_IDLE_HEARTBEAT_TIMEOUT",
                            message="Heartbeat timeout while sandbox idle",
                            operation="idle_heartbeat_timeout",
                            data={"sandbox_id": str(sandbox_id)},
                        )
                        stream_cancel.set()
                        if pop_task is not None:
                            pop_task.cancel()
                            try:
                                await pop_task
                            except (asyncio.CancelledError, Exception):
                                pass
                        break

            if stream_cancel.is_set() and task_id is None:
                logger.info("Multi-task loop: stream cancelled, no task for sandbox %s", sandbox_id)
                break
            if task_id is None:
                logger.info("Pop cancelled for sandbox %s (stream dead or shutdown)", sandbox_id)
                break
            logger.info("Multi-task loop: got task %s for sandbox %s", task_id, sandbox_id)
            idle_wait_secs = 1.0

            # Acquire execution semaphore before dispatching
            await self._execution_semaphore.acquire()
            try:
                success, task_deadline_exceeded, task_error_status, task_completed = await self._run_single_task(
                    bridge,
                    sandbox_id,
                    context,
                    task_id,
                    owner_epoch,
                    stream_cancel,
                    failover_pending_tasks,
                    linked_session_id,
                    pending_read=pending_read,
                )
                pending_read = None  # _run_single_task consumed or cancelled it
                heartbeat_deadline = _time.monotonic() + _get_heartbeat_timeout()
            finally:
                self._execution_semaphore.release()

            # Track consecutive failures for sandbox ejection (Rust lines 1122-1133)
            # Only reset on Completed; only increment on Failed/Aborted/Timeout.
            # Other statuses (e.g. non-terminal) leave counter unchanged.
            if task_completed:
                consecutive_failures = 0
                bridge.last_error = None
            elif task_error_status or task_deadline_exceeded:
                consecutive_failures += 1

            if consecutive_failures >= joysafeter_config.sandbox_failure_threshold:
                _log_grpc_boundary_failure(
                    code="GRPC_SANDBOX_FAILURE_THRESHOLD_EXCEEDED",
                    message="Sandbox exceeded failure threshold; ejecting",
                    operation="eject_failed_sandbox",
                    data={
                        "sandbox_id": str(sandbox_id),
                        "consecutive_failures": consecutive_failures,
                        "threshold": joysafeter_config.sandbox_failure_threshold,
                    },
                    retryable=True,
                    user_action="retry",
                )
                failure_ejected = True
                break

            if not success:
                logger.warning("_multi_task_loop: task %s returned success=False, breaking", task_id)
                break

        if pending_read is not None:
            pending_read.cancel()
            try:
                await pending_read
            except (asyncio.CancelledError, Exception):
                pass
        return failure_ejected

    async def _claim_next_sandbox_task_from_db(self, sandbox_id: uuid.UUID) -> Optional[tuple[uuid.UUID, int]]:
        from app.joysafeter_orchestrator.services import TaskService
        from app.joysafeter_shared.database import AsyncSessionLocal

        try:
            async with AsyncSessionLocal() as db:
                return await TaskService(db).claim_next_sandbox_task_for_running(sandbox_id)
        except Exception as e:
            _log_grpc_boundary_failure(
                code="GRPC_SANDBOX_TASK_CLAIM_FAILED",
                message="Failed to claim next scheduling task for sandbox",
                operation="claim_next_sandbox_task",
                error=e,
                data={"sandbox_id": str(sandbox_id)},
            )
            return None

    async def _run_single_task(
        self,
        bridge: SandboxBridge,
        sandbox_id: uuid.UUID,
        context,
        task_id: uuid.UUID,
        owner_epoch: int,
        stream_cancel: asyncio.Event,
        failover_pending_tasks: list,
        linked_session_id: Optional[uuid.UUID] = None,
        pending_read: Optional[asyncio.Future] = None,
    ) -> tuple[bool, bool, bool, bool]:
        """Inner per-task loop: send StartTask, read events until Result+Idle.

        Returns a tuple of:
          - continue_loop: True if outer loop should continue, False if stream broke.
          - deadline_exceeded: True if the task was cancelled due to deadline.
          - task_error_status: True if the task ended in a failed/aborted/timeout state.
          - task_completed: True if the task ended with Completed status.
        """
        from app.joysafeter_domain.models.joysafeter_session import SessionStatus
        from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus
        from app.joysafeter_orchestrator.events.event_mapping import is_control_request, map_harness_event
        from app.joysafeter_orchestrator.kernel.harness_input_builder import (
            build_harness_input,
            extract_tool_name_sets,
        )
        from app.joysafeter_orchestrator.kernel.task_controller import TaskController
        from app.joysafeter_orchestrator.lifespan import get_redis_coordinator, get_session_broadcaster
        from app.joysafeter_orchestrator.services import AgentService, SessionService, TaskService
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from app.joysafeter_shared.config.settings import joysafeter_config
        from app.joysafeter_shared.database import AsyncSessionLocal

        logger.info("Dispatching task %s to sandbox %s", task_id, sandbox_id)

        # Issue 3 fix: set task->sandbox mapping in Redis (matching Rust line 757)
        coordinator = get_redis_coordinator()
        if coordinator:
            await _best_effort_redis("set_task_sandbox", coordinator.set_task_sandbox(task_id, sandbox_id))

        bridge.status = SandboxBridgeStatus.BUSY
        bridge.current_task_id = task_id
        bridge.current_owner_epoch = owner_epoch

        # I1 fix: update sandbox DB status to "running" (Rust parity: server.rs line 427)
        try:
            async with AsyncSessionLocal() as db:
                svc = SandboxService(db)
                await svc.update_status(sandbox_id, "running")
        except Exception as e:
            _log_grpc_boundary_failure(
                code="GRPC_SANDBOX_STATUS_RUNNING_UPDATE_FAILED",
                message="Failed to set sandbox status to running",
                operation="set_sandbox_running",
                error=e,
                data={"sandbox_id": str(sandbox_id), "task_id": str(task_id)},
            )

        # Pool fix: send SetupSandbox if not done yet (pool containers skip setup on first connect)
        if not bridge.setup_done:
            await self._send_setup(bridge, sandbox_id)

        # --- Build and send StartTask ---
        try:
            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                agent_svc = AgentService(db)
                session_svc = SessionService(db)
                sandbox_svc = SandboxService(db)

                task = await task_svc.get_task(task_id)
                if not task:
                    _log_grpc_boundary_failure(
                        code="GRPC_TASK_NOT_FOUND_FOR_DISPATCH",
                        message="Task not found for gRPC dispatch",
                        operation="load_task_for_dispatch",
                        data={"task_id": str(task_id), "sandbox_id": str(sandbox_id)},
                        retryable=False,
                        user_action="refresh",
                    )
                    bridge.current_task_id = None
                    bridge.status = SandboxBridgeStatus.IDLE
                    return (True, False, False, False)

                agent = await agent_svc.get_agent(task.agent_id, project_id=getattr(task, "project_id", None))
                if not agent:
                    await task_svc.update_task_error(
                        task_id,
                        "Agent not found",
                        TaskStatus.FAILED,
                        expected_epoch=bridge.current_owner_epoch,
                    )
                    bridge.current_task_id = None
                    bridge.status = SandboxBridgeStatus.IDLE
                    # Fix 4.5: clean up Redis task mapping on early exit
                    coordinator = get_redis_coordinator()
                    if coordinator:
                        await _best_effort_redis("remove_task_sandbox", coordinator.remove_task_sandbox(task_id))
                    return (True, False, True, False)

                if task.status != TaskStatus.RUNNING.value:
                    _log_grpc_boundary_failure(
                        code="GRPC_CLAIMED_TASK_NOT_RUNNING",
                        message="Task was not running after sandbox claim; skipping dispatch",
                        operation="dispatch_claimed_task",
                        data={"task_id": str(task_id), "sandbox_id": str(sandbox_id), "status": task.status},
                        retryable=False,
                        user_action=None,
                    )
                    bridge.current_task_id = None
                    bridge.status = SandboxBridgeStatus.IDLE
                    coordinator = get_redis_coordinator()
                    if coordinator:
                        await _best_effort_redis("remove_task_sandbox", coordinator.remove_task_sandbox(task_id))
                    return (True, False, False, False)

                session_id = task.chat_session_id

                await sandbox_svc.touch(sandbox_id, task_id)

                session = None
                environment = None
                if session_id:
                    session = await session_svc.get_session(session_id)

                env_ref = getattr(agent, "environment_ref", None)
                if env_ref:
                    from app.joysafeter_orchestrator.services import EnvironmentService

                    env_svc = EnvironmentService(db)
                    environment = await env_svc.get_environment_by_ref(
                        env_ref, project_id=getattr(agent, "project_id", None)
                    )

            harness_input = await build_harness_input(
                task,
                agent,
                session_id,
                bridge.external_id,
                sandbox_id,
            )

            custom_names, mcp_names = extract_tool_name_sets(agent)

            start_msg = _build_start_task(
                task_id,
                harness_input,
                task,
                joysafeter_config,
                agent=agent,
                session=session,
                environment=environment,
            )
            orch_msg = joysafeter_pb2.OrchestratorMessage(start=start_msg)
            await bridge.write_to_runner(orch_msg)
            logger.info("StartTask sent: task=%s sandbox=%s", task_id, sandbox_id)

            if session_id and self._event_bus:
                await self._event_bus.publish(
                    JoySafeterEventEnvelope(
                        session_id=session_id,
                        event_type="session.status_running",
                        payload={},
                        is_status_change=True,
                        task_id=task_id,
                        sandbox_id=sandbox_id,
                    )
                )
        except Exception as e:
            _log_grpc_boundary_failure(
                code="GRPC_TASK_DISPATCH_FAILED",
                message="Failed to dispatch task to runner",
                operation="dispatch_task",
                error=e,
                data={"sandbox_id": str(sandbox_id), "task_id": str(task_id), "session_id": str(session_id)},
                level="error",
            )
            bridge.current_task_id = None
            bridge.status = SandboxBridgeStatus.IDLE
            await TaskController.failover_or_fail_task(task_id, str(e), expected_epoch=bridge.current_owner_epoch)
            return (True, False, True, False)

        # --- Inner per-task event loop ---
        import time as _time

        task_done = False
        got_idle = False
        requires_action_pending = False
        deadline_exceeded = False
        task_error_status = False
        task_completed = False
        timeout = task.timeout_sec or joysafeter_config.task_default_timeout
        last_tool_use_event_id: Optional[str] = None
        buffered_events: list[tuple[str, dict]] = []

        heartbeat_deadline = _time.monotonic() + _get_heartbeat_timeout()
        task_deadline = _time.monotonic() + timeout

        logger.info("Entering event loop for task %s on sandbox %s", task_id, sandbox_id)
        _reuse_read = pending_read
        while True:
            if _reuse_read is not None:
                read_fut = _reuse_read
                _reuse_read = None
            else:
                read_fut = asyncio.ensure_future(context.read())
            cancel_fut = asyncio.ensure_future(bridge._cancel_event.wait())

            hb_remaining = max(heartbeat_deadline - _time.monotonic(), 0.01)
            heartbeat_fut = asyncio.ensure_future(asyncio.sleep(hb_remaining))

            waitables = [read_fut, heartbeat_fut, cancel_fut]
            if requires_action_pending:
                confirm_fut = asyncio.ensure_future(bridge.confirmation_event.wait())
                waitables.append(confirm_fut)
            else:
                confirm_fut = None
                dl_remaining = max(task_deadline - _time.monotonic(), 0.01)
                deadline_fut = asyncio.ensure_future(asyncio.sleep(dl_remaining))
                waitables.append(deadline_fut)

            done, pending = await asyncio.wait(
                waitables,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for p in pending:
                p.cancel()
                try:
                    await p
                except (asyncio.CancelledError, Exception):
                    pass

            # --- Cancel requested ---
            if cancel_fut in done:
                bridge._cancel_event.clear()
                logger.info("Cancel requested for task %s, sending CancelTask", task_id)
                cancel_msg = joysafeter_pb2.OrchestratorMessage(
                    cancel=joysafeter_pb2.CancelTask(reason="Cancelled by user")
                )
                await bridge.write_to_runner(cancel_msg)

                # C1 fix: update task status to cancelled + emit session.status_idle (Rust parity)
                try:
                    async with AsyncSessionLocal() as db:
                        task_svc = TaskService(db)
                        cancel_ok = await task_svc.update_task_status(
                            task_id,
                            TaskStatus.CANCELLED,
                            expected_epoch=bridge.current_owner_epoch,
                        )
                    if not cancel_ok:
                        _log_grpc_boundary_failure(
                            code="GRPC_CANCEL_TASK_CAS_CONFLICT",
                            message="CAS conflict cancelling task; ignoring stale cancel",
                            operation="cancel_task",
                            data={
                                "task_id": str(task_id),
                                "sandbox_id": str(sandbox_id),
                                "owner_epoch": bridge.current_owner_epoch,
                            },
                            retryable=False,
                            user_action=None,
                        )
                        return (False, False, False, False)
                    if session_id and self._event_bus:
                        stop_reason: dict[str, Any] = {"type": "cancelled"}
                        await self._event_bus.publish(
                            JoySafeterEventEnvelope(
                                session_id=session_id,
                                event_type="session.status_idle",
                                payload={"task_id": str(task_id), "stop_reason": stop_reason},
                                task_id=task_id,
                                sandbox_id=sandbox_id,
                                is_status_change=True,
                                stop_reason=stop_reason,
                            )
                        )
                except Exception as e:
                    _log_grpc_boundary_failure(
                        code="GRPC_CANCELLED_TASK_UPDATE_FAILED",
                        message="Failed to update cancelled task",
                        operation="update_cancelled_task",
                        error=e,
                        data={"sandbox_id": str(sandbox_id), "task_id": str(task_id), "session_id": str(session_id)},
                    )

                continue

            # --- Confirmation received (Rust lines 938-951 + loop-top flush 898-929) ---
            if confirm_fut in done and requires_action_pending:
                requires_action_pending = False
                bridge.confirmation_event.clear()
                bridge._requires_action_pending = False
                # Reset task deadline after HITL resume (matching Rust line 753)
                task_deadline = _time.monotonic() + timeout
                logger.info("Confirmation received for task %s, resuming", task_id)
                while not bridge._control_queue.empty():
                    try:
                        content = bridge._control_queue.get_nowait()
                        input_msg = joysafeter_pb2.OrchestratorMessage(input=joysafeter_pb2.SendInput(content=content))
                        await bridge.write_to_runner(input_msg)
                    except asyncio.QueueEmpty:
                        break

                # Rust confirmation handler: update status + emit running event
                if session_id:
                    if self._event_bus:
                        await self._event_bus.publish(
                            JoySafeterEventEnvelope(
                                session_id=session_id,
                                event_type="session.status_running",
                                payload={},
                                is_status_change=True,
                                task_id=task_id,
                                sandbox_id=sandbox_id,
                            )
                        )
                    else:
                        running_accepted = False
                        async with AsyncSessionLocal() as db:
                            session_svc = SessionService(db)
                            running_accepted = await session_svc.update_session_status_for_task_event(
                                session_id,
                                SessionStatus.RUNNING.value,
                                task_id,
                            )
                            if running_accepted:
                                await session_svc.send_event(
                                    session_id,
                                    "session.status_running",
                                    {"task_id": str(task_id)},
                                )
                        broadcaster = get_session_broadcaster()
                        if broadcaster and running_accepted:
                            await broadcaster.send(
                                session_id,
                                {"type": "session.status_running", "task_id": str(task_id)},
                            )

                # Flush buffered events (Rust loop-top flush, lines 898-929)
                if buffered_events:
                    logger.info(
                        "Flushing %d buffered events after confirmation for task %s", len(buffered_events), task_id
                    )
                    if session_id:
                        # Rust loop-top flush also emits session.status_running again
                        if self._event_bus:
                            await self._event_bus.publish(
                                JoySafeterEventEnvelope(
                                    session_id=session_id,
                                    event_type="session.status_running",
                                    payload={},
                                    is_status_change=True,
                                    task_id=task_id,
                                    sandbox_id=sandbox_id,
                                )
                            )
                        else:
                            running_accepted = False
                            async with AsyncSessionLocal() as db:
                                session_svc = SessionService(db)
                                running_accepted = await session_svc.update_session_status_for_task_event(
                                    session_id,
                                    SessionStatus.RUNNING.value,
                                    task_id,
                                )
                                if running_accepted:
                                    await session_svc.send_event(
                                        session_id,
                                        "session.status_running",
                                        {"task_id": str(task_id)},
                                    )
                            broadcaster = get_session_broadcaster()
                            if broadcaster and running_accepted:
                                await broadcaster.send(
                                    session_id,
                                    {"type": "session.status_running", "task_id": str(task_id)},
                                )

                        for buf_type, buf_payload in buffered_events:
                            if self._event_bus:
                                await self._event_bus.publish(
                                    JoySafeterEventEnvelope(
                                        session_id=session_id,
                                        event_type=buf_type,
                                        payload=buf_payload,
                                        task_id=task_id,
                                        sandbox_id=sandbox_id,
                                        task_broadcast_payload={"type": buf_type, **buf_payload},
                                    )
                                )
                            else:
                                ws_msg = WsOutMessage(
                                    type="event",
                                    payload={"type": buf_type, **buf_payload},
                                )
                                await bridge.broadcast_to_task(task_id, ws_msg)

                                coordinator = get_redis_coordinator()
                                await _best_effort_publish_event(
                                    coordinator,
                                    task_id,
                                    json.dumps({"type": ws_msg.type, **ws_msg.payload}),
                                )

                                buffered = BufferedEvent(
                                    session_id=session_id,
                                    event_type=buf_type,
                                    payload=buf_payload,
                                    seq=0,
                                )
                                await self._event_buffer.send(buffered)

                                broadcaster = get_session_broadcaster()
                                if broadcaster:
                                    await broadcaster.send(
                                        session_id,
                                        {
                                            **{"type": buf_type},
                                            **(buf_payload if isinstance(buf_payload, dict) else {}),
                                        },
                                    )
                    # When session_id is None, just discard buffered events (Rust line 928)
                    buffered_events.clear()

                continue

            # --- Heartbeat timeout ---
            if heartbeat_fut in done:
                await self._event_buffer.flush()
                last_err = bridge.last_error
                if last_err:
                    reason = f"Heartbeat timeout — sandbox unresponsive (last error: {last_err})"
                else:
                    reason = "Heartbeat timeout — sandbox unresponsive"
                _log_grpc_boundary_failure(
                    code="GRPC_TASK_HEARTBEAT_TIMEOUT",
                    message="Heartbeat timeout during task",
                    operation="task_heartbeat_timeout",
                    data={"task_id": str(task_id), "sandbox_id": str(sandbox_id)},
                )
                retry_count = await TaskController.failover_or_fail_task(
                    task_id,
                    reason,
                    expected_epoch=bridge.current_owner_epoch,
                )
                if retry_count is not None:
                    failover_pending_tasks.append((task_id, retry_count))
                bridge.remove_task_subscribers(task_id)
                from app.joysafeter_orchestrator.lifespan import get_redis_coordinator as _get_rc

                _coord = _get_rc()
                if _coord:
                    await _best_effort_redis("remove_task_sandbox", _coord.remove_task_sandbox(task_id))
                return (False, False, False, False)
            if deadline_fut in done and not requires_action_pending:
                _log_grpc_boundary_failure(
                    code="GRPC_TASK_DEADLINE_EXCEEDED",
                    message="Task deadline exceeded",
                    operation="task_deadline_exceeded",
                    data={"task_id": str(task_id), "sandbox_id": str(sandbox_id), "timeout_sec": timeout},
                )
                cancel_msg = joysafeter_pb2.OrchestratorMessage(
                    cancel=joysafeter_pb2.CancelTask(reason=f"Server-side deadline exceeded ({timeout}s)")
                )
                await bridge.write_to_runner(cancel_msg)
                async with AsyncSessionLocal() as db:
                    task_svc = TaskService(db)
                    timeout_ok = await task_svc.update_task_error(
                        task_id,
                        f"Task timed out after {timeout}s (server-side deadline)",
                        TaskStatus.TIMEOUT,
                        expected_epoch=bridge.current_owner_epoch,
                    )
                if not timeout_ok:
                    _log_grpc_boundary_failure(
                        code="GRPC_TASK_TIMEOUT_CAS_CONFLICT",
                        message="CAS conflict timing out task; ignoring stale deadline",
                        operation="timeout_task",
                        data={
                            "task_id": str(task_id),
                            "sandbox_id": str(sandbox_id),
                            "owner_epoch": bridge.current_owner_epoch,
                        },
                        retryable=False,
                        user_action=None,
                    )
                    return (False, False, False, False)
                if session_id:
                    if self._event_bus:
                        await self._event_bus.publish(
                            JoySafeterEventEnvelope(
                                session_id=session_id,
                                event_type="session.status_idle",
                                payload={"task_id": str(task_id), "stop_reason": {"type": "timeout"}},
                                is_status_change=True,
                                stop_reason={"type": "timeout"},
                                task_id=task_id,
                                sandbox_id=sandbox_id,
                            )
                        )
                    else:
                        async with AsyncSessionLocal() as db:
                            session_svc = SessionService(db)
                            await session_svc.update_session_status_for_task_event(
                                session_id,
                                SessionStatus.IDLE.value,
                                task_id,
                                stop_reason={"type": "timeout"},
                            )
                            await session_svc.send_event(
                                session_id,
                                "session.status_idle",
                                {"task_id": str(task_id), "stop_reason": {"type": "timeout"}},
                            )
                        broadcaster = get_session_broadcaster()
                        if broadcaster:
                            await broadcaster.send(
                                session_id,
                                {
                                    "type": "session.status_idle",
                                    "task_id": str(task_id),
                                    "stop_reason": {"type": "timeout"},
                                },
                            )
                task_done = True
                deadline_exceeded = True
                break

            # --- Stream message ---
            if read_fut not in done:
                continue
            msg = read_fut.result()
            if msg == grpc_aio.EOF:
                logger.warning(
                    "EOF received in task event loop: task=%s task_done=%s got_idle=%s", task_id, task_done, got_idle
                )
                break

            # Reset heartbeat deadline on ANY received message (Rust line 983)
            heartbeat_deadline = _time.monotonic() + _get_heartbeat_timeout()

            payload_type = msg.WhichOneof("payload")
            if payload_type is None:
                continue

            if payload_type == "heartbeat":
                continue
            elif payload_type == "event":
                event = msg.event
                raw_event = _proto_event_to_dict(event)
                mapped_list = map_harness_event(raw_event, custom_names, mcp_names)

                for mapped_type, mapped_payload in mapped_list:
                    if mapped_type == "memory_sync":
                        asyncio.create_task(_handle_memory_sync_standalone(session_id, mapped_payload))
                        continue

                    # I5 fix: map_harness_event returns "session.error", not "error"
                    if mapped_type == "session.error":
                        err_detail = mapped_payload.get("error", {})
                        bridge.last_error = (
                            err_detail.get("message") if isinstance(err_detail, dict) else str(err_detail)
                        )

                    if requires_action_pending:
                        if len(buffered_events) < 1000:
                            buffered_events.append((mapped_type, mapped_payload))
                        continue

                    if mapped_type in ("agent.tool_use", "agent.mcp_tool_use") and is_control_request(mapped_payload):
                        call_id = (
                            mapped_payload.get("_call_id")
                            or mapped_payload.get("request_id")
                            or mapped_payload.get("id")
                            or mapped_payload.get("call_id")
                            or ""
                        )

                        # Persist the tool_use event to DB first so event_id is stable
                        persisted_event_id = uuid.UUID(str(uuid7())) if session_id else None

                        if self._event_bus and session_id:
                            await self._event_bus.publish(
                                JoySafeterEventEnvelope(
                                    session_id=session_id,
                                    event_type=mapped_type,
                                    payload=mapped_payload,
                                    task_id=task_id,
                                    sandbox_id=sandbox_id,
                                    event_id=persisted_event_id,
                                    seq=event.seq,
                                    flush_immediately=True,
                                    task_broadcast_payload={"type": mapped_type, **mapped_payload},
                                )
                            )
                        else:
                            ws_msg = WsOutMessage(
                                type="event",
                                payload={"type": mapped_type, **mapped_payload},
                            )
                            await bridge.broadcast_to_task(task_id, ws_msg)

                            coordinator = get_redis_coordinator()
                            await _best_effort_publish_event(
                                coordinator,
                                task_id,
                                json.dumps({"type": ws_msg.type, **ws_msg.payload}),
                            )

                            if session_id:
                                buffered = BufferedEvent(
                                    session_id=session_id,
                                    event_type=mapped_type,
                                    payload=mapped_payload,
                                    seq=event.seq,
                                    id=persisted_event_id,
                                )
                                await self._event_buffer.send(buffered)
                                await self._event_buffer.flush()

                                broadcaster = get_session_broadcaster()
                                if broadcaster:
                                    await broadcaster.send(
                                        session_id,
                                        {
                                            **{"type": mapped_type, "seq": event.seq},
                                            **(mapped_payload if isinstance(mapped_payload, dict) else {}),
                                        },
                                    )

                        if session_id and persisted_event_id:
                            event_id = f"evt_{persisted_event_id}"
                            last_tool_use_event_id = event_id
                        else:
                            event_id = f"evt_{uuid7()}"

                        if call_id:
                            bridge.pending_control_request_ids[event_id] = call_id
                        else:
                            logger.warning("HITL-GRPC control_request: NO call_id found in payload: %s", mapped_payload)
                        requires_action_pending = True
                        bridge._requires_action_pending = True
                        if session_id:
                            stop_reason = {"type": "requires_action", "event_ids": [event_id]}
                            if self._event_bus:
                                await self._event_bus.publish(
                                    JoySafeterEventEnvelope(
                                        session_id=session_id,
                                        event_type="session.status_idle",
                                        payload={"task_id": str(task_id), "stop_reason": stop_reason},
                                        is_status_change=True,
                                        stop_reason=stop_reason,
                                        task_id=task_id,
                                        sandbox_id=sandbox_id,
                                    )
                                )
                            else:
                                async with AsyncSessionLocal() as db:
                                    session_svc = SessionService(db)
                                    await session_svc.update_session_status_for_task_event(
                                        session_id,
                                        SessionStatus.IDLE.value,
                                        task_id,
                                        stop_reason=stop_reason,
                                    )
                                    await session_svc.send_event(
                                        session_id,
                                        "session.status_idle",
                                        {"task_id": str(task_id), "stop_reason": stop_reason},
                                    )
                                broadcaster = get_session_broadcaster()
                                if broadcaster:
                                    await broadcaster.send(
                                        session_id,
                                        {
                                            "type": "session.status_idle",
                                            "task_id": str(task_id),
                                            "stop_reason": stop_reason,
                                        },
                                    )
                        continue

                    persisted_event_id = uuid.UUID(str(uuid7())) if session_id else None

                    # Background sub-agent activity no longer touches
                    # last_used_at — idle_since (set by RunnerIdle) is the
                    # authoritative idle anchor now, and RunnerIdle is held
                    # back by the runtime until all background agents finish
                    # (cc: heldBackResult; codex multi-agent: aggregated child
                    # threads), so a sandbox can't be reaped mid-activity.

                    if mapped_type in ("session.status_running", "session.status_idle") and session_id:
                        await self._emit_task_scoped_status_event(
                            session_id=session_id,
                            task_id=task_id,
                            mapped_type=mapped_type,
                            mapped_payload=mapped_payload,
                            sandbox_id=sandbox_id,
                            seq=event.seq,
                            bridge=bridge,
                        )
                        continue

                    if self._event_bus and session_id:
                        await self._event_bus.publish(
                            JoySafeterEventEnvelope(
                                session_id=session_id,
                                event_type=mapped_type,
                                payload=mapped_payload,
                                task_id=task_id,
                                sandbox_id=sandbox_id,
                                event_id=persisted_event_id,
                                seq=event.seq,
                                task_broadcast_payload={"type": mapped_type, **mapped_payload},
                            )
                        )
                    else:
                        ws_msg = WsOutMessage(
                            type="event",
                            payload={"type": mapped_type, **mapped_payload},
                        )
                        await bridge.broadcast_to_task(task_id, ws_msg)

                        coordinator = get_redis_coordinator()
                        await _best_effort_publish_event(
                            coordinator,
                            task_id,
                            json.dumps({"type": ws_msg.type, **ws_msg.payload}),
                        )

                        if session_id:
                            buffered = BufferedEvent(
                                session_id=session_id,
                                event_type=mapped_type,
                                payload=mapped_payload,
                                seq=event.seq,
                                id=persisted_event_id,
                            )
                            await self._event_buffer.send(buffered)

                            broadcaster = get_session_broadcaster()
                            if broadcaster:
                                await broadcaster.send(
                                    session_id,
                                    {
                                        **{"type": mapped_type, "seq": event.seq},
                                        **(mapped_payload if isinstance(mapped_payload, dict) else {}),
                                    },
                                )

                    if session_id and persisted_event_id:
                        if mapped_type in ("agent.tool_use", "agent.mcp_tool_use", "agent.custom_tool_use"):
                            last_tool_use_event_id = f"evt_{persisted_event_id}"

                    is_custom_tool = mapped_type == "agent.custom_tool_use"
                    if is_custom_tool and not requires_action_pending:
                        call_id = (
                            mapped_payload.get("_call_id")
                            or mapped_payload.get("request_id")
                            or mapped_payload.get("id")
                            or mapped_payload.get("call_id")
                            or ""
                        )
                        event_id = last_tool_use_event_id or f"evt_{uuid7()}"
                        if call_id:
                            bridge.pending_control_request_ids[event_id] = call_id
                        requires_action_pending = True
                        bridge._requires_action_pending = True
                        if session_id:
                            await self._event_buffer.flush()
                            stop_reason = {"type": "requires_action", "event_ids": [event_id]}
                            if self._event_bus:
                                await self._event_bus.publish(
                                    JoySafeterEventEnvelope(
                                        session_id=session_id,
                                        event_type="session.status_idle",
                                        payload={"task_id": str(task_id), "stop_reason": stop_reason},
                                        is_status_change=True,
                                        stop_reason=stop_reason,
                                        task_id=task_id,
                                        sandbox_id=sandbox_id,
                                    )
                                )
                            else:
                                async with AsyncSessionLocal() as db:
                                    session_svc = SessionService(db)
                                    await session_svc.update_session_status_for_task_event(
                                        session_id,
                                        SessionStatus.IDLE.value,
                                        task_id,
                                        stop_reason=stop_reason,
                                    )
                                    await session_svc.send_event(
                                        session_id,
                                        "session.status_idle",
                                        {"task_id": str(task_id), "stop_reason": stop_reason},
                                    )
                                broadcaster = get_session_broadcaster()
                                if broadcaster:
                                    await broadcaster.send(
                                        session_id,
                                        {
                                            "type": "session.status_idle",
                                            "task_id": str(task_id),
                                            "stop_reason": stop_reason,
                                        },
                                    )

            elif payload_type == "result":
                result = msg.result
                logger.info("Result received: task=%s status=%s got_idle=%s", task_id, result.status, got_idle)
                result_accepted = await self._handle_result(bridge, sandbox_id, task_id, session_id, result)
                if not result_accepted:
                    _log_grpc_boundary_failure(
                        code="GRPC_STALE_RESULT_IGNORED",
                        message="Ignoring stale task result",
                        operation="handle_task_result",
                        data={"task_id": str(task_id), "sandbox_id": str(sandbox_id)},
                        retryable=False,
                        user_action=None,
                    )
                    return (False, False, False, False)
                result_status = bridge.last_result_status or TaskStatus.from_str_lossy(result.status)
                if result_status == TaskStatus.COMPLETED:
                    task_completed = True
                elif result_status in (TaskStatus.FAILED, TaskStatus.ABORTED, TaskStatus.TIMEOUT):
                    task_error_status = True
                task_done = True
                logger.info("Result processed: task=%s task_done=%s got_idle=%s", task_id, task_done, got_idle)

                # I2 fix: publish Redis "complete" event (Rust parity: server.rs lines 551-557)
                if coordinator:
                    import json as _json

                    await _best_effort_redis(
                        "publish_task_complete",
                        coordinator.publish_event(
                            task_id,
                            _json.dumps({"type": "complete", "task_id": str(task_id)}),
                        ),
                    )

            elif payload_type == "idle":
                if not task_done:
                    _log_grpc_boundary_failure(
                        code="GRPC_RUNNER_IDLE_BEFORE_RESULT",
                        message="Runner idle before result",
                        operation="run_task",
                        data={"task_id": str(task_id), "sandbox_id": str(sandbox_id)},
                        retryable=True,
                        user_action="retry",
                    )
                    break
                idle = msg.idle
                bridge.status = SandboxBridgeStatus.IDLE
                bridge.current_task_id = None
                logger.info("Runner idle received: sandbox=%s task_done=%s", sandbox_id, task_done)

                # Fix 4: Update sandbox DB status to idle + touch (Rust lines 1271-1274)
                async with AsyncSessionLocal() as db:
                    sandbox_svc = SandboxService(db)
                    await sandbox_svc.update_status(sandbox_id, "idle")
                    await sandbox_svc.touch(sandbox_id)

                    if linked_session_id:
                        harness_session_id = idle.session_id if idle.HasField("session_id") else None
                        work_dir = idle.work_dir if idle.HasField("work_dir") else None
                        session_svc = SessionService(db)
                        await session_svc.update_session_sandbox(
                            linked_session_id,
                            sandbox_id,
                            harness_session_id=harness_session_id,
                            work_dir=work_dir,
                        )

                from app.joysafeter_orchestrator.lifespan import get_redis_coordinator as _get_rc

                coord = _get_rc()
                if coord:
                    await _best_effort_redis("refresh_sandbox_owner", coord.refresh_sandbox_owner(sandbox_id))

                # Flush buffered events BEFORE setting session idle (Rust lines 1226-1230)
                # This ensures all agent events are in PG when clients see session.status_idle
                await self._event_buffer.flush()

                if session_id and not bridge._requires_action_pending:
                    final_status = bridge.last_result_status
                    last_error = bridge.last_result_error
                    stop_reason = (
                        self._stop_reason_from_result(final_status, last_error)
                        if final_status
                        else {"type": "end_turn"}
                    )
                    if self._event_bus:
                        await self._event_bus.publish(
                            JoySafeterEventEnvelope(
                                session_id=session_id,
                                event_type="session.status_idle",
                                payload={"task_id": str(task_id), "stop_reason": stop_reason},
                                is_status_change=True,
                                stop_reason=stop_reason,
                                task_id=task_id,
                                sandbox_id=sandbox_id,
                            )
                        )
                    else:
                        async with AsyncSessionLocal() as db:
                            session_svc = SessionService(db)
                            await session_svc.update_session_status_for_task_event(
                                session_id,
                                SessionStatus.IDLE.value,
                                task_id,
                                stop_reason=stop_reason,
                            )
                            await session_svc.send_event(
                                session_id,
                                "session.status_idle",
                                {"task_id": str(task_id), "stop_reason": stop_reason},
                            )
                        broadcaster = get_session_broadcaster()
                        if broadcaster:
                            await broadcaster.send(
                                session_id,
                                {
                                    "type": "session.status_idle",
                                    "task_id": str(task_id),
                                    "stop_reason": stop_reason,
                                },
                            )

                got_idle = True

            elif payload_type == "memory_sync":
                ms = msg.memory_sync
                asyncio.create_task(
                    _handle_memory_sync_standalone(
                        session_id,
                        {
                            "store_mount_name": ms.store_mount_name,
                            "relative_path": ms.relative_path,
                            "content": ms.content,
                            "operation": ms.operation,
                        },
                    )
                )

            if task_done:
                break

        # --- Post-task ---
        # I3 fix: unconditionally reset HITL state after each task (Rust parity: server.rs lines 541-543)
        bridge._requires_action_pending = False
        bridge.confirmation_event.clear()

        logger.info(
            "Post-task: task=%s task_done=%s got_idle=%s deadline=%s error=%s completed=%s",
            task_id,
            task_done,
            got_idle,
            deadline_exceeded,
            task_error_status,
            task_completed,
        )
        if not task_done:
            await self._event_buffer.flush()
            last_err = bridge.last_error
            if last_err:
                reason = f"Sandbox disconnected unexpectedly (last error: {last_err})"
            else:
                reason = "Sandbox disconnected unexpectedly"
            retry_count = await TaskController.failover_or_fail_task(
                task_id,
                reason,
                expected_epoch=bridge.current_owner_epoch,
            )
            if retry_count is not None:
                failover_pending_tasks.append((task_id, retry_count))
            bridge.remove_task_subscribers(task_id)
            from app.joysafeter_orchestrator.lifespan import get_redis_coordinator as _get_rc2

            _coord2 = _get_rc2()
            if _coord2:
                await _best_effort_redis("remove_task_sandbox", _coord2.remove_task_sandbox(task_id))
            return (False, deadline_exceeded, False, False)

        if task_done and not got_idle:
            bridge.status = SandboxBridgeStatus.IDLE
            bridge.current_task_id = None
            bridge.remove_task_subscribers(task_id)
            await self._event_buffer.flush()
            if self._event_bus:
                await self._event_bus.flush()
            from app.joysafeter_orchestrator.lifespan import get_redis_coordinator

            coordinator = get_redis_coordinator()
            if coordinator:
                await _best_effort_redis("remove_task_sandbox", coordinator.remove_task_sandbox(task_id))
            if linked_session_id:
                stop_reason = {"type": "end_turn"}
                if deadline_exceeded:
                    stop_reason = {"type": "timeout"}
                elif task_error_status:
                    stop_reason = _task_error_stop_reason(
                        code="TASK_FAILED",
                        message="Task failed",
                        task_id=task_id,
                        session_id=linked_session_id,
                        sandbox_id=sandbox_id,
                    )
                if self._event_bus:
                    await self._event_bus.publish(
                        JoySafeterEventEnvelope(
                            session_id=linked_session_id,
                            event_type="session.status_idle",
                            payload={"task_id": str(task_id), "stop_reason": stop_reason},
                            is_status_change=True,
                            stop_reason=stop_reason,
                            task_id=task_id,
                            sandbox_id=sandbox_id,
                        )
                    )
                else:
                    async with AsyncSessionLocal() as db:
                        session_svc = SessionService(db)
                        cas_ok = await session_svc.update_session_status_for_task_event(
                            linked_session_id,
                            SessionStatus.IDLE.value,
                            task_id,
                            stop_reason=stop_reason,
                        )
                        if cas_ok:
                            await session_svc.send_event(
                                linked_session_id,
                                "session.status_idle",
                                {"task_id": str(task_id), "stop_reason": stop_reason},
                            )
                            broadcaster = get_session_broadcaster()
                            if broadcaster:
                                await broadcaster.send(
                                    linked_session_id,
                                    {
                                        "type": "session.status_idle",
                                        "task_id": str(task_id),
                                        "stop_reason": stop_reason,
                                    },
                                )
            return (False, deadline_exceeded, task_error_status, task_completed)

        return (True, deadline_exceeded, task_error_status, task_completed)

    async def _handle_result(
        self,
        bridge: SandboxBridge,
        sandbox_id: uuid.UUID,
        task_id: uuid.UUID,
        session_id: Optional[uuid.UUID],
        result: joysafeter_pb2.RunnerHarnessResult,
    ) -> bool:
        from app.joysafeter_domain.models.joysafeter_session import SessionStatus
        from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from app.joysafeter_orchestrator.services import SessionService, TaskService
        from app.joysafeter_shared.database import AsyncSessionLocal

        usage = None
        if result.usage:
            usage = {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "cache_read_tokens": result.usage.cache_read_tokens,
                "cache_write_tokens": result.usage.cache_write_tokens,
            }

        error = result.error if result.HasField("error") else None
        final_status = TaskStatus.from_str_lossy(result.status)
        if not final_status.is_terminal():
            error = error or f"Runner returned non-terminal result status: {result.status}"
            final_status = TaskStatus.FAILED

        cas_ok = True
        async with AsyncSessionLocal() as db:
            task_svc = TaskService(db)
            cas_ok = await task_svc.update_task_output(
                task_id, result.output, expected_epoch=bridge.current_owner_epoch
            )
            if not cas_ok:
                _log_grpc_boundary_failure(
                    code="GRPC_RESULT_OUTPUT_CAS_CONFLICT",
                    message="CAS conflict writing output; ignoring runner result",
                    operation="persist_task_result_output",
                    data={
                        "task_id": str(task_id),
                        "sandbox_id": str(sandbox_id),
                        "owner_epoch": bridge.current_owner_epoch,
                    },
                    retryable=False,
                    user_action=None,
                )
                return False
            if usage:
                cas_ok = await task_svc.update_task_usage(task_id, usage, expected_epoch=bridge.current_owner_epoch)
                if not cas_ok:
                    _log_grpc_boundary_failure(
                        code="GRPC_RESULT_USAGE_CAS_CONFLICT",
                        message="CAS conflict writing usage; ignoring runner result",
                        operation="persist_task_result_usage",
                        data={
                            "task_id": str(task_id),
                            "sandbox_id": str(sandbox_id),
                            "owner_epoch": bridge.current_owner_epoch,
                        },
                        retryable=False,
                        user_action=None,
                    )
                    return False
            if session_id:
                await SessionService(db).repair_missing_agent_message(session_id, task_id, result.output)
            if final_status.is_terminal():
                if error:
                    cas_ok = await task_svc.update_task_error(
                        task_id,
                        error,
                        final_status,
                        expected_epoch=bridge.current_owner_epoch,
                    )
                else:
                    cas_ok = await task_svc.update_task_status(
                        task_id,
                        final_status,
                        expected_epoch=bridge.current_owner_epoch,
                    )
                if not cas_ok:
                    _log_grpc_boundary_failure(
                        code="GRPC_RESULT_TERMINAL_CAS_CONFLICT",
                        message="CAS conflict finalizing task; ignoring runner result",
                        operation="finalize_task_result",
                        data={
                            "task_id": str(task_id),
                            "sandbox_id": str(sandbox_id),
                            "owner_epoch": bridge.current_owner_epoch,
                            "final_status": final_status.value,
                        },
                        retryable=False,
                        user_action=None,
                    )
                    return False

            sandbox_svc = SandboxService(db)
            await sandbox_svc.complete_task(sandbox_id, task_id, "idle")

            if session_id and usage:
                session_svc = SessionService(db)
                await session_svc.accumulate_usage(
                    session_id,
                    {
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "cache_creation_input_tokens": usage.get("cache_write_tokens", 0),
                        "cache_read_input_tokens": usage.get("cache_read_tokens", 0),
                    },
                )

        from app.joysafeter_orchestrator.lifespan import get_redis_coordinator, get_session_broadcaster

        result_payload = {
            "status": final_status.value,
            "output": result.output,
            "error": error,
            "duration_ms": result.duration_ms,
        }
        await bridge.broadcast_to_task(task_id, WsOutMessage(type="complete", payload=result_payload))

        # Issue 4 fix: publish complete event to Redis (matching Rust lines 1197-1199)
        coordinator = get_redis_coordinator()
        await _best_effort_publish_event(
            coordinator,
            task_id,
            json.dumps({"type": "complete", **result_payload}),
        )

        bridge.remove_task_subscribers(task_id)

        if coordinator:
            await _best_effort_redis("remove_task_sandbox", coordinator.remove_task_sandbox(task_id))

        # Agentd pattern: update session to idle DIRECTLY in Result handler.
        # Don't wait for Idle message or post-loop fallback.
        if session_id:
            stop_reason = (
                _task_error_stop_reason(
                    code="TASK_RESULT_FAILED",
                    message=str(error),
                    task_id=task_id,
                    session_id=session_id,
                    sandbox_id=sandbox_id,
                )
                if error
                else {"type": "end_turn"}
            )
            idle_updated = False
            async with AsyncSessionLocal() as idle_db:
                session_svc = SessionService(idle_db)
                idle_updated = await session_svc.update_session_status_for_task_event(
                    session_id,
                    SessionStatus.IDLE.value,
                    task_id,
                    stop_reason,
                )
                if idle_updated:
                    await session_svc.send_event(
                        session_id, "session.status_idle", {"task_id": str(task_id), "stop_reason": stop_reason}
                    )
            broadcaster = get_session_broadcaster()
            if broadcaster and idle_updated:
                await broadcaster.send(
                    session_id,
                    {
                        "type": "session.status_idle",
                        "session_id": str(session_id),
                        "task_id": str(task_id),
                        "stop_reason": stop_reason,
                    },
                )

        # Store result info so the idle handler can compute stop_reason
        bridge.last_result_status = final_status
        bridge.last_result_error = error

        logger.info("Task %s completed: status=%s", task_id, result.status)
        return True

    async def _emit_task_scoped_status_event(
        self,
        *,
        session_id: uuid.UUID,
        task_id: uuid.UUID,
        mapped_type: str,
        mapped_payload: Any,
        sandbox_id: uuid.UUID,
        seq: Any,
        bridge: "SandboxBridge",
    ) -> None:
        """Persist and fan out a task-scoped session.status_running/idle event.

        Single source of truth for the two identical status-emit blocks in the
        resumed-task and main streaming loops: publish via the event bus when it
        is present, otherwise write the task-scoped transition + event directly
        and fan out to the task's WS subscribers, cross-instance Redis, and SSE.
        """
        from app.joysafeter_domain.models.joysafeter_session import SessionStatus
        from app.joysafeter_orchestrator.lifespan import get_redis_coordinator, get_session_broadcaster
        from app.joysafeter_orchestrator.services import SessionService
        from app.joysafeter_shared.database import AsyncSessionLocal

        status = SessionStatus.RUNNING.value if mapped_type == "session.status_running" else SessionStatus.IDLE.value
        stop_reason = mapped_payload.get("stop_reason") if isinstance(mapped_payload, dict) else None
        status_payload = dict(mapped_payload or {})
        status_payload["task_id"] = str(task_id)
        task_payload = {"type": mapped_type, **status_payload}

        if self._event_bus:
            await self._event_bus.publish(
                JoySafeterEventEnvelope(
                    session_id=session_id,
                    event_type=mapped_type,
                    payload=status_payload,
                    task_id=task_id,
                    sandbox_id=sandbox_id,
                    seq=seq,
                    is_status_change=True,
                    stop_reason=stop_reason,
                    task_broadcast_payload=task_payload,
                )
            )
            return

        async with AsyncSessionLocal() as db:
            svc = SessionService(db)
            accepted = await svc.update_session_status_for_task_event(
                session_id, status, task_id, stop_reason=stop_reason
            )
            persisted_event = await svc.send_event(session_id, mapped_type, status_payload) if accepted else None
        if persisted_event is None:
            return

        ws_msg = WsOutMessage(type="event", payload=task_payload)
        await bridge.broadcast_to_task(task_id, ws_msg)
        await _best_effort_publish_event(
            get_redis_coordinator(),
            task_id,
            json.dumps({"type": ws_msg.type, **ws_msg.payload}),
        )
        broadcaster = get_session_broadcaster()
        if broadcaster:
            await broadcaster.send(
                session_id,
                {
                    "id": f"evt_{persisted_event.id}",
                    "type": persisted_event.event_type,
                    "seq": persisted_event.seq,
                    **(persisted_event.payload or {}),
                },
            )

    @staticmethod
    def _stop_reason_from_result(status: "TaskStatus", error: Optional[str]) -> dict:
        from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus

        if status == TaskStatus.COMPLETED:
            return {"type": "end_turn"}
        elif status == TaskStatus.TIMEOUT:
            return {"type": "timeout"}
        elif status == TaskStatus.CANCELLED:
            return {"type": "cancelled"}
        elif status in (TaskStatus.FAILED, TaskStatus.ABORTED):
            return _task_error_stop_reason(
                code="TASK_FAILED",
                message=error or "Task failed",
            )
        return {"type": "end_turn"}

    async def _handle_reconnect_result(
        self,
        bridge: SandboxBridge,
        sandbox_id: uuid.UUID,
        task_id: uuid.UUID,
        session_id: Optional[uuid.UUID],
        result,
        coordinator,
    ) -> bool:
        """Reconnect result handler — with CAS check and event buffer flush."""
        from app.joysafeter_domain.models.joysafeter_session import SessionStatus
        from app.joysafeter_domain.models.joysafeter_task import JoySafeterTaskStatus as TaskStatus
        from app.joysafeter_orchestrator.lifespan import get_session_broadcaster
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from app.joysafeter_orchestrator.services import SessionService, TaskService
        from app.joysafeter_shared.database import AsyncSessionLocal

        usage = None
        if result.usage:
            usage = {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "cache_read_tokens": result.usage.cache_read_tokens,
                "cache_write_tokens": result.usage.cache_write_tokens,
            }

        error = result.error if result.HasField("error") else None
        final_status = TaskStatus.from_str_lossy(result.status)
        if not final_status.is_terminal():
            error = error or f"Runner returned non-terminal result status: {result.status}"
            final_status = TaskStatus.FAILED

        cas_ok = True
        async with AsyncSessionLocal() as db:
            task_svc = TaskService(db)
            cas_ok = await task_svc.update_task_output(
                task_id, result.output, expected_epoch=bridge.current_owner_epoch
            )
            if not cas_ok:
                _log_grpc_boundary_failure(
                    code="GRPC_RECONNECT_RESULT_OUTPUT_CAS_CONFLICT",
                    message="CAS conflict writing reconnect output; ignoring result",
                    operation="persist_reconnect_result_output",
                    data={
                        "task_id": str(task_id),
                        "sandbox_id": str(sandbox_id),
                        "owner_epoch": bridge.current_owner_epoch,
                    },
                    retryable=False,
                    user_action=None,
                )
                return False
            if usage:
                cas_ok = await task_svc.update_task_usage(task_id, usage, expected_epoch=bridge.current_owner_epoch)
                if not cas_ok:
                    _log_grpc_boundary_failure(
                        code="GRPC_RECONNECT_RESULT_USAGE_CAS_CONFLICT",
                        message="CAS conflict writing reconnect usage; ignoring result",
                        operation="persist_reconnect_result_usage",
                        data={
                            "task_id": str(task_id),
                            "sandbox_id": str(sandbox_id),
                            "owner_epoch": bridge.current_owner_epoch,
                        },
                        retryable=False,
                        user_action=None,
                    )
                    return False
            if session_id:
                await SessionService(db).repair_missing_agent_message(session_id, task_id, result.output)
            if final_status.is_terminal():
                if error:
                    cas_ok = await task_svc.update_task_error(
                        task_id, error, final_status, expected_epoch=bridge.current_owner_epoch
                    )
                else:
                    cas_ok = await task_svc.update_task_status(
                        task_id, final_status, expected_epoch=bridge.current_owner_epoch
                    )
                if not cas_ok:
                    _log_grpc_boundary_failure(
                        code="GRPC_RECONNECT_RESULT_TERMINAL_CAS_CONFLICT",
                        message="CAS conflict finalizing reconnect task; ignoring result",
                        operation="finalize_reconnect_result",
                        data={
                            "task_id": str(task_id),
                            "sandbox_id": str(sandbox_id),
                            "owner_epoch": bridge.current_owner_epoch,
                            "final_status": final_status.value,
                        },
                        retryable=False,
                        user_action=None,
                    )
                    return False

        result_payload = {
            "status": final_status.value,
            "output": result.output,
            "error": error,
            "duration_ms": result.duration_ms,
        }
        await bridge.broadcast_to_task(task_id, WsOutMessage(type="complete", payload=result_payload))

        await _best_effort_publish_event(
            coordinator,
            task_id,
            json.dumps({"type": "complete", **result_payload}),
        )

        async with AsyncSessionLocal() as db:
            sandbox_svc = SandboxService(db)
            await sandbox_svc.complete_task(sandbox_id, task_id, "idle")

        bridge.remove_task_subscribers(task_id)

        if coordinator:
            await _best_effort_redis("remove_task_sandbox", coordinator.remove_task_sandbox(task_id))

        await self._event_buffer.flush()

        if session_id:
            if not bridge._requires_action_pending:
                stop_reason = self._stop_reason_from_result(final_status, error)
                if self._event_bus:
                    await self._event_bus.publish(
                        JoySafeterEventEnvelope(
                            session_id=session_id,
                            event_type="session.status_idle",
                            payload={"task_id": str(task_id), "stop_reason": stop_reason},
                            is_status_change=True,
                            stop_reason=stop_reason,
                            task_id=task_id,
                            sandbox_id=sandbox_id,
                        )
                    )
                else:
                    async with AsyncSessionLocal() as db:
                        session_svc = SessionService(db)
                        idle_updated = await session_svc.update_session_status_for_task_event(
                            session_id,
                            SessionStatus.IDLE.value,
                            task_id,
                            stop_reason=stop_reason,
                        )
                        if idle_updated:
                            await session_svc.send_event(
                                session_id,
                                "session.status_idle",
                                {"task_id": str(task_id), "stop_reason": stop_reason},
                            )
                    broadcaster = get_session_broadcaster()
                    if broadcaster and idle_updated:
                        await broadcaster.send(
                            session_id,
                            {"type": "session.status_idle", "task_id": str(task_id), "stop_reason": stop_reason},
                        )

            if usage:
                async with AsyncSessionLocal() as db:
                    session_svc = SessionService(db)
                    await session_svc.accumulate_usage(
                        session_id,
                        {
                            "input_tokens": usage.get("input_tokens", 0),
                            "output_tokens": usage.get("output_tokens", 0),
                            "cache_creation_input_tokens": usage.get("cache_write_tokens", 0),
                            "cache_read_input_tokens": usage.get("cache_read_tokens", 0),
                        },
                    )

        bridge.last_result_status = final_status
        bridge.last_result_error = error

        logger.info("Reconnect task %s completed: status=%s", task_id, final_status.value)
        return True

    async def _send_setup(self, bridge: SandboxBridge, sandbox_id: uuid.UUID) -> None:
        if bridge.setup_done:
            return

        from app.joysafeter_orchestrator.services import AgentService, SessionService
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from app.joysafeter_shared.database import AsyncSessionLocal

        try:
            async with AsyncSessionLocal() as db:
                sandbox_svc = SandboxService(db)
                sandbox = await sandbox_svc.get_sandbox(sandbox_id)
                if not sandbox or not sandbox.chat_session_id:
                    bridge.setup_done = True
                    return

                session_svc = SessionService(db)
                session = await session_svc.get_session(sandbox.chat_session_id)
                if not session:
                    bridge.setup_done = True
                    return

                agent_svc = AgentService(db)
                agent = await agent_svc.get_agent(session.agent_id, project_id=getattr(session, "project_id", None))
                if not agent:
                    bridge.setup_done = True
                    return

                from app.joysafeter_orchestrator.kernel.harness_input_builder import build_harness_input

                agent_system_prompt = agent.system_prompt

                class _FakeTask:
                    prompt = ""
                    system_prompt = agent_system_prompt

                harness_input = await build_harness_input(
                    _FakeTask(),
                    agent,
                    sandbox.chat_session_id,
                    bridge.external_id,
                    sandbox_id,
                )

                environment = None
                env_ref = getattr(agent, "environment_ref", None)
                if env_ref:
                    from app.joysafeter_orchestrator.services import EnvironmentService

                    env_svc = EnvironmentService(db)
                    environment = await env_svc.get_environment_by_ref(
                        env_ref, project_id=getattr(agent, "project_id", None)
                    )

                # workspace_path on the record is the HOST path; inside the container it's always /workspace
                work_dir = session.last_work_dir or ("/workspace" if getattr(sandbox, "workspace_path", None) else None)

            setup_msg = _build_setup_sandbox(harness_input, agent, environment, work_dir=work_dir)
            orch_msg = joysafeter_pb2.OrchestratorMessage(setup=setup_msg)
            if bridge.runner_stream is None:
                _log_grpc_boundary_failure(
                    code="GRPC_SETUP_SANDBOX_STREAM_MISSING",
                    message="Cannot send SetupSandbox because runner stream is not connected",
                    operation="send_setup_sandbox",
                    data={"sandbox_id": str(sandbox_id)},
                )
                return
            await bridge.write_to_runner(orch_msg)
            bridge.setup_done = True
            logger.info("SetupSandbox sent for sandbox %s", sandbox_id)

        except Exception as e:
            _log_grpc_boundary_failure(
                code="GRPC_SETUP_SANDBOX_SEND_FAILED",
                message="Failed to send SetupSandbox",
                operation="send_setup_sandbox",
                error=e,
                data={"sandbox_id": str(sandbox_id)},
            )
            bridge.setup_done = True

    # --- Fix 2: Full execute_sandbox_cleanup matching Rust lines 46-127 + grace period ---

    async def _cleanup_sandbox(
        self,
        sandbox_id: uuid.UUID,
        session_id: Optional[uuid.UUID] = None,
        failover_pending_tasks: Optional[list] = None,
        is_error: bool = False,
        external_id: Optional[str] = None,
    ) -> None:
        """Post-disconnect cleanup: probe container, then either fast-cleanup or start 120s grace period."""
        from app.joysafeter_orchestrator.lifespan import get_sandbox_provider

        if failover_pending_tasks is None:
            failover_pending_tasks = []

        provider = get_sandbox_provider()
        if not provider:
            await self._execute_sandbox_cleanup(sandbox_id, session_id, failover_pending_tasks, is_error)
            return

        # Fast path: probe container status -- if confirmed dead, skip 120s wait
        await asyncio.sleep(3)
        container_dead = await self._probe_container(provider, sandbox_id, external_id=external_id)
        if container_dead:
            logger.info("Container confirmed dead for sandbox %s, fast recovery", sandbox_id)
            await self._execute_sandbox_cleanup(
                sandbox_id, session_id, failover_pending_tasks, is_error, container_dead=True
            )
            return

        # Second probe after 2s
        await asyncio.sleep(2)
        container_dead = await self._probe_container(provider, sandbox_id, external_id=external_id)
        if container_dead:
            logger.info("Container dead on retry for sandbox %s", sandbox_id)
            await self._execute_sandbox_cleanup(
                sandbox_id, session_id, failover_pending_tasks, is_error, container_dead=True
            )
            return

        # Container is alive -- start 120s reconnection grace period
        logger.info("Runner disconnected from sandbox %s, starting 120s grace period", sandbox_id)

        current_bridge = await self._bridge_registry.get(sandbox_id)

        asyncio.create_task(
            self._grace_period_cleanup(sandbox_id, session_id, failover_pending_tasks, is_error, current_bridge),
            name=f"grace-{sandbox_id}",
        )

    async def _execute_sandbox_cleanup(
        self,
        sandbox_id: uuid.UUID,
        session_id: Optional[uuid.UUID],
        failover_pending_tasks: list,
        is_error: bool,
        container_dead: bool = False,
    ) -> None:
        """Full sandbox cleanup matching Rust execute_sandbox_cleanup (lines 46-127)."""
        from app.joysafeter_orchestrator.kernel.task_controller import TaskController
        from app.joysafeter_orchestrator.lifespan import (
            get_memory_subscribers,
            get_redis_coordinator,
            get_session_broadcaster,
        )
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from app.joysafeter_orchestrator.services import SessionService
        from app.joysafeter_shared.database import AsyncSessionLocal

        sandbox_status = "error" if is_error else "stopped"

        # 1. CAS sandbox status -- skip if already terminal
        async with AsyncSessionLocal() as db:
            sandbox_svc = SandboxService(db)
            sandbox = await sandbox_svc.get_sandbox(sandbox_id)
            if sandbox:
                current = sandbox.status
                if container_dead and current != "destroyed":
                    await sandbox_svc.mark_destroyed(sandbox_id)
                elif current not in ("destroyed", "stopped", "error"):
                    await sandbox_svc.update_status_cas(sandbox_id, current, sandbox_status)

        # 2. Remove bridge from registry
        await self._bridge_registry.remove(sandbox_id)

        # 3. Fail over scheduling tasks assigned to this dead sandbox. This
        # respects max_retries and feeds the same delayed requeue path as
        # running-task failover.
        async with AsyncSessionLocal() as db:
            from sqlalchemy import text

            rows = (
                await db.execute(
                    text("SELECT id FROM joysafeter_tasks WHERE sandbox_id = :sandbox_id AND status = 'scheduling'"),
                    {"sandbox_id": sandbox_id},
                )
            ).all()
        for row in rows:
            tid = row[0]
            retry_count = await TaskController.failover_or_fail_task(
                tid,
                f"Sandbox {sandbox_id} cleaned up before task started",
            )
            if retry_count is not None:
                failover_pending_tasks.append((tid, retry_count))
                logger.info("Scheduling task %s failed over during sandbox cleanup", tid)
            else:
                _log_grpc_boundary_failure(
                    code="GRPC_CLEANUP_SCHEDULING_TASK_FAILOVER_SKIPPED",
                    message="Could not fail over scheduling task during sandbox cleanup",
                    operation="cleanup_sandbox_failover_scheduling_task",
                    data={"sandbox_id": str(sandbox_id), "task_id": str(tid)},
                    retryable=False,
                    user_action="refresh",
                )

        # 4. Drain and requeue sandbox queue
        await self._queue.drain_and_requeue_sandbox(sandbox_id)

        # 5. Schedule delayed retry for failover_pending_tasks
        has_retries_inmemory = len(failover_pending_tasks) > 0
        for tid, retry_count in failover_pending_tasks:
            delay = TaskController.compute_retry_delay(retry_count, tid)
            logger.info(
                "Scheduling delayed retry for task %s: retry_count=%d delay=%.1fs",
                tid,
                retry_count,
                delay,
            )

            async def _delayed_retry(_task_id, _delay_sec):
                await asyncio.sleep(_delay_sec)
                await self._queue.push_to_global(_task_id)

            asyncio.create_task(
                _delayed_retry(tid, delay),
                name=f"retry-{tid}",
            )

        # 6. Remove Redis owner and queue keys
        coordinator = get_redis_coordinator()
        if coordinator:
            await _best_effort_redis("remove_sandbox_owner", coordinator.remove_sandbox_owner(sandbox_id))
            await _best_effort_redis("remove_sandbox_queue", coordinator.remove_sandbox_queue(sandbox_id))

        # 7. Emit session status event BEFORE removing broadcaster
        # Query DB for pending tasks instead of in-memory list — matches Rust behavior
        if session_id:
            async with AsyncSessionLocal() as db:
                from sqlalchemy import text

                pending_result = await db.execute(
                    text("SELECT COUNT(*) FROM joysafeter_tasks WHERE chat_session_id = :sid AND status = 'pending'"),
                    {"sid": session_id},
                )
                pending_count = pending_result.scalar() or 0
                active_result = await db.execute(
                    text(
                        "SELECT COUNT(*) FROM joysafeter_tasks "
                        "WHERE chat_session_id = :sid AND status IN ('pending', 'scheduling', 'running')"
                    ),
                    {"sid": session_id},
                )
                active_count = active_result.scalar() or 0
            has_retries = pending_count > 0 or has_retries_inmemory
            if has_retries:
                if self._event_bus:
                    await self._event_bus.publish(
                        JoySafeterEventEnvelope(
                            session_id=session_id,
                            event_type="session.status_rescheduling",
                            payload={"stop_reason": {"type": "sandbox_failed"}},
                            is_status_change=True,
                            stop_reason={"type": "sandbox_failed"},
                            sandbox_id=sandbox_id,
                        )
                    )
                else:
                    broadcaster = get_session_broadcaster()
                    async with AsyncSessionLocal() as db:
                        session_svc = SessionService(db)
                        await session_svc.update_session_status(session_id, "rescheduling")
                        await session_svc.send_event(
                            session_id,
                            "session.status_rescheduling",
                            {"stop_reason": {"type": "sandbox_failed"}},
                        )
                    if broadcaster:
                        await broadcaster.send(
                            session_id,
                            {"type": "session.status_rescheduling", "stop_reason": {"type": "sandbox_failed"}},
                        )
            elif active_count > 0:
                _log_grpc_boundary_failure(
                    code="GRPC_DISCONNECT_IDLE_SKIPPED_ACTIVE_TASKS",
                    message="Skipping sandbox disconnect idle because active tasks remain",
                    operation="handle_sandbox_disconnect",
                    data={
                        "session_id": str(session_id),
                        "sandbox_id": str(sandbox_id),
                        "active_task_count": active_count,
                    },
                    retryable=False,
                    user_action=None,
                )
            else:
                async with AsyncSessionLocal() as db:
                    session_svc = SessionService(db)
                    session_rec = await session_svc.get_session(session_id)
                    session_is_idle = session_rec is not None and session_rec.status == "idle"
                if session_rec is None:
                    logger.debug(
                        "Session %s already deleted, skipping disconnect event",
                        session_id,
                    )
                elif not session_is_idle:
                    # A sandbox can be destroyed after a completed turn because of
                    # idle cleanup, manual cleanup, or container failure. That must
                    # not make the chat session terminal: a later user.message can
                    # create a fresh sandbox for the same session.
                    if self._event_bus:
                        await self._event_bus.publish(
                            JoySafeterEventEnvelope(
                                session_id=session_id,
                                event_type="session.status_idle",
                                payload={"stop_reason": {"type": "sandbox_disconnected"}},
                                is_status_change=True,
                                stop_reason={"type": "sandbox_disconnected"},
                                sandbox_id=sandbox_id,
                            )
                        )
                    else:
                        async with AsyncSessionLocal() as db:
                            session_svc = SessionService(db)
                            await session_svc.update_session_status(
                                session_id,
                                "idle",
                                stop_reason={"type": "sandbox_disconnected"},
                            )
                            await session_svc.send_event(
                                session_id,
                                "session.status_idle",
                                {"stop_reason": {"type": "sandbox_disconnected"}},
                            )
                        broadcaster = get_session_broadcaster()
                        if broadcaster:
                            await broadcaster.send(
                                session_id,
                                {"type": "session.status_idle", "stop_reason": {"type": "sandbox_disconnected"}},
                            )

        # 8. Unregister memory subscribers
        if session_id:
            mem_subs = get_memory_subscribers()
            if mem_subs:
                await mem_subs.unregister_session(session_id)

        # 9. Remove session broadcaster (no-op in Python -- broadcaster is shared)

        logger.info("SandboxBridge cleanup completed: sandbox=%s status=%s", sandbox_id, sandbox_status)

    async def _probe_container(self, provider, sandbox_id: uuid.UUID, external_id: Optional[str] = None) -> bool:
        if not external_id:
            from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
            from app.joysafeter_shared.database import AsyncSessionLocal

            try:
                async with AsyncSessionLocal() as db:
                    svc = SandboxService(db)
                    sandbox = await svc.get_sandbox(sandbox_id)
                    if not sandbox or not sandbox.external_id:
                        return True
                    external_id = sandbox.external_id
            except Exception:
                return True

        try:
            status = await provider.status(external_id)
            return bool(status != "running")
        except Exception:
            return True

    async def _grace_period_cleanup(
        self,
        sandbox_id: uuid.UUID,
        session_id: Optional[uuid.UUID],
        failover_pending_tasks: list,
        is_error: bool,
        original_bridge: Optional[SandboxBridge],
    ) -> None:
        """120s grace period for reconnection, matching Rust probe schedule (3s/5s/10s/15s/120s)."""

        # Probe at absolute 3s, 5s, 10s, 15s — matches Rust (cumulative sleeps: 3, 2, 5, 5)
        for sleep_sec in (3, 2, 5, 5):
            await asyncio.sleep(sleep_sec)
            current_bridge = await self._bridge_registry.get(sandbox_id)
            if current_bridge is not None and current_bridge is not original_bridge:
                logger.info(
                    "Bridge replaced by early reconnection for sandbox %s, re-queuing %d task(s)",
                    sandbox_id,
                    len(failover_pending_tasks),
                )
                for tid, _retry_count in failover_pending_tasks:
                    await self._queue.push_to_global(tid)
                    logger.info("Re-queued orphaned task %s immediately after reconnect", tid)
                return

        remaining = 120 - 15  # 105s to reach total 120s
        await asyncio.sleep(remaining)

        # Check if a new connection replaced this bridge
        current_bridge = await self._bridge_registry.get(sandbox_id)
        if current_bridge is not None and current_bridge is not original_bridge:
            logger.info("Bridge replaced by reconnection for sandbox %s, skipping cleanup", sandbox_id)
            for tid, _retry_count in failover_pending_tasks:
                await self._queue.push_to_global(tid)
                logger.info("Re-queued orphaned task %s after reconnect", tid)
            return

        _log_grpc_boundary_failure(
            code="GRPC_RECONNECT_GRACE_EXPIRED",
            message="No reconnection within grace period, cleaning up sandbox",
            operation="grace_period_cleanup",
            data={"sandbox_id": str(sandbox_id), "session_id": str(session_id or "")},
            retryable=False,
            user_action=None,
        )
        await self._execute_sandbox_cleanup(sandbox_id, session_id, failover_pending_tasks, is_error)


# --- Fix 3: Memory sync with cross-session peer broadcast ---


async def _handle_memory_sync_standalone(session_id: Optional[uuid.UUID], payload: dict) -> None:
    if not session_id:
        return

    import posixpath

    mount_name = payload.get("store_mount_name", "")
    rel_path = payload.get("relative_path", "")
    content = payload.get("content", "")
    operation = payload.get("operation", "upsert")

    # Normalize and validate path to prevent traversal
    rel_path = posixpath.normpath(rel_path)
    if rel_path.startswith("..") or "\x00" in rel_path:
        _log_grpc_boundary_failure(
            code="GRPC_MEMORY_SYNC_PATH_TRAVERSAL_BLOCKED",
            message="Memory sync blocked path traversal attempt",
            operation="memory_sync_validate_path",
            data={"session_id": str(session_id), "mount_name": str(mount_name), "relative_path": str(rel_path)},
            retryable=False,
            user_action=None,
        )
        return
    if not rel_path.startswith("/"):
        rel_path = "/" + rel_path

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
                    logger.warning("Ignoring write to read_only memory store mount=%s", mount_name)
                    return

                mem_svc = MemoryService(db)
                if operation == "delete":
                    existing = await mem_svc.get_memory_by_path(sms.store_id, rel_path)
                    if existing:
                        await mem_svc.delete_memory(sms.store_id, existing.id, session_id)
                else:
                    await mem_svc.upsert_memory_from_agent(sms.store_id, rel_path, content, session_id)

                break

    except Exception as e:
        _log_grpc_boundary_failure(
            code="GRPC_MEMORY_SYNC_FAILED",
            message="Memory sync failed",
            operation="memory_sync",
            error=e,
            data={"session_id": str(session_id), "mount_name": str(mount_name), "relative_path": str(rel_path)},
        )


def _extract_setup_commands(agent=None, environment=None) -> list[str]:
    """Extract setup_commands from environment config (packages.install_commands)
    and agent metadata.  Returns a combined list."""
    commands: list[str] = []

    if environment and getattr(environment, "config", None):
        env_config = environment.config
        if isinstance(env_config, dict):
            packages = env_config.get("packages", {})
            if isinstance(packages, dict):
                from app.joysafeter_domain.schemas.joysafeter_environment import Packages

                try:
                    pkg = Packages(**packages)
                    commands.extend(pkg.install_commands())
                except Exception:
                    pass

    if agent and getattr(agent, "metadata_", None):
        agent_cmds = agent.metadata_.get("setup_commands")
        if isinstance(agent_cmds, list):
            for cmd in agent_cmds:
                if isinstance(cmd, str) and cmd.strip():
                    commands.append(cmd.strip())

    return commands


def _build_repo_configs(harness_input) -> list:
    """Build RepoConfig protos from harness_input.repos.

    Tokens come pre-decrypted on harness_input and are passed straight to the
    runner over the gRPC channel; they are never logged here.
    """
    repos = []
    for rc in getattr(harness_input, "repos", None) or []:
        if not isinstance(rc, dict) or not rc.get("url"):
            continue
        repos.append(
            joysafeter_pb2.RepoConfig(
                url=rc.get("url", ""),
                branch=rc.get("branch", ""),
                path=rc.get("path", ""),
                authorization_token=rc.get("authorization_token", ""),
                mount_name=rc.get("mount_name", ""),
            )
        )
    return repos


def _build_setup_sandbox(
    harness_input,
    agent,
    environment=None,
    work_dir=None,
) -> joysafeter_pb2.SetupSandbox:
    skills = []
    for sa in harness_input.skill_archives:
        skills.append(
            joysafeter_pb2.SkillArchive(
                name=sa.name,
                tar_gz=sa.data,
                target=sa.target,
            )
        )

    mcp_servers = []
    for cfg in harness_input.mcp_servers:
        mcp_servers.append(
            joysafeter_pb2.McpConfig(
                name=cfg.get("name", ""),
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
                env=cfg.get("env", {}),
                # mcp_configs store the transport under "type" (schema McpServerConfig),
                # but older payloads used "server_type"/"transport". Accept all three so
                # the sandbox runner can tell remote (http/sse) from stdio servers.
                server_type=cfg.get("type") or cfg.get("server_type") or cfg.get("transport") or "",
                url=cfg.get("url", ""),
                headers=cfg.get("headers", {}),
            )
        )

    custom_tools = []
    for ct in harness_input.custom_tools:
        input_schema = ct.get("input_schema", {})
        schema_json = json.dumps(input_schema) if isinstance(input_schema, dict) else str(input_schema)
        custom_tools.append(
            joysafeter_pb2.CustomTool(
                name=ct["name"],
                description=ct.get("description", ""),
                input_schema_json=schema_json,
            )
        )

    memory_mounts = []
    for mm in harness_input.memory_mounts:
        files = []
        for f in mm.get("files", []):
            content = f.get("content", "")
            if isinstance(content, str):
                content = content.encode("utf-8")
            files.append(
                joysafeter_pb2.MemoryFile(
                    relative_path=f.get("path", ""),
                    content=content,
                )
            )
        logger.info(
            "Memory mount %s: %d files, mount_path=/mnt/memory/%s",
            mm.get("mount_name"),
            len(files),
            mm.get("mount_name"),
        )
        memory_mounts.append(
            joysafeter_pb2.MemoryStoreMount(
                store_id=mm.get("store_id", ""),
                mount_name=mm.get("mount_name", ""),
                mount_path=f"/mnt/memory/{mm.get('mount_name', '')}",
                access=mm.get("access", "read_write"),
                files=files,
            )
        )

    file_mounts = []
    for fm in getattr(harness_input, "file_mounts", []):
        file_mounts.append(
            joysafeter_pb2.FileMount(
                path=fm.path,
                content=fm.content,
                filename=fm.filename,
            )
        )

    file_refs = []
    for fr in getattr(harness_input, "file_refs", []):
        file_refs.append(
            joysafeter_pb2.FileRef(
                path=fr.path,
                url=fr.url,
                filename=fr.filename,
                size_bytes=fr.size_bytes,
            )
        )

    kwargs = dict(
        skills=skills,
        mcp_servers=mcp_servers,
        custom_tools=custom_tools,
        setup_commands=[],
        env=harness_input.env,
        secrets={},  # secrets injected via container env, not gRPC
        permission_mode=harness_input.permission_mode,
        provider=str(agent.engine_kind) if agent else "",
        model=harness_input.model or "",
        memory_system_prompt=harness_input.memory_system_prompt or "",
        memory_mounts=memory_mounts,
        files=file_mounts,
        file_refs=file_refs,
        allowed_tools=list(harness_input.allowed_tools or []),
        ask_tools=list(harness_input.ask_tools or []),
    )
    repos = _build_repo_configs(harness_input)
    if repos:
        kwargs["repos"] = repos
    if work_dir:
        kwargs["work_dir"] = work_dir
    return joysafeter_pb2.SetupSandbox(**kwargs)


def _build_start_task(
    task_id: uuid.UUID,
    harness_input,
    task,
    config,
    agent=None,
    session=None,
    environment=None,
) -> joysafeter_pb2.StartTask:
    skills = []
    for sa in harness_input.skill_archives:
        skills.append(
            joysafeter_pb2.SkillArchive(
                name=sa.name,
                tar_gz=sa.data,
                target=sa.target,
            )
        )

    mcp_servers = []
    for cfg in harness_input.mcp_servers:
        mcp_servers.append(
            joysafeter_pb2.McpConfig(
                name=cfg.get("name", ""),
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
                env=cfg.get("env", {}),
                # mcp_configs store the transport under "type" (schema McpServerConfig),
                # but older payloads used "server_type"/"transport". Accept all three so
                # the sandbox runner can tell remote (http/sse) from stdio servers.
                server_type=cfg.get("type") or cfg.get("server_type") or cfg.get("transport") or "",
                url=cfg.get("url", ""),
                headers=cfg.get("headers", {}),
            )
        )

    custom_tools = []
    for ct in harness_input.custom_tools:
        input_schema = ct.get("input_schema", {})
        schema_json = json.dumps(input_schema) if isinstance(input_schema, dict) else str(input_schema)
        custom_tools.append(
            joysafeter_pb2.CustomTool(
                name=ct["name"],
                description=ct.get("description", ""),
                input_schema_json=schema_json,
            )
        )

    # Use the permission rules resolved by harness_input_builder
    # Use the permission rules resolved by harness_input_builder
    # (_build_permission_rules): allow + ask, matching the official Managed
    # Agents model (always_allow / always_ask only). Do NOT re-derive here.
    allowed = list(harness_input.allowed_tools or [])
    ask = list(harness_input.ask_tools or [])

    timeout = task.timeout_sec or config.task_default_timeout

    engine_kind = str(agent.engine_kind) if agent else ""
    kwargs: dict[str, Any] = dict(
        task_id=str(task_id),
        provider=engine_kind,
        prompt=harness_input.prompt,
        system_prompt=harness_input.system_prompt or "",
        model=harness_input.model or "",
        timeout_seconds=timeout,
        env=harness_input.env,
        secrets={},  # secrets injected via container env, not gRPC
        mcp_servers=mcp_servers,
        skills=skills,
        allowed_tools=allowed,
        ask_tools=ask,
        permission_mode=harness_input.permission_mode,
        custom_tools=custom_tools,
    )
    if harness_input.session_id:
        kwargs["session_id"] = harness_input.session_id

    max_turns = 100
    if agent and getattr(agent, "metadata_", None):
        mt = agent.metadata_.get("max_turns")
        if mt is not None:
            try:
                max_turns = int(mt)
            except (ValueError, TypeError):
                pass
    kwargs["max_turns"] = max_turns

    if session and getattr(session, "last_work_dir", None):
        kwargs["work_dir"] = session.last_work_dir

    repos = _build_repo_configs(harness_input)
    if repos:
        kwargs["repos"] = repos

    setup_commands = _extract_setup_commands(agent, environment)
    if setup_commands:
        kwargs["setup_commands"] = setup_commands

    return joysafeter_pb2.StartTask(**kwargs)


def _proto_event_to_dict(event: joysafeter_pb2.RunnerHarnessEvent) -> dict[str, Any]:
    event_field = event.WhichOneof("event")
    if event_field is None:
        return {"type": "unknown"}

    if event_field == "text":
        return {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": event.text.content}],
            },
        }
    elif event_field == "thinking":
        return {
            "type": "assistant",
            "message": {
                "content": [{"type": "thinking", "content": event.thinking.content}],
            },
        }
    elif event_field == "tool_use":
        tu = event.tool_use
        try:
            input_data = json.loads(tu.input_json) if tu.input_json else {}
        except json.JSONDecodeError:
            input_data = {"raw": tu.input_json}

        if tu.is_control_request:
            return {
                "type": "control_request",
                "request": {
                    "subtype": "can_use_tool",
                    "tool_name": tu.tool,
                    "tool_input": input_data,
                },
                "request_id": tu.call_id,
            }

        return {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": tu.tool,
                        "id": tu.call_id,
                        "input": input_data,
                    }
                ],
            },
        }
    elif event_field == "tool_result":
        tr = event.tool_result
        return {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tr.call_id,
                        "name": tr.tool,
                        "content": tr.output,
                    }
                ],
            },
        }
    elif event_field == "error":
        return async_error_payload(
            code="RUNNER_EVENT_ERROR",
            message=event.error.message or "Runner emitted an error event",
            source="runtime",
            retryable=False,
        )
    elif event_field == "status":
        return {"type": "system", "subtype": event.status.state}
    elif event_field == "log":
        return {"type": "log", "level": event.log.level, "message": event.log.message}
    elif event_field == "model_request_start":
        return {"type": "model_request_start", "model": event.model_request_start.model}
    elif event_field == "model_request_end":
        mre = event.model_request_end
        return {
            "type": "model_request_end",
            "model": mre.model,
            "input_tokens": mre.input_tokens,
            "output_tokens": mre.output_tokens,
            "cache_read_tokens": mre.cache_read_tokens,
            "cache_write_tokens": mre.cache_write_tokens,
        }
    elif event_field == "task_notification":
        tn = event.task_notification
        # Background sub-agent lifecycle event (claude-code Task tool with
        # run_in_background=true). Surface the full payload so the event-mapper
        # downstream can write it as a first-class session event.
        payload: dict[str, Any] = {
            "type": "task_notification",
            "phase": tn.phase,
            "task_id": tn.task_id,
        }
        if tn.HasField("tool_use_id"):
            payload["tool_use_id"] = tn.tool_use_id
        if tn.HasField("description"):
            payload["description"] = tn.description
        if tn.HasField("status"):
            payload["status"] = tn.status
        if tn.HasField("summary"):
            payload["summary"] = tn.summary
        if tn.HasField("result"):
            payload["result"] = tn.result
        if tn.HasField("output_file"):
            payload["output_file"] = tn.output_file
        if tn.HasField("last_tool_name"):
            payload["last_tool_name"] = tn.last_tool_name
        if tn.HasField("total_tokens"):
            payload["total_tokens"] = tn.total_tokens
        if tn.HasField("tool_uses"):
            payload["tool_uses"] = tn.tool_uses
        if tn.HasField("duration_ms"):
            payload["duration_ms"] = tn.duration_ms
        return payload

    return {"type": "unknown"}


async def start_grpc_server(
    bridge_registry: SandboxBridgeRegistry,
    event_buffer: EventBatchSender,
    queue: QueueBackend,
    host: str = "0.0.0.0",
    port: int = 9090,
    vault_provider: Optional[Any] = None,
    execution_semaphore: Optional[asyncio.Semaphore] = None,
    event_bus: Optional[Any] = None,
) -> tuple[grpc_aio.Server, "AgentBridgeServicer"]:
    server = grpc_aio.server(
        options=[
            ("grpc.max_receive_message_length", 8 * 1024 * 1024),
            ("grpc.max_send_message_length", 32 * 1024 * 1024),
            ("grpc.max_concurrent_streams", 200),
            # Transport-level keepalive: detect dead connections through NAT/LB
            ("grpc.keepalive_time_ms", 30000),  # ping every 30s
            ("grpc.keepalive_timeout_ms", 10000),  # 10s to respond
            ("grpc.keepalive_permit_without_calls", 1),  # ping even when idle
            ("grpc.http2.min_recv_ping_interval_without_data_ms", 10000),
        ]
    )
    servicer = AgentBridgeServicer(
        bridge_registry,
        event_buffer,
        queue,
        vault_provider=vault_provider,
        execution_semaphore=execution_semaphore,
        event_bus=event_bus,
    )
    joysafeter_pb2_grpc.add_AgentBridgeServicer_to_server(servicer, server)
    # The current Rust runner is generated from proto/joysafeter.proto and
    # calls /joysafeter.AgentBridge/Session, while the Python backend proto is
    # still packaged as joysafeter.AgentBridge. Register both service names so
    # existing runners and backend code remain compatible.
    rpc_method_handlers = {
        "Session": grpc.stream_stream_rpc_method_handler(
            servicer.Session,
            request_deserializer=joysafeter_pb2.RunnerMessage.FromString,
            response_serializer=joysafeter_pb2.OrchestratorMessage.SerializeToString,
        ),
    }
    server.add_generic_rpc_handlers(
        (grpc.method_handlers_generic_handler("joysafeter.AgentBridge", rpc_method_handlers),)
    )
    server.add_registered_method_handlers("joysafeter.AgentBridge", rpc_method_handlers)
    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    logger.info("gRPC server started on %s:%d", host, port)
    return server, servicer
