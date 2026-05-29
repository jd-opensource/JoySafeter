"""gRPC AgentBridge server — bidirectional streaming between runner and orchestrator.

Ported 1:1 from conductor-kernel/src/grpc.rs Session handler.
Architecture: pull-based. The Session handler's outer loop blocks on
pop_for_sandbox() waiting for tasks. The scheduler only pushes to the queue.
"""
import asyncio
import json
import logging
import uuid
from typing import Any, Optional

from uuid_utils import uuid7

import grpc
from grpc import aio as grpc_aio

from app.core.grpc.proto import conductor_pb2, conductor_pb2_grpc
from app.core.sandbox_bridge import (
    SandboxBridge,
    SandboxBridgeRegistry,
    SandboxBridgeStatus,
    WsOutMessage,
)
from app.core.events.event_buffer import BufferedEvent, EventBatchSender
from app.core.queue import QueueBackend
from app.core.events.envelope import ConductorEventEnvelope

logger = logging.getLogger(__name__)

_HEARTBEAT_TIMEOUT_DEFAULT = 120
TASK_DEFAULT_TIMEOUT_SEC = 7200


def _get_heartbeat_timeout() -> int:
    from app.core.lifespan import get_runtime_config
    rc = get_runtime_config()
    if rc:
        return rc.heartbeat_timeout_sec
    return _HEARTBEAT_TIMEOUT_DEFAULT


class AgentBridgeServicer(conductor_pb2_grpc.AgentBridgeServicer):
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
        self._execution_semaphore = execution_semaphore or asyncio.Semaphore(200)
        self._event_bus = event_bus

    async def Session(self, request_iterator, context):
        """Bidirectional streaming RPC — 1:1 port of agentd's grpc.rs Session handler.

        Architecture:
        - Receive RunnerReady
        - Send SetupSandbox
        - Enter outer loop: block on pop_for_sandbox() for next task
        - Per task: send StartTask, enter inner loop reading events until Result+Idle
        - On disconnect: cleanup
        """
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
                sandbox_id, ready.runner_version, ready.is_reconnect,
            )

            # Register bridge (always create fresh, matching Rust sandbox_bridges.insert)
            bridge = await self._bridge_registry.register(sandbox_id, str(sandbox_id))

            bridge.runner_stream = context
            bridge.runner_connected.set()

            # Register Redis owner (Rust: redis.register_sandbox_owner)
            from app.core.lifespan import get_redis_coordinator as _get_rc_init
            _coord_init = _get_rc_init()
            if _coord_init:
                await _coord_init.register_sandbox_owner(sandbox_id)

            # DB status CAS: reject terminal sandboxes, skip CAS for pooled, otherwise CAS to idle
            from app.core.database import AsyncSessionLocal as _ASL_init
            from app.services.sandbox_service import SandboxService as _SbxSvc_init

            async with _ASL_init() as _db_init:
                _svc_init = _SbxSvc_init(_db_init)
                _sandbox_rec = await _svc_init.get_sandbox(sandbox_id)
                if _sandbox_rec:
                    _current_status = _sandbox_rec.status
                    if _current_status in ("destroyed", "error"):
                        logger.warning(
                            "Runner connected to terminal sandbox %s (status=%s), rejecting",
                            sandbox_id, _current_status,
                        )
                        await self._bridge_registry.remove(sandbox_id)
                        return
                    if _current_status in ("stopping", "stopped"):
                        logger.warning(
                            "Runner connected to sandbox being stopped %s (status=%s), rejecting",
                            sandbox_id, _current_status,
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

            bridge.status = SandboxBridgeStatus.IDLE

            # --- Send SetupSandbox or resolve session (BEFORE active_task_id, matching Rust) ---
            if not ready.is_reconnect and not bridge.setup_done:
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
                    logger.warning(
                        "Timed out waiting for sandbox %s to link with session — SetupSandbox will be skipped",
                        sandbox_id,
                    )
                else:
                    await self._send_setup(bridge, sandbox_id)
            else:
                logger.info("Runner reconnecting sandbox %s, skipping setup", sandbox_id)
                # Resolve session from DB on reconnect
                async with _ASL_init() as _db_resolve:
                    _svc_resolve = _SbxSvc_init(_db_resolve)
                    _rec_resolve = await _svc_resolve.get_sandbox(sandbox_id)
                    if _rec_resolve:
                        linked_session_id = _rec_resolve.chat_session_id

            # Register memory subscribers for this session
            if linked_session_id:
                from app.core.lifespan import get_memory_subscribers
                from app.core.memory_sync import MemorySessionEntry
                mem_subs = get_memory_subscribers()
                if mem_subs:
                    from app.services.session_service import SessionService as _SessSvc
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
                    bridge, sandbox_id, ready.active_task_id, context, stream_cancel,
                    failover_pending_tasks,
                )
            elif ready.is_reconnect:
                # Runner reconnected without active_task_id — rescue orphaned running tasks
                await self._rescue_orphaned_tasks(sandbox_id)

            # --- Outer task-dispatch loop (matches agentd) ---
            # Blocks on pop_for_sandbox until a task arrives or stream disconnects.
            # Shield from gRPC cancellation — we handle stream EOF internally.
            failure_ejected = await asyncio.shield(self._multi_task_loop(
                bridge, sandbox_id, context, stream_cancel,
                failover_pending_tasks, linked_session_id,
            ))

        except grpc_aio.AioRpcError as e:
            logger.warning("gRPC AioRpcError for sandbox %s: code=%s details=%s", sandbox_id, e.code(), e.details())
        except asyncio.CancelledError:
            logger.warning("gRPC session cancelled for sandbox %s", sandbox_id)
        except Exception as e:
            logger.error("gRPC session error for sandbox %s: %s", sandbox_id, e, exc_info=True)
        finally:
            stream_cancel.set()
            if bridge:
                bridge.runner_connected.clear()
                bridge.runner_stream = None
                bridge.status = SandboxBridgeStatus.DISCONNECTED
                logger.info("Runner disconnected: sandbox=%s", sandbox_id)
            if sandbox_id:
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
        from app.core.database import AsyncSessionLocal
        from app.models.task import ConductorTaskStatus as TaskStatus
        from app.models.session import SessionStatus
        from app.services.task_service import ConductorTaskService as TaskService
        from app.services.session_service import SessionService
        from app.services.sandbox_service import SandboxService
        from app.core.events.event_mapping import map_harness_event, is_control_request
        from app.core.task_controller import TaskController
        from app.core.lifespan import get_session_broadcaster, get_redis_coordinator
        from app.core.harness_input_builder import extract_tool_name_sets

        bridge.setup_done = True  # skip SetupSandbox on reconnect

        try:
            active_task_id = uuid.UUID(active_task_id_str)
        except ValueError:
            logger.warning(
                "Invalid active_task_id on reconnect: %s", active_task_id_str,
            )
            return

        # Check if task is already terminal
        async with AsyncSessionLocal() as db:
            task_svc = TaskService(db)
            task = await task_svc.get_task(active_task_id)
            if not task:
                logger.warning(
                    "Reconnect: active task %s not found, ignoring", active_task_id,
                )
                return
            if TaskStatus.from_str_lossy(task.status).is_terminal():
                logger.info(
                    "Reconnect: active task %s already terminal (%s), ignoring",
                    active_task_id, task.status,
                )
                return

        # Acquire execution semaphore
        await self._execution_semaphore.acquire()
        try:
            logger.info(
                "Resuming active task %s from reconnecting runner on sandbox %s",
                active_task_id, sandbox_id,
            )

            # Set Redis task->sandbox mapping
            coordinator = get_redis_coordinator()
            if coordinator:
                await coordinator.set_task_sandbox(active_task_id, sandbox_id)

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
                    task_session_id = task.chat_session_id
                    task_timeout_sec = task.timeout_sec or TASK_DEFAULT_TIMEOUT_SEC
                    from app.services.agent_service import ConductorAgentService as AgentService
                    agent_svc = AgentService(db)
                    agent = await agent_svc.get_agent(task.agent_id)
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
                    pending_events = await session_svc.list_unprocessed_events(
                        task_session_id, control_types
                    )
                    for evt in pending_events:
                        content = ""
                        if isinstance(evt.payload, dict):
                            content = evt.payload.get("content", "")
                        input_msg = conductor_pb2.OrchestratorMessage(
                            input=conductor_pb2.SendInput(content=content)
                        )
                        await context.write(input_msg)
                        await session_svc.mark_event_processed(evt.id)

            # --- Inner event loop for resumed task ---
            task_done = False
            got_idle = False
            heartbeat_timed_out = False
            requires_action_pending = False
            buffered_events: list[tuple[str, dict]] = []
            last_tool_use_event_id: Optional[str] = None

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
                    cancel_msg = conductor_pb2.OrchestratorMessage(
                        cancel=conductor_pb2.CancelTask(reason="Cancelled by user")
                    )
                    await context.write(cancel_msg)
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
                            input_msg = conductor_pb2.OrchestratorMessage(
                                input=conductor_pb2.SendInput(content=content)
                            )
                            await context.write(input_msg)
                        except asyncio.QueueEmpty:
                            break

                    if task_session_id:
                        if self._event_bus:
                            await self._event_bus.publish(ConductorEventEnvelope(
                                session_id=task_session_id,
                                event_type="session.status_running",
                                payload={},
                                is_status_change=True,
                                task_id=active_task_id,
                                sandbox_id=sandbox_id,
                            ))
                        else:
                            async with AsyncSessionLocal() as db:
                                svc = SessionService(db)
                                await svc.update_session_status(task_session_id, SessionStatus.RUNNING.value)
                                await svc.send_event(task_session_id, "session.status_running", {})
                            broadcaster = get_session_broadcaster()
                            if broadcaster:
                                await broadcaster.send(task_session_id, {"type": "session.status_running"})

                    if buffered_events and task_session_id:
                        for buf_type, buf_payload in buffered_events:
                            if self._event_bus:
                                await self._event_bus.publish(ConductorEventEnvelope(
                                    session_id=task_session_id,
                                    event_type=buf_type,
                                    payload=buf_payload,
                                    task_id=active_task_id,
                                    sandbox_id=sandbox_id,
                                    task_broadcast_payload={"type": buf_type, **buf_payload},
                                ))
                            else:
                                ws_msg = WsOutMessage(type="event", payload={"type": buf_type, **buf_payload})
                                await bridge.broadcast_to_task(active_task_id, ws_msg)
                                if coordinator:
                                    await coordinator.publish_event(
                                        active_task_id, json.dumps({"type": ws_msg.type, **ws_msg.payload})
                                    )
                                async with AsyncSessionLocal() as db:
                                    svc = SessionService(db)
                                    await svc.send_event(task_session_id, buf_type, buf_payload)
                                broadcaster = get_session_broadcaster()
                                if broadcaster:
                                    await broadcaster.send(
                                        task_session_id,
                                        {**{"type": buf_type}, **(buf_payload if isinstance(buf_payload, dict) else {})},
                                    )
                    buffered_events.clear()
                    continue

                # Heartbeat timeout
                if heartbeat_fut in done:
                    logger.warning(
                        "Heartbeat timeout during resumed task %s: sandbox=%s",
                        active_task_id, sandbox_id,
                    )
                    heartbeat_timed_out = True
                    break

                # Task deadline
                if deadline_fut in done and not requires_action_pending:
                    logger.warning(
                        "Task deadline exceeded for resumed task %s: timeout=%ds",
                        active_task_id, task_timeout_sec,
                    )
                    cancel_msg = conductor_pb2.OrchestratorMessage(
                        cancel=conductor_pb2.CancelTask(
                            reason=f"Server-side deadline exceeded ({task_timeout_sec}s)"
                        )
                    )
                    await context.write(cancel_msg)
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
                            asyncio.create_task(
                                _handle_memory_sync_standalone(task_session_id, mapped_payload)
                            )
                            continue

                        if mapped_type == "error":
                            bridge.last_error = mapped_payload.get("error") or mapped_payload.get("message")

                        if requires_action_pending:
                            buffered_events.append((mapped_type, mapped_payload))
                            continue

                        if mapped_type in ("agent.tool_use", "agent.mcp_tool_use") and is_control_request(mapped_payload):
                            call_id = mapped_payload.get("_call_id") or mapped_payload.get("request_id") or mapped_payload.get("id") or mapped_payload.get("call_id") or ""

                            event_id = f"evt_{uuid7()}"
                            persisted_id = uuid7() if task_session_id else None
                            if self._event_bus and task_session_id:
                                await self._event_bus.publish(ConductorEventEnvelope(
                                    session_id=task_session_id,
                                    event_type=mapped_type,
                                    payload=mapped_payload,
                                    task_id=active_task_id,
                                    sandbox_id=sandbox_id,
                                    event_id=persisted_id,
                                    seq=event.seq,
                                    flush_immediately=True,
                                    task_broadcast_payload={"type": mapped_type, **mapped_payload},
                                ))
                                event_id = f"evt_{persisted_id}"
                                last_tool_use_event_id = event_id
                            else:
                                ws_msg = WsOutMessage(type="event", payload={"type": mapped_type, **mapped_payload})
                                await bridge.broadcast_to_task(active_task_id, ws_msg)
                                if coordinator:
                                    await coordinator.publish_event(
                                        active_task_id, json.dumps({"type": ws_msg.type, **ws_msg.payload})
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
                                            {**{"type": mapped_type, "seq": event.seq}, **(mapped_payload if isinstance(mapped_payload, dict) else {})},
                                        )

                            if call_id:
                                bridge.pending_control_request_ids[event_id] = call_id
                            requires_action_pending = True
                            bridge._requires_action_pending = True
                            if task_session_id:
                                stop_reason = {"type": "requires_action", "event_ids": [event_id]}
                                if self._event_bus:
                                    await self._event_bus.publish(ConductorEventEnvelope(
                                        session_id=task_session_id,
                                        event_type="session.status_idle",
                                        payload={"stop_reason": stop_reason},
                                        is_status_change=True,
                                        stop_reason=stop_reason,
                                        task_id=active_task_id,
                                        sandbox_id=sandbox_id,
                                    ))
                                else:
                                    async with AsyncSessionLocal() as db:
                                        svc = SessionService(db)
                                        await svc.update_session_status(
                                            task_session_id, SessionStatus.IDLE.value, stop_reason=stop_reason
                                        )
                                        await svc.send_event(
                                            task_session_id, "session.status_idle", {"stop_reason": stop_reason}
                                        )
                                    broadcaster = get_session_broadcaster()
                                    if broadcaster:
                                        await broadcaster.send(
                                            task_session_id,
                                            {"type": "session.status_idle", "stop_reason": stop_reason},
                                        )
                            continue

                        if self._event_bus and task_session_id:
                            await self._event_bus.publish(ConductorEventEnvelope(
                                session_id=task_session_id,
                                event_type=mapped_type,
                                payload=mapped_payload,
                                task_id=active_task_id,
                                sandbox_id=sandbox_id,
                                seq=event.seq,
                                task_broadcast_payload={"type": mapped_type, **mapped_payload},
                            ))
                        else:
                            ws_msg = WsOutMessage(
                                type="event",
                                payload={"type": mapped_type, **mapped_payload},
                            )
                            await bridge.broadcast_to_task(active_task_id, ws_msg)

                            if coordinator:
                                await coordinator.publish_event(
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
                                        {**{"type": mapped_type, "seq": event.seq}, **(mapped_payload if isinstance(mapped_payload, dict) else {})},
                                    )

                        if mapped_type == "agent.custom_tool_use" and not requires_action_pending:
                            call_id = mapped_payload.get("_call_id") or mapped_payload.get("request_id") or mapped_payload.get("id") or mapped_payload.get("call_id") or ""
                            event_id = last_tool_use_event_id or f"evt_{uuid7()}"
                            if call_id:
                                bridge.pending_control_request_ids[event_id] = call_id
                            requires_action_pending = True
                            bridge._requires_action_pending = True
                            if task_session_id:
                                await self._event_buffer.flush()
                                stop_reason = {"type": "requires_action", "event_ids": [event_id]}
                                if self._event_bus:
                                    await self._event_bus.publish(ConductorEventEnvelope(
                                        session_id=task_session_id,
                                        event_type="session.status_idle",
                                        payload={"stop_reason": stop_reason},
                                        is_status_change=True,
                                        stop_reason=stop_reason,
                                        task_id=active_task_id,
                                        sandbox_id=sandbox_id,
                                    ))
                                else:
                                    async with AsyncSessionLocal() as db:
                                        svc = SessionService(db)
                                        await svc.update_session_status(
                                            task_session_id, SessionStatus.IDLE.value, stop_reason=stop_reason
                                        )
                                        await svc.send_event(
                                            task_session_id, "session.status_idle", {"stop_reason": stop_reason}
                                        )
                                    broadcaster = get_session_broadcaster()
                                    if broadcaster:
                                        await broadcaster.send(
                                            task_session_id,
                                            {"type": "session.status_idle", "stop_reason": stop_reason},
                                        )

                elif payload_type == "result":
                    result = msg.result
                    await self._handle_reconnect_result(
                        bridge, sandbox_id, active_task_id, task_session_id, result, coordinator,
                    )
                    task_done = True

                elif payload_type == "idle":
                    idle_msg = msg.idle
                    bridge.status = SandboxBridgeStatus.IDLE
                    bridge.current_task_id = None
                    logger.info("Runner idle after resumed task: sandbox=%s", sandbox_id)

                    async with AsyncSessionLocal() as db:
                        sandbox_svc = SandboxService(db)
                        await sandbox_svc.update_status(sandbox_id, "idle")
                        await sandbox_svc.touch(sandbox_id)

                    if coordinator:
                        await coordinator.refresh_sandbox_owner(sandbox_id)

                    async with AsyncSessionLocal() as db:
                        sandbox_svc2 = SandboxService(db)
                        sandbox_record = await sandbox_svc2.get_sandbox(sandbox_id)
                        if sandbox_record and sandbox_record.chat_session_id:
                            harness_session_id = idle_msg.session_id if idle_msg.HasField("session_id") else None
                            work_dir = idle_msg.work_dir if idle_msg.HasField("work_dir") else None
                            svc = SessionService(db)
                            await svc.update_session_sandbox(
                                sandbox_record.chat_session_id, sandbox_id,
                                harness_session_id=harness_session_id,
                                work_dir=work_dir,
                            )

                    got_idle = True

                elif payload_type == "memory_sync":
                    ms = msg.memory_sync
                    asyncio.create_task(_handle_memory_sync_standalone(task_session_id, {
                        "store_mount_name": ms.store_mount_name,
                        "relative_path": ms.relative_path,
                        "content": ms.content,
                        "operation": ms.operation,
                    }))

                if task_done and got_idle:
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
                logger.warning(
                    "Resumed task %s incomplete on sandbox %s: %s",
                    active_task_id, sandbox_id, reason,
                )
                retry_count = await TaskController.failover_or_fail_task(
                    active_task_id, reason
                )
                if retry_count is not None:
                    failover_pending_tasks.append((active_task_id, retry_count))
                bridge.remove_task_subscribers(active_task_id)
                if coordinator:
                    await coordinator.remove_task_sandbox(active_task_id)
                if not got_idle:
                    # Stream broken -- signal cleanup
                    stream_cancel.set()

            if task_done and not got_idle:
                bridge.status = SandboxBridgeStatus.IDLE
                bridge.current_task_id = None
                async with AsyncSessionLocal() as db:
                    sandbox_svc = SandboxService(db)
                    await sandbox_svc.update_status(sandbox_id, "idle")
                bridge.remove_task_subscribers(active_task_id)
                if coordinator:
                    await coordinator.remove_task_sandbox(active_task_id)

        finally:
            self._execution_semaphore.release()

    async def _rescue_orphaned_tasks(self, sandbox_id: uuid.UUID) -> None:
        """Re-queue running tasks orphaned by a runner that reconnected without active_task_id."""
        from app.core.database import AsyncSessionLocal
        from app.services.task_service import ConductorTaskService as TaskService
        from app.models.task import ConductorTaskStatus as TaskStatus, ConductorTask
        from sqlalchemy import select, and_

        try:
            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                result = await db.execute(
                    select(ConductorTask.id)
                    .where(
                        and_(
                            ConductorTask.sandbox_id == sandbox_id,
                            ConductorTask.status == TaskStatus.RUNNING.value,
                        )
                    )
                )
                orphaned_ids = [row[0] for row in result.fetchall()]

                if not orphaned_ids:
                    return

                logger.info(
                    "Rescuing %d orphaned running task(s) for sandbox %s: %s",
                    len(orphaned_ids), sandbox_id, orphaned_ids,
                )

                for tid in orphaned_ids:
                    ok = await task_svc.increment_retry(tid)
                    if ok:
                        await self._queue.push_to_global(tid)
                        logger.info("Orphaned task %s reset to pending and re-queued", tid)
                    else:
                        logger.warning("Could not reset orphaned task %s (may be terminal)", tid)
        except Exception as e:
            logger.error("Failed to rescue orphaned tasks for sandbox %s: %s", sandbox_id, e)

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
        from app.core.settings import conductor_config

        heartbeat_deadline = _time.monotonic() + _get_heartbeat_timeout()
        consecutive_failures: int = 0
        failure_ejected = False

        pending_read: Optional[asyncio.Future] = None

        logger.info("Entering multi-task loop for sandbox %s (stream_cancel=%s)", sandbox_id, stream_cancel.is_set())
        while not stream_cancel.is_set():
            # Idle phase: wait for a task from the queue while reading heartbeats
            pop_task = asyncio.create_task(
                self._queue.pop_for_sandbox(sandbox_id, stream_cancel),
                name=f"pop-{sandbox_id}",
            )

            task_id = None
            while not stream_cancel.is_set():
                if pending_read is None:
                    pending_read = asyncio.ensure_future(context.read())

                waitables = {pop_task, pending_read}

                hb_remaining = max(heartbeat_deadline - _time.monotonic(), 0.01)
                hb_timer = asyncio.create_task(asyncio.sleep(hb_remaining))
                waitables.add(hb_timer)

                done, pending = await asyncio.wait(
                    waitables, return_when=asyncio.FIRST_COMPLETED,
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
                        pop_task.cancel()
                        try:
                            await pop_task
                        except (asyncio.CancelledError, Exception):
                            pass
                        break
                    payload_type = msg.WhichOneof("payload")
                    if payload_type == "heartbeat":
                        heartbeat_deadline = _time.monotonic() + _get_heartbeat_timeout()
                    continue

                if pop_task in done:
                    task_id = pop_task.result()
                    break

                if hb_timer in done:
                    now = _time.monotonic()
                    if now >= heartbeat_deadline:
                        logger.warning("Heartbeat timeout while idle: sandbox=%s", sandbox_id)
                        stream_cancel.set()
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

            # Acquire execution semaphore before dispatching
            await self._execution_semaphore.acquire()
            try:
                success, task_deadline_exceeded, task_error_status, task_completed = await self._run_single_task(
                    bridge, sandbox_id, context, task_id, stream_cancel,
                    failover_pending_tasks, linked_session_id,
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

            if consecutive_failures >= conductor_config.sandbox_failure_threshold:
                logger.warning(
                    "Sandbox %s exceeded failure threshold (%d >= %d), ejecting",
                    sandbox_id, consecutive_failures, conductor_config.sandbox_failure_threshold,
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

    async def _run_single_task(
        self,
        bridge: SandboxBridge,
        sandbox_id: uuid.UUID,
        context,
        task_id: uuid.UUID,
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
        from app.core.database import AsyncSessionLocal
        from app.models.task import ConductorTaskStatus as TaskStatus
        from app.models.session import SessionStatus
        from app.services.task_service import ConductorTaskService as TaskService
        from app.services.agent_service import ConductorAgentService as AgentService
        from app.services.session_service import SessionService
        from app.services.sandbox_service import SandboxService
        from app.core.harness_input_builder import build_harness_input, extract_tool_name_sets
        from app.core.events.event_mapping import map_harness_event, is_control_request
        from app.core.settings import conductor_config
        from app.core.lifespan import get_session_broadcaster, get_redis_coordinator
        from app.core.task_controller import TaskController

        logger.info("Dispatching task %s to sandbox %s", task_id, sandbox_id)

        # Issue 3 fix: set task->sandbox mapping in Redis (matching Rust line 757)
        coordinator = get_redis_coordinator()
        if coordinator:
            await coordinator.set_task_sandbox(task_id, sandbox_id)

        bridge.status = SandboxBridgeStatus.BUSY
        bridge.current_task_id = task_id

        # --- Build and send StartTask ---
        try:
            async with AsyncSessionLocal() as db:
                task_svc = TaskService(db)
                agent_svc = AgentService(db)
                session_svc = SessionService(db)
                sandbox_svc = SandboxService(db)

                task = await task_svc.get_task(task_id)
                if not task:
                    logger.error("Task %s not found for dispatch", task_id)
                    bridge.current_task_id = None
                    bridge.status = SandboxBridgeStatus.IDLE
                    return (True, False, False, False)

                agent = await agent_svc.get_agent(task.agent_id)
                if not agent:
                    await task_svc.update_task_error(task_id, "Agent not found", TaskStatus.FAILED)
                    bridge.current_task_id = None
                    bridge.status = SandboxBridgeStatus.IDLE
                    return (True, False, True, False)

                cas_ok = await task_svc.update_task_status(task_id, TaskStatus.RUNNING)
                if not cas_ok:
                    logger.warning("CAS conflict: task %s no longer pending, skipping dispatch", task_id)
                    bridge.current_task_id = None
                    bridge.status = SandboxBridgeStatus.IDLE
                    coordinator = get_redis_coordinator()
                    if coordinator:
                        await coordinator.remove_task_sandbox(task_id)
                    return (True, False, False, False)

                session_id = task.chat_session_id

                await sandbox_svc.touch(sandbox_id, task_id)

                session = None
                environment = None
                if session_id:
                    session = await session_svc.get_session(session_id)

                env_ref = getattr(agent, "environment_ref", None)
                if env_ref:
                    from app.services.conductor_environment_service import EnvironmentService
                    env_svc = EnvironmentService(db)
                    environment = await env_svc.get_environment_by_ref(env_ref)

            harness_input = await build_harness_input(
                task, agent, session_id, bridge.external_id, sandbox_id,
            )

            custom_names, mcp_names = extract_tool_name_sets(agent)

            start_msg = _build_start_task(
                task_id, harness_input, task, conductor_config,
                agent=agent, session=session, environment=environment,
            )
            orch_msg = conductor_pb2.OrchestratorMessage(start=start_msg)
            await context.write(orch_msg)
            logger.info("StartTask sent: task=%s sandbox=%s", task_id, sandbox_id)

            if session_id and self._event_bus:
                await self._event_bus.publish(ConductorEventEnvelope(
                    session_id=session_id,
                    event_type="session.status_running",
                    payload={},
                    is_status_change=True,
                    task_id=task_id,
                    sandbox_id=sandbox_id,
                ))
        except Exception as e:
            logger.error("Failed to dispatch task %s: %s", task_id, e, exc_info=True)
            bridge.current_task_id = None
            bridge.status = SandboxBridgeStatus.IDLE
            await TaskController.failover_or_fail_task(task_id, str(e))
            return (True, False, True, False)

        # --- Inner per-task event loop ---
        import time as _time
        task_done = False
        got_idle = False
        requires_action_pending = False
        deadline_exceeded = False
        task_error_status = False
        task_completed = False
        timeout = task.timeout_sec or conductor_config.task_default_timeout
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
                waitables, return_when=asyncio.FIRST_COMPLETED,
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
                cancel_msg = conductor_pb2.OrchestratorMessage(
                    cancel=conductor_pb2.CancelTask(reason="Cancelled by user")
                )
                await context.write(cancel_msg)
                continue

            # --- Confirmation received (Rust lines 938-951 + loop-top flush 898-929) ---
            if confirm_fut in done and requires_action_pending:
                requires_action_pending = False
                bridge.confirmation_event.clear()
                bridge._requires_action_pending = False
                logger.info("Confirmation received for task %s, resuming", task_id)
                while not bridge._control_queue.empty():
                    try:
                        content = bridge._control_queue.get_nowait()
                        input_msg = conductor_pb2.OrchestratorMessage(
                            input=conductor_pb2.SendInput(content=content)
                        )
                        await context.write(input_msg)
                    except asyncio.QueueEmpty:
                        break

                # Rust confirmation handler: update status + emit running event
                if session_id:
                    if self._event_bus:
                        await self._event_bus.publish(ConductorEventEnvelope(
                            session_id=session_id,
                            event_type="session.status_running",
                            payload={},
                            is_status_change=True,
                            task_id=task_id,
                            sandbox_id=sandbox_id,
                        ))
                    else:
                        async with AsyncSessionLocal() as db:
                            svc = SessionService(db)
                            await svc.update_session_status(session_id, SessionStatus.RUNNING.value)
                            await svc.send_event(session_id, "session.status_running", {})
                        broadcaster = get_session_broadcaster()
                        if broadcaster:
                            await broadcaster.send(
                                session_id,
                                {"type": "session.status_running"},
                            )

                # Flush buffered events (Rust loop-top flush, lines 898-929)
                if buffered_events:
                    logger.info("Flushing %d buffered events after confirmation for task %s", len(buffered_events), task_id)
                    if session_id:
                        # Rust loop-top flush also emits session.status_running again
                        if self._event_bus:
                            await self._event_bus.publish(ConductorEventEnvelope(
                                session_id=session_id,
                                event_type="session.status_running",
                                payload={},
                                is_status_change=True,
                                task_id=task_id,
                                sandbox_id=sandbox_id,
                            ))
                        else:
                            async with AsyncSessionLocal() as db:
                                svc = SessionService(db)
                                await svc.update_session_status(session_id, SessionStatus.RUNNING.value)
                                await svc.send_event(session_id, "session.status_running", {})
                            broadcaster = get_session_broadcaster()
                            if broadcaster:
                                await broadcaster.send(
                                    session_id,
                                    {"type": "session.status_running"},
                                )

                        for buf_type, buf_payload in buffered_events:
                            if self._event_bus:
                                await self._event_bus.publish(ConductorEventEnvelope(
                                    session_id=session_id,
                                    event_type=buf_type,
                                    payload=buf_payload,
                                    task_id=task_id,
                                    sandbox_id=sandbox_id,
                                    task_broadcast_payload={"type": buf_type, **buf_payload},
                                ))
                            else:
                                ws_msg = WsOutMessage(
                                    type="event",
                                    payload={"type": buf_type, **buf_payload},
                                )
                                await bridge.broadcast_to_task(task_id, ws_msg)

                                coordinator = get_redis_coordinator()
                                if coordinator:
                                    await coordinator.publish_event(
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
                                        {**{"type": buf_type}, **(buf_payload if isinstance(buf_payload, dict) else {})},
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
                logger.warning("Heartbeat timeout during task %s: sandbox=%s", task_id, sandbox_id)
                retry_count = await TaskController.failover_or_fail_task(task_id, reason)
                if retry_count is not None:
                    failover_pending_tasks.append((task_id, retry_count))
                bridge.remove_task_subscribers(task_id)
                from app.core.lifespan import get_redis_coordinator as _get_rc
                _coord = _get_rc()
                if _coord:
                    await _coord.remove_task_sandbox(task_id)
                return (False, False, False, False)
            if deadline_fut in done and not requires_action_pending:
                logger.warning("Task deadline exceeded: task=%s timeout=%ds", task_id, timeout)
                cancel_msg = conductor_pb2.OrchestratorMessage(
                    cancel=conductor_pb2.CancelTask(
                        reason=f"Server-side deadline exceeded ({timeout}s)"
                    )
                )
                await context.write(cancel_msg)
                async with AsyncSessionLocal() as db:
                    task_svc = TaskService(db)
                    await task_svc.update_task_error(
                        task_id,
                        f"Task timed out after {timeout}s (server-side deadline)",
                        TaskStatus.TIMEOUT,
                    )
                if session_id:
                    if self._event_bus:
                        await self._event_bus.publish(ConductorEventEnvelope(
                            session_id=session_id,
                            event_type="session.status_idle",
                            payload={"stop_reason": {"type": "timeout"}},
                            is_status_change=True,
                            stop_reason={"type": "timeout"},
                            task_id=task_id,
                            sandbox_id=sandbox_id,
                        ))
                    else:
                        async with AsyncSessionLocal() as db:
                            svc = SessionService(db)
                            await svc.update_session_status(
                                session_id, SessionStatus.IDLE.value,
                                stop_reason={"type": "timeout"},
                            )
                            await svc.send_event(
                                session_id,
                                "session.status_idle",
                                {"stop_reason": {"type": "timeout"}},
                            )
                        broadcaster = get_session_broadcaster()
                        if broadcaster:
                            await broadcaster.send(
                                session_id,
                                {"type": "session.status_idle", "stop_reason": {"type": "timeout"}},
                            )
                task_done = True
                deadline_exceeded = True
                break

            # --- Stream message ---
            if read_fut not in done:
                continue
            msg = read_fut.result()
            if msg == grpc_aio.EOF:
                logger.warning("EOF received in task event loop: task=%s task_done=%s got_idle=%s", task_id, task_done, got_idle)
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
                        asyncio.create_task(
                            _handle_memory_sync_standalone(session_id, mapped_payload)
                        )
                        continue

                    if mapped_type == "error":
                        bridge.last_error = mapped_payload.get("error") or mapped_payload.get("message")

                    if requires_action_pending:
                        buffered_events.append((mapped_type, mapped_payload))
                        continue

                    if mapped_type in ("agent.tool_use", "agent.mcp_tool_use") and is_control_request(mapped_payload):
                        call_id = mapped_payload.get("_call_id") or mapped_payload.get("request_id") or mapped_payload.get("id") or mapped_payload.get("call_id") or ""

                        # Persist the tool_use event to DB first so event_id is stable
                        persisted_event_id = uuid7() if session_id else None

                        if self._event_bus and session_id:
                            await self._event_bus.publish(ConductorEventEnvelope(
                                session_id=session_id,
                                event_type=mapped_type,
                                payload=mapped_payload,
                                task_id=task_id,
                                sandbox_id=sandbox_id,
                                event_id=persisted_event_id,
                                seq=event.seq,
                                flush_immediately=True,
                                task_broadcast_payload={"type": mapped_type, **mapped_payload},
                            ))
                        else:
                            ws_msg = WsOutMessage(
                                type="event",
                                payload={"type": mapped_type, **mapped_payload},
                            )
                            await bridge.broadcast_to_task(task_id, ws_msg)

                            coordinator = get_redis_coordinator()
                            if coordinator:
                                await coordinator.publish_event(
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
                                        {**{"type": mapped_type, "seq": event.seq}, **(mapped_payload if isinstance(mapped_payload, dict) else {})},
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
                                await self._event_bus.publish(ConductorEventEnvelope(
                                    session_id=session_id,
                                    event_type="session.status_idle",
                                    payload={"stop_reason": stop_reason},
                                    is_status_change=True,
                                    stop_reason=stop_reason,
                                    task_id=task_id,
                                    sandbox_id=sandbox_id,
                                ))
                            else:
                                async with AsyncSessionLocal() as db:
                                    svc = SessionService(db)
                                    await svc.update_session_status(
                                        session_id, SessionStatus.IDLE.value, stop_reason=stop_reason
                                    )
                                    await svc.send_event(
                                        session_id,
                                        "session.status_idle",
                                        {"stop_reason": stop_reason},
                                    )
                                broadcaster = get_session_broadcaster()
                                if broadcaster:
                                    await broadcaster.send(
                                        session_id,
                                        {"type": "session.status_idle", "stop_reason": stop_reason},
                                    )
                        continue

                    persisted_event_id = uuid7() if session_id else None

                    if self._event_bus and session_id:
                        await self._event_bus.publish(ConductorEventEnvelope(
                            session_id=session_id,
                            event_type=mapped_type,
                            payload=mapped_payload,
                            task_id=task_id,
                            sandbox_id=sandbox_id,
                            event_id=persisted_event_id,
                            seq=event.seq,
                            task_broadcast_payload={"type": mapped_type, **mapped_payload},
                        ))
                    else:
                        ws_msg = WsOutMessage(
                            type="event",
                            payload={"type": mapped_type, **mapped_payload},
                        )
                        await bridge.broadcast_to_task(task_id, ws_msg)

                        coordinator = get_redis_coordinator()
                        if coordinator:
                            await coordinator.publish_event(
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
                                    {**{"type": mapped_type, "seq": event.seq}, **(mapped_payload if isinstance(mapped_payload, dict) else {})},
                                )

                    if session_id and persisted_event_id:
                        if mapped_type in ("agent.tool_use", "agent.mcp_tool_use", "agent.custom_tool_use"):
                            last_tool_use_event_id = f"evt_{persisted_event_id}"

                    is_custom_tool = mapped_type == "agent.custom_tool_use"
                    if is_custom_tool and not requires_action_pending:
                        call_id = mapped_payload.get("_call_id") or mapped_payload.get("request_id") or mapped_payload.get("id") or mapped_payload.get("call_id") or ""
                        event_id = last_tool_use_event_id or f"evt_{uuid7()}"
                        if call_id:
                            bridge.pending_control_request_ids[event_id] = call_id
                        requires_action_pending = True
                        bridge._requires_action_pending = True
                        if session_id:
                            await self._event_buffer.flush()
                            stop_reason = {"type": "requires_action", "event_ids": [event_id]}
                            if self._event_bus:
                                await self._event_bus.publish(ConductorEventEnvelope(
                                    session_id=session_id,
                                    event_type="session.status_idle",
                                    payload={"stop_reason": stop_reason},
                                    is_status_change=True,
                                    stop_reason=stop_reason,
                                    task_id=task_id,
                                    sandbox_id=sandbox_id,
                                ))
                            else:
                                async with AsyncSessionLocal() as db:
                                    svc = SessionService(db)
                                    await svc.update_session_status(
                                        session_id, SessionStatus.IDLE.value, stop_reason=stop_reason
                                    )
                                    await svc.send_event(
                                        session_id,
                                        "session.status_idle",
                                        {"stop_reason": stop_reason},
                                    )
                                broadcaster = get_session_broadcaster()
                                if broadcaster:
                                    await broadcaster.send(
                                        session_id,
                                        {"type": "session.status_idle", "stop_reason": stop_reason},
                                    )

            elif payload_type == "result":
                result = msg.result
                logger.info("Result received: task=%s status=%s got_idle=%s", task_id, result.status, got_idle)
                await self._handle_result(bridge, sandbox_id, task_id, session_id, result)
                result_status = TaskStatus.from_str_lossy(result.status)
                if result_status == TaskStatus.COMPLETED:
                    task_completed = True
                elif result_status in (TaskStatus.FAILED, TaskStatus.ABORTED, TaskStatus.TIMEOUT):
                    task_error_status = True
                task_done = True
                logger.info("Result processed: task=%s task_done=%s got_idle=%s", task_id, task_done, got_idle)

            elif payload_type == "idle":
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
                        svc = SessionService(db)
                        await svc.update_session_sandbox(
                            linked_session_id, sandbox_id,
                            harness_session_id=harness_session_id,
                            work_dir=work_dir,
                        )

                from app.core.lifespan import get_redis_coordinator as _get_rc
                coord = _get_rc()
                if coord:
                    await coord.refresh_sandbox_owner(sandbox_id)

                # Flush buffered events BEFORE setting session idle (Rust lines 1226-1230)
                # This ensures all agent events are in PG when clients see session.status_idle
                await self._event_buffer.flush()

                if session_id and not bridge._requires_action_pending:
                    final_status = getattr(bridge, "_last_result_status", None)
                    last_error = getattr(bridge, "_last_result_error", None)
                    stop_reason = self._stop_reason_from_result(final_status, last_error) if final_status else {"type": "end_turn"}
                    if self._event_bus:
                        await self._event_bus.publish(ConductorEventEnvelope(
                            session_id=session_id,
                            event_type="session.status_idle",
                            payload={"stop_reason": stop_reason},
                            is_status_change=True,
                            stop_reason=stop_reason,
                            task_id=task_id,
                            sandbox_id=sandbox_id,
                        ))
                    else:
                        async with AsyncSessionLocal() as db:
                            svc = SessionService(db)
                            await svc.update_session_status(
                                session_id, SessionStatus.IDLE.value, stop_reason=stop_reason
                            )
                            await svc.send_event(
                                session_id,
                                "session.status_idle",
                                {"stop_reason": stop_reason},
                            )
                        broadcaster = get_session_broadcaster()
                        if broadcaster:
                            await broadcaster.send(
                                session_id,
                                {"type": "session.status_idle", "stop_reason": stop_reason},
                            )

                got_idle = True

            elif payload_type == "memory_sync":
                ms = msg.memory_sync
                asyncio.create_task(_handle_memory_sync_standalone(session_id, {
                    "store_mount_name": ms.store_mount_name,
                    "relative_path": ms.relative_path,
                    "content": ms.content,
                    "operation": ms.operation,
                }))

            if task_done and got_idle:
                break

        # --- Post-task ---
        logger.info("Post-task: task=%s task_done=%s got_idle=%s deadline=%s error=%s completed=%s", task_id, task_done, got_idle, deadline_exceeded, task_error_status, task_completed)
        if not task_done:
            await self._event_buffer.flush()
            last_err = bridge.last_error
            if last_err:
                reason = f"Sandbox disconnected unexpectedly (last error: {last_err})"
            else:
                reason = "Sandbox disconnected unexpectedly"
            retry_count = await TaskController.failover_or_fail_task(
                task_id, reason
            )
            if retry_count is not None:
                failover_pending_tasks.append((task_id, retry_count))
            bridge.remove_task_subscribers(task_id)
            from app.core.lifespan import get_redis_coordinator as _get_rc2
            _coord2 = _get_rc2()
            if _coord2:
                await _coord2.remove_task_sandbox(task_id)
            return (False, deadline_exceeded, False, False)

        if task_done and not got_idle:
            bridge.status = SandboxBridgeStatus.DISCONNECTED
            bridge.current_task_id = None
            bridge.remove_task_subscribers(task_id)
            from app.core.lifespan import get_redis_coordinator
            coordinator = get_redis_coordinator()
            if coordinator:
                await coordinator.remove_task_sandbox(task_id)
            if linked_session_id:
                stop_reason = {"type": "end_turn"}
                if deadline_exceeded:
                    stop_reason = {"type": "timeout"}
                elif task_error_status:
                    stop_reason = {"type": "error", "message": "Task failed"}
                if self._event_bus:
                    await self._event_bus.publish(ConductorEventEnvelope(
                        session_id=linked_session_id,
                        event_type="session.status_idle",
                        payload={"stop_reason": stop_reason},
                        is_status_change=True,
                        stop_reason=stop_reason,
                        task_id=task_id,
                        sandbox_id=sandbox_id,
                    ))
                else:
                    async with AsyncSessionLocal() as db:
                        svc = SessionService(db)
                        cas_ok = await svc.update_session_status(
                            linked_session_id, SessionStatus.IDLE.value, stop_reason=stop_reason
                        )
                        if cas_ok:
                            await svc.send_event(
                                linked_session_id,
                                "session.status_idle",
                                {"stop_reason": stop_reason},
                            )
                            broadcaster = get_session_broadcaster()
                            if broadcaster:
                                await broadcaster.send(
                                    linked_session_id,
                                    {"type": "session.status_idle", "stop_reason": stop_reason},
                                )
            return (False, deadline_exceeded, task_error_status, task_completed)

        return (True, deadline_exceeded, task_error_status, task_completed)

    async def _handle_result(
        self,
        bridge: SandboxBridge,
        sandbox_id: uuid.UUID,
        task_id: uuid.UUID,
        session_id: Optional[uuid.UUID],
        result: conductor_pb2.RunnerHarnessResult,
    ) -> None:
        from app.core.database import AsyncSessionLocal
        from app.models.task import ConductorTaskStatus as TaskStatus
        from app.models.session import SessionStatus
        from app.services.task_service import ConductorTaskService as TaskService
        from app.services.session_service import SessionService
        from app.services.sandbox_service import SandboxService

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

        cas_ok = True
        async with AsyncSessionLocal() as db:
            task_svc = TaskService(db)
            if final_status.is_terminal():
                if error:
                    cas_ok = await task_svc.update_task_error(
                        task_id, error, final_status,
                    )
                else:
                    cas_ok = await task_svc.update_task_status(
                        task_id, final_status,
                    )
                if not cas_ok:
                    logger.warning("CAS conflict: task %s already terminal, ignoring runner result", task_id)

            if cas_ok:
                await task_svc.update_task_output(task_id, result.output)
                if usage:
                    await task_svc.update_task_usage(task_id, usage)

            sandbox_svc = SandboxService(db)
            await sandbox_svc.complete_task(sandbox_id, task_id, "idle")

            if session_id and usage:
                session_svc = SessionService(db)
                await session_svc.accumulate_usage(session_id, {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cache_creation_input_tokens": usage.get("cache_write_tokens", 0),
                    "cache_read_input_tokens": usage.get("cache_read_tokens", 0),
                })

        from app.core.lifespan import get_redis_coordinator, get_session_broadcaster

        result_payload = {
            "status": result.status,
            "output": result.output,
            "error": error,
            "duration_ms": result.duration_ms,
        }
        await bridge.broadcast_to_task(
            task_id, WsOutMessage(type="complete", payload=result_payload)
        )

        # Issue 4 fix: publish complete event to Redis (matching Rust lines 1197-1199)
        coordinator = get_redis_coordinator()
        if coordinator:
            await coordinator.publish_event(
                task_id,
                json.dumps({"type": "complete", **result_payload}),
            )

        bridge.remove_task_subscribers(task_id)

        if coordinator:
            await coordinator.remove_task_sandbox(task_id)

        # Store result info so the idle handler can compute stop_reason
        bridge._last_result_status = final_status
        bridge._last_result_error = error

        logger.info("Task %s completed: status=%s", task_id, result.status)

    @staticmethod
    def _stop_reason_from_result(status: "TaskStatus", error: Optional[str]) -> dict:
        from app.models.task import ConductorTaskStatus as TaskStatus
        if status == TaskStatus.COMPLETED:
            return {"type": "end_turn"}
        elif status == TaskStatus.TIMEOUT:
            return {"type": "timeout"}
        elif status == TaskStatus.CANCELLED:
            return {"type": "cancelled"}
        elif status in (TaskStatus.FAILED, TaskStatus.ABORTED):
            return {"type": "error", "message": error}
        return {"type": "end_turn"}

    async def _handle_reconnect_result(
        self,
        bridge: SandboxBridge,
        sandbox_id: uuid.UUID,
        task_id: uuid.UUID,
        session_id: Optional[uuid.UUID],
        result,
        coordinator,
    ) -> None:
        """Reconnect result handler — with CAS check and event buffer flush."""
        from app.core.database import AsyncSessionLocal
        from app.models.task import ConductorTaskStatus as TaskStatus
        from app.services.task_service import ConductorTaskService as TaskService
        from app.services.session_service import SessionService
        from app.services.sandbox_service import SandboxService
        from app.core.lifespan import get_session_broadcaster

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

        cas_ok = True
        async with AsyncSessionLocal() as db:
            task_svc = TaskService(db)
            if final_status.is_terminal():
                if error:
                    cas_ok = await task_svc.update_task_error(task_id, error, final_status)
                else:
                    cas_ok = await task_svc.update_task_status(task_id, final_status)
                if not cas_ok:
                    logger.warning("CAS conflict: reconnect task %s already terminal, ignoring result", task_id)
            if cas_ok:
                await task_svc.update_task_output(task_id, result.output)
                if usage:
                    await task_svc.update_task_usage(task_id, usage)

        result_payload = {
            "status": result.status,
            "output": result.output,
            "error": error,
            "duration_ms": result.duration_ms,
        }
        await bridge.broadcast_to_task(
            task_id, WsOutMessage(type="complete", payload=result_payload)
        )

        if coordinator:
            await coordinator.publish_event(
                task_id,
                json.dumps({"type": "complete", **result_payload}),
            )

        async with AsyncSessionLocal() as db:
            sandbox_svc = SandboxService(db)
            await sandbox_svc.complete_task(sandbox_id, task_id, "idle")

        bridge.remove_task_subscribers(task_id)

        if coordinator:
            await coordinator.remove_task_sandbox(task_id)

        await self._event_buffer.flush()

        if session_id:
            if not bridge._requires_action_pending:
                stop_reason = self._stop_reason_from_result(final_status, error)
                if self._event_bus:
                    await self._event_bus.publish(ConductorEventEnvelope(
                        session_id=session_id,
                        event_type="session.status_idle",
                        payload={"stop_reason": stop_reason},
                        is_status_change=True,
                        stop_reason=stop_reason,
                        task_id=task_id,
                        sandbox_id=sandbox_id,
                    ))
                else:
                    async with AsyncSessionLocal() as db:
                        session_svc = SessionService(db)
                        await session_svc.update_session_status(
                            session_id, SessionStatus.IDLE.value, stop_reason=stop_reason
                        )

                    async with AsyncSessionLocal() as db:
                        session_svc = SessionService(db)
                        await session_svc.send_event(
                            session_id,
                            "session.status_idle",
                            {"stop_reason": stop_reason},
                        )
                    broadcaster = get_session_broadcaster()
                    if broadcaster:
                        await broadcaster.send(
                            session_id,
                            {"type": "session.status_idle", "stop_reason": stop_reason},
                        )

            if usage:
                async with AsyncSessionLocal() as db:
                    session_svc = SessionService(db)
                    await session_svc.accumulate_usage(session_id, {
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "cache_creation_input_tokens": usage.get("cache_write_tokens", 0),
                        "cache_read_input_tokens": usage.get("cache_read_tokens", 0),
                    })

        logger.info("Reconnect task %s completed: status=%s", task_id, result.status)

    async def _send_setup(self, bridge: SandboxBridge, sandbox_id: uuid.UUID) -> None:
        if bridge.setup_done:
            return

        from app.core.database import AsyncSessionLocal
        from app.services.sandbox_service import SandboxService
        from app.services.session_service import SessionService
        from app.services.agent_service import ConductorAgentService as AgentService

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
                agent = await agent_svc.get_agent(session.agent_id)
                if not agent:
                    bridge.setup_done = True
                    return

                from app.core.harness_input_builder import build_harness_input

                class _FakeTask:
                    prompt = ""
                    system_prompt = agent.system_prompt

                harness_input = await build_harness_input(
                    _FakeTask(), agent, sandbox.chat_session_id,
                    bridge.external_id, sandbox_id,
                )

                environment = None
                env_ref = getattr(agent, "environment_ref", None)
                if env_ref:
                    from app.services.conductor_environment_service import EnvironmentService
                    env_svc = EnvironmentService(db)
                    environment = await env_svc.get_environment_by_ref(env_ref)

                # workspace_path on the record is the HOST path; inside the container it's always /workspace
                work_dir = session.last_work_dir or (
                    "/workspace" if getattr(sandbox, "workspace_path", None) else None
                )

            setup_msg = _build_setup_sandbox(harness_input, agent, environment, work_dir=work_dir)
            orch_msg = conductor_pb2.OrchestratorMessage(setup=setup_msg)
            await bridge.runner_stream.write(orch_msg)
            bridge.setup_done = True
            logger.info("SetupSandbox sent for sandbox %s", sandbox_id)

        except Exception as e:
            logger.warning("Failed to send SetupSandbox for %s: %s", sandbox_id, e)
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
        from app.core.lifespan import get_sandbox_provider

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
            await self._execute_sandbox_cleanup(sandbox_id, session_id, failover_pending_tasks, is_error, container_dead=True)
            return

        # Second probe after 2s
        await asyncio.sleep(2)
        container_dead = await self._probe_container(provider, sandbox_id, external_id=external_id)
        if container_dead:
            logger.info("Container dead on retry for sandbox %s", sandbox_id)
            await self._execute_sandbox_cleanup(sandbox_id, session_id, failover_pending_tasks, is_error, container_dead=True)
            return

        # Container is alive -- start 120s reconnection grace period
        logger.info("Runner disconnected from sandbox %s, starting 120s grace period", sandbox_id)

        current_bridge = await self._bridge_registry.get(sandbox_id)

        asyncio.create_task(
            self._grace_period_cleanup(
                sandbox_id, session_id, failover_pending_tasks, is_error, current_bridge
            ),
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
        from app.core.database import AsyncSessionLocal
        from app.services.sandbox_service import SandboxService
        from app.services.task_service import ConductorTaskService as TaskService
        from app.services.session_service import SessionService
        from app.core.task_controller import TaskController
        from app.core.lifespan import (
            get_redis_coordinator,
            get_session_broadcaster,
            get_memory_subscribers,
        )

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

        # 3. Reset scheduling tasks to pending
        async with AsyncSessionLocal() as db:
            task_svc = TaskService(db)
            n = await task_svc.reset_sandbox_tasks_to_pending(sandbox_id)
            if n > 0:
                logger.info(
                    "Reset %d scheduling tasks to pending for dead sandbox %s", n, sandbox_id
                )

        # 4. Drain and requeue sandbox queue
        await self._queue.drain_and_requeue_sandbox(sandbox_id)

        # 5. Schedule delayed retry for failover_pending_tasks
        has_retries = len(failover_pending_tasks) > 0
        for tid, retry_count in failover_pending_tasks:
            delay = TaskController.compute_retry_delay(retry_count, tid)
            logger.info(
                "Scheduling delayed retry for task %s: retry_count=%d delay=%.1fs",
                tid, retry_count, delay,
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
            await coordinator.remove_sandbox_owner(sandbox_id)
            await coordinator.remove_sandbox_queue(sandbox_id)

        # 7. Emit session status event BEFORE removing broadcaster
        if session_id:
            if has_retries:
                if self._event_bus:
                    await self._event_bus.publish(ConductorEventEnvelope(
                        session_id=session_id,
                        event_type="session.status_rescheduling",
                        payload={"stop_reason": {"type": "sandbox_failed"}},
                        is_status_change=True,
                        stop_reason={"type": "sandbox_failed"},
                        sandbox_id=sandbox_id,
                    ))
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
            else:
                async with AsyncSessionLocal() as db:
                    session_svc = SessionService(db)
                    session_rec = await session_svc.get_session(session_id)
                    session_is_idle = (
                        session_rec is not None
                        and session_rec.status == "idle"
                    )
                if session_rec is None:
                    logger.debug(
                        "Session %s already deleted, skipping disconnect event",
                        session_id,
                    )
                elif not session_is_idle:
                    if self._event_bus:
                        await self._event_bus.publish(ConductorEventEnvelope(
                            session_id=session_id,
                            event_type="session.status_terminated",
                            payload={"stop_reason": {"type": "sandbox_disconnected"}},
                            is_status_change=True,
                            stop_reason={"type": "sandbox_disconnected"},
                            sandbox_id=sandbox_id,
                        ))
                    else:
                        async with AsyncSessionLocal() as db:
                            session_svc = SessionService(db)
                            await session_svc.update_session_status(session_id, "terminated")
                            await session_svc.send_event(
                                session_id,
                                "session.status_terminated",
                                {"stop_reason": {"type": "sandbox_disconnected"}},
                            )
                        broadcaster = get_session_broadcaster()
                        if broadcaster:
                            await broadcaster.send(
                                session_id,
                                {"type": "session.status_terminated", "stop_reason": {"type": "sandbox_disconnected"}},
                            )

        # 8. Unregister memory subscribers
        if session_id:
            mem_subs = get_memory_subscribers()
            if mem_subs:
                await mem_subs.unregister_session(session_id)

        # 9. Remove session broadcaster (no-op in Python -- broadcaster is shared)

        logger.info(
            "SandboxBridge cleanup completed: sandbox=%s status=%s", sandbox_id, sandbox_status
        )

    async def _probe_container(self, provider, sandbox_id: uuid.UUID, external_id: Optional[str] = None) -> bool:
        if not external_id:
            from app.core.database import AsyncSessionLocal
            from app.services.sandbox_service import SandboxService
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
            return status != "running"
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
        """120s grace period for reconnection, matching Rust lines 1441-1500."""
        from app.core.task_controller import TaskController

        # Check early for reconnection before waiting the full 120s
        for early_check in (5, 10, 15):
            await asyncio.sleep(early_check)
            current_bridge = await self._bridge_registry.get(sandbox_id)
            if current_bridge is not None and current_bridge is not original_bridge:
                logger.info("Bridge replaced by early reconnection for sandbox %s, re-queuing %d task(s)", sandbox_id, len(failover_pending_tasks))
                for tid, _retry_count in failover_pending_tasks:
                    await self._queue.push_to_global(tid)
                    logger.info("Re-queued orphaned task %s immediately after reconnect", tid)
                return

        remaining = 120 - 30
        await asyncio.sleep(remaining)

        # Check if a new connection replaced this bridge
        current_bridge = await self._bridge_registry.get(sandbox_id)
        if current_bridge is not None and current_bridge is not original_bridge:
            logger.info("Bridge replaced by reconnection for sandbox %s, skipping cleanup", sandbox_id)
            for tid, _retry_count in failover_pending_tasks:
                await self._queue.push_to_global(tid)
                logger.info("Re-queued orphaned task %s after reconnect", tid)
            return

        logger.warning("No reconnection within grace period for sandbox %s, cleaning up", sandbox_id)
        await self._execute_sandbox_cleanup(sandbox_id, session_id, failover_pending_tasks, is_error)


# --- Fix 3: Memory sync with cross-session peer broadcast ---

async def _handle_memory_sync_standalone(
    session_id: Optional[uuid.UUID], payload: dict
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

        store_id_for_broadcast: Optional[uuid.UUID] = None

        async with AsyncSessionLocal() as db:
            session_svc = SessionService(db)
            mounts = await session_svc.list_session_memory_stores(session_id)

            for sms in mounts:
                if sms.mount_name != mount_name:
                    continue
                if sms.access == "read_only":
                    logger.warning(
                        "Ignoring write to read_only memory store mount=%s", mount_name
                    )
                    return

                mem_svc = MemoryService(db)
                if operation == "delete":
                    existing = await mem_svc.get_memory_by_path(sms.store_id, rel_path)
                    if existing:
                        await mem_svc.delete_memory(sms.store_id, existing.id, session_id)
                else:
                    await mem_svc.upsert_memory_from_agent(
                        sms.store_id, rel_path, content, session_id
                    )

                store_id_for_broadcast = sms.store_id
                break

        # Cross-session broadcast: notify peer sessions sharing this store (Rust lines 1330-1352)
        if store_id_for_broadcast is not None:
            from app.core.lifespan import get_memory_subscribers, get_bridge_registry
            mem_subs = get_memory_subscribers()
            bridge_registry = get_bridge_registry()

            if mem_subs and bridge_registry:
                peers = await mem_subs.get_peers(store_id_for_broadcast, session_id)
                for peer in peers:
                    peer_bridge = await bridge_registry.get(peer.sandbox_db_id)
                    if peer_bridge and peer_bridge.runner_stream:
                        try:
                            update_msg = conductor_pb2.OrchestratorMessage(
                                memory_update=conductor_pb2.MemoryFileUpdate(
                                    store_mount_name=peer.mount_name,
                                    relative_path=rel_path,
                                    content=content.encode("utf-8") if isinstance(content, str) else content,
                                    operation=operation,
                                )
                            )
                            await peer_bridge.runner_stream.write(update_msg)
                        except Exception as e:
                            logger.warning(
                                "Failed to send MemoryFileUpdate to peer session %s: %s",
                                peer.session_id, e,
                            )

    except Exception as e:
        logger.warning("Memory sync failed: %s", e)


def _extract_setup_commands(agent=None, environment=None) -> list[str]:
    """Extract setup_commands from environment config (packages.install_commands)
    and agent metadata.  Returns a combined list."""
    commands: list[str] = []

    if environment and getattr(environment, "config", None):
        env_config = environment.config
        if isinstance(env_config, dict):
            packages = env_config.get("packages", {})
            if isinstance(packages, dict):
                from app.schemas.environment import Packages
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


def _build_setup_sandbox(
    harness_input, agent, environment=None, work_dir=None,
) -> conductor_pb2.SetupSandbox:
    skills = []
    for sa in harness_input.skill_archives:
        skills.append(conductor_pb2.SkillArchive(
            name=sa.name,
            tar_gz=sa.data,
            target=sa.target,
        ))

    mcp_servers = []
    for cfg in harness_input.mcp_servers:
        mcp_servers.append(conductor_pb2.McpConfig(
            name=cfg.get("name", ""),
            command=cfg.get("command", ""),
            args=cfg.get("args", []),
            env=cfg.get("env", {}),
            server_type=cfg.get("server_type", ""),
            url=cfg.get("url", ""),
            headers=cfg.get("headers", {}),
        ))

    custom_tools = []
    for ct in harness_input.custom_tools:
        input_schema = ct.get("input_schema", {})
        schema_json = json.dumps(input_schema) if isinstance(input_schema, dict) else str(input_schema)
        custom_tools.append(conductor_pb2.CustomTool(
            name=ct["name"],
            description=ct.get("description", ""),
            input_schema_json=schema_json,
        ))

    memory_mounts = []
    for mm in harness_input.memory_mounts:
        files = []
        for f in mm.get("files", []):
            content = f.get("content", "")
            if isinstance(content, str):
                content = content.encode("utf-8")
            files.append(conductor_pb2.MemoryFile(
                relative_path=f.get("path", ""),
                content=content,
            ))
        memory_mounts.append(conductor_pb2.MemoryStoreMount(
            store_id=mm.get("store_id", ""),
            mount_name=mm.get("mount_name", ""),
            mount_path=f"/mnt/memory/{mm.get('mount_name', '')}",
            access=mm.get("access", "read_write"),
            files=files,
        ))

    kwargs = dict(
        skills=skills,
        mcp_servers=mcp_servers,
        custom_tools=custom_tools,
        setup_commands=[],
        env=harness_input.env,
        secrets=harness_input.secrets,
        permission_mode=harness_input.permission_mode,
        provider=str(agent.engine_kind) if agent else "",
        model=harness_input.model or "",
        memory_system_prompt=harness_input.memory_system_prompt or "",
        memory_mounts=memory_mounts,
    )
    if work_dir:
        kwargs["work_dir"] = work_dir
    return conductor_pb2.SetupSandbox(**kwargs)


def _build_start_task(
    task_id: uuid.UUID,
    harness_input,
    task,
    config,
    agent=None,
    session=None,
    environment=None,
) -> conductor_pb2.StartTask:
    skills = []
    for sa in harness_input.skill_archives:
        skills.append(conductor_pb2.SkillArchive(
            name=sa.name,
            tar_gz=sa.data,
            target=sa.target,
        ))

    mcp_servers = []
    for cfg in harness_input.mcp_servers:
        mcp_servers.append(conductor_pb2.McpConfig(
            name=cfg.get("name", ""),
            command=cfg.get("command", ""),
            args=cfg.get("args", []),
            env=cfg.get("env", {}),
            server_type=cfg.get("server_type", ""),
            url=cfg.get("url", ""),
            headers=cfg.get("headers", {}),
        ))

    custom_tools = []
    for ct in harness_input.custom_tools:
        input_schema = ct.get("input_schema", {})
        schema_json = json.dumps(input_schema) if isinstance(input_schema, dict) else str(input_schema)
        custom_tools.append(conductor_pb2.CustomTool(
            name=ct["name"],
            description=ct.get("description", ""),
            input_schema_json=schema_json,
        ))

    allowed = []
    disallowed = []
    for tool in (harness_input.tools or []):
        if isinstance(tool, dict) and tool.get("type") == "agent_toolset_20260401":
            for tcfg in tool.get("configs", []):
                if isinstance(tcfg, dict):
                    name = tcfg.get("name", "")
                    if tcfg.get("enabled", True):
                        allowed.append(name)
                    else:
                        disallowed.append(name)

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
        secrets=harness_input.secrets,
        mcp_servers=mcp_servers,
        skills=skills,
        allowed_tools=allowed,
        disallowed_tools=disallowed,
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

    repos = []
    if agent and getattr(agent, "metadata_", None):
        agent_repos = agent.metadata_.get("repos")
        if isinstance(agent_repos, list):
            for repo_cfg in agent_repos:
                if isinstance(repo_cfg, dict) and repo_cfg.get("url"):
                    repos.append(conductor_pb2.RepoConfig(
                        url=repo_cfg.get("url", ""),
                        branch=repo_cfg.get("branch", ""),
                        path=repo_cfg.get("path", ""),
                    ))
    if repos:
        kwargs["repos"] = repos

    setup_commands = _extract_setup_commands(agent, environment)
    if setup_commands:
        kwargs["setup_commands"] = setup_commands

    return conductor_pb2.StartTask(**kwargs)


def _proto_event_to_dict(event: conductor_pb2.RunnerHarnessEvent) -> dict[str, Any]:
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
                "content": [{
                    "type": "tool_use",
                    "name": tu.tool,
                    "id": tu.call_id,
                    "input": input_data,
                }],
            },
        }
    elif event_field == "tool_result":
        tr = event.tool_result
        return {
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tr.call_id,
                    "name": tr.tool,
                    "content": tr.output,
                }],
            },
        }
    elif event_field == "error":
        return {"type": "error", "error": event.error.message}
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
    server = grpc_aio.server()
    servicer = AgentBridgeServicer(
        bridge_registry, event_buffer, queue,
        vault_provider=vault_provider,
        execution_semaphore=execution_semaphore,
        event_bus=event_bus,
    )
    conductor_pb2_grpc.add_AgentBridgeServicer_to_server(servicer, server)
    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    logger.info("gRPC server started on %s:%d", host, port)
    return server, servicer
