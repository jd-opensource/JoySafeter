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

import grpc
from grpc import aio as grpc_aio

from app.conductor.proto import conductor_pb2, conductor_pb2_grpc
from app.conductor.kernel.sandbox_bridge import (
    SandboxBridge,
    SandboxBridgeRegistry,
    SandboxBridgeStatus,
    WsOutMessage,
)
from app.conductor.kernel.event_buffer import BufferedEvent, EventBatchSender
from app.conductor.kernel.queue import QueueBackend

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT_SEC = 120
TASK_DEFAULT_TIMEOUT_SEC = 7200


class AgentBridgeServicer(conductor_pb2_grpc.AgentBridgeServicer):
    def __init__(
        self,
        bridge_registry: SandboxBridgeRegistry,
        event_buffer: EventBatchSender,
        queue: QueueBackend,
        vault_provider: Optional[Any] = None,
    ):
        self._bridge_registry = bridge_registry
        self._event_buffer = event_buffer
        self._queue = queue
        self._vault_provider = vault_provider

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

            # Register bridge
            bridge = await self._bridge_registry.get(sandbox_id)
            if not bridge:
                bridge = await self._bridge_registry.register(sandbox_id, str(sandbox_id))

            bridge.runner_stream = context
            bridge.runner_connected.set()
            bridge.status = SandboxBridgeStatus.IDLE

            # --- Handle reconnection with active_task_id ---
            if ready.HasField("active_task_id") and ready.active_task_id:
                await self._handle_reconnect_active_task(
                    bridge, sandbox_id, ready.active_task_id, context, stream_cancel,
                )

            # --- Send SetupSandbox ---
            await self._send_setup(bridge, sandbox_id)

            # --- Outer task-dispatch loop (matches agentd) ---
            # Blocks on pop_for_sandbox until a task arrives or stream disconnects.
            await self._multi_task_loop(bridge, sandbox_id, context, stream_cancel)

        except grpc_aio.AioRpcError as e:
            logger.info("gRPC stream ended for sandbox %s: %s", sandbox_id, e.code())
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
                await self._cleanup_sandbox(sandbox_id)

    async def _handle_reconnect_active_task(
        self,
        bridge: SandboxBridge,
        sandbox_id: uuid.UUID,
        active_task_id_str: str,
        context,
        stream_cancel: asyncio.Event,
    ) -> None:
        """Handle RunnerReady.active_task_id: the runner reconnected while still
        executing a task.  Re-attach the bridge so events continue flowing."""
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.task import TaskStatus
        from app.conductor.services.task_service import TaskService

        try:
            active_task_id = uuid.UUID(active_task_id_str)
        except ValueError:
            logger.warning(
                "Invalid active_task_id on reconnect: %s", active_task_id_str,
            )
            return

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

        logger.info(
            "Reconnect: resuming in-flight task %s on sandbox %s",
            active_task_id, sandbox_id,
        )
        bridge.status = SandboxBridgeStatus.BUSY
        bridge.current_task_id = active_task_id

    async def _multi_task_loop(
        self,
        bridge: SandboxBridge,
        sandbox_id: uuid.UUID,
        context,
        stream_cancel: asyncio.Event,
    ) -> None:
        """Outer loop: block on pop_for_sandbox, dispatch tasks one at a time.

        Matches agentd grpc.rs lines 651-680. Uses pop_for_sandbox which blocks
        until a task arrives or stream_cancel is set. While waiting, a background
        reader drains heartbeats and detects disconnect. The reader is CANCELLED
        before entering the per-task loop (only one reader can be active at a time).
        """
        while not stream_cancel.is_set():
            # Spawn background reader for idle phase (heartbeats + disconnect detect)
            idle_cancel = asyncio.Event()

            async def _idle_reader():
                try:
                    while not idle_cancel.is_set():
                        msg = await context.read()
                        if msg == grpc_aio.EOF:
                            stream_cancel.set()
                            return
                        payload_type = msg.WhichOneof("payload")
                        if payload_type == "heartbeat":
                            continue
                except Exception:
                    stream_cancel.set()

            reader_task = asyncio.create_task(
                _idle_reader(), name=f"idle-reader-{sandbox_id}"
            )

            # Block on pop_for_sandbox — wakes when task arrives or stream dies
            task_id = await self._queue.pop_for_sandbox(sandbox_id, stream_cancel)

            # Cancel the idle reader BEFORE entering per-task loop
            idle_cancel.set()
            reader_task.cancel()
            try:
                await reader_task
            except (asyncio.CancelledError, Exception):
                pass

            if task_id is None:
                logger.info("Pop cancelled for sandbox %s (stream dead or shutdown)", sandbox_id)
                break

            # Dispatch this task — has exclusive ownership of context.read()
            success = await self._run_single_task(bridge, sandbox_id, context, task_id, stream_cancel)
            if not success:
                break

    async def _run_single_task(
        self,
        bridge: SandboxBridge,
        sandbox_id: uuid.UUID,
        context,
        task_id: uuid.UUID,
        stream_cancel: asyncio.Event,
    ) -> bool:
        """Inner per-task loop: send StartTask, read events until Result+Idle.

        Returns True if the task completed normally and outer loop should continue.
        Returns False if the stream broke and outer loop should exit.
        """
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.task import TaskStatus
        from app.conductor.models.session import SessionStatus
        from app.conductor.services.task_service import TaskService
        from app.conductor.services.agent_service import AgentService
        from app.conductor.services.session_service import SessionService
        from app.conductor.services.sandbox_service import SandboxService
        from app.conductor.kernel.harness_input_builder import build_harness_input, extract_tool_name_sets
        from app.conductor.kernel.event_mapping import map_harness_event, is_control_request
        from app.conductor.config import conductor_config

        logger.info("Dispatching task %s to sandbox %s", task_id, sandbox_id)

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
                    return True

                agent = await agent_svc.get_agent(task.agent_id)
                if not agent:
                    await task_svc.update_task_status(task_id, TaskStatus.FAILED, error="Agent not found")
                    bridge.current_task_id = None
                    bridge.status = SandboxBridgeStatus.IDLE
                    return True

                await task_svc.update_task_status(task_id, TaskStatus.RUNNING)

                session_id = task.chat_session_id
                if session_id:
                    await session_svc.update_session_status(session_id, SessionStatus.RUNNING.value)

                await sandbox_svc.touch(sandbox_id, task_id)

                # Fetch session for work_dir and environment for setup_commands/repos
                session = None
                environment = None
                if session_id:
                    session = await session_svc.get_session(session_id)

                env_ref = getattr(agent, "environment_ref", None)
                if env_ref:
                    from app.conductor.services.environment_service import EnvironmentService
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

        except Exception as e:
            logger.error("Failed to dispatch task %s: %s", task_id, e)
            bridge.current_task_id = None
            bridge.status = SandboxBridgeStatus.IDLE
            from app.conductor.kernel.task_controller import TaskController
            await TaskController.failover_or_fail_task(task_id, str(e))
            return True

        # --- Inner per-task event loop ---
        task_done = False
        got_idle = False
        requires_action_pending = False
        timeout = task.timeout_sec or conductor_config.task_default_timeout
        last_tool_use_event_id: Optional[str] = None

        from app.conductor.lifespan import get_session_broadcaster, get_redis_coordinator

        while True:
            # Select: read stream message | confirmation | heartbeat timeout | task deadline
            read_fut = asyncio.ensure_future(context.read())
            confirm_fut = asyncio.ensure_future(bridge.confirmation_event.wait())
            heartbeat_fut = asyncio.ensure_future(asyncio.sleep(HEARTBEAT_TIMEOUT_SEC))
            deadline_fut = asyncio.ensure_future(asyncio.sleep(timeout))

            waitables = [read_fut, heartbeat_fut]
            if requires_action_pending:
                waitables.append(confirm_fut)
            else:
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

            # --- Confirmation received ---
            if confirm_fut in done and requires_action_pending:
                requires_action_pending = False
                bridge.confirmation_event.clear()
                bridge._requires_action_pending = False
                logger.info("Confirmation received for task %s, resuming", task_id)
                # Send any queued control inputs
                while not bridge._control_queue.empty():
                    try:
                        content = bridge._control_queue.get_nowait()
                        input_msg = conductor_pb2.OrchestratorMessage(
                            input=conductor_pb2.SendInput(content=content)
                        )
                        await context.write(input_msg)
                    except asyncio.QueueEmpty:
                        break
                if session_id:
                    async with AsyncSessionLocal() as db:
                        svc = SessionService(db)
                        await svc.update_session_status(session_id, SessionStatus.RUNNING.value)
                continue

            # --- Heartbeat timeout ---
            if heartbeat_fut in done:
                logger.warning("Heartbeat timeout during task %s: sandbox=%s", task_id, sandbox_id)
                from app.conductor.kernel.task_controller import TaskController
                await TaskController.failover_or_fail_task(task_id, "Heartbeat timeout — sandbox unresponsive")
                bridge.current_task_id = None
                bridge.status = SandboxBridgeStatus.IDLE
                return False

            # --- Task deadline ---
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
                    await task_svc.update_task_status(
                        task_id, TaskStatus.FAILED,
                        error=f"Task timed out after {timeout}s (server-side deadline)",
                    )
                task_done = True
                break

            # --- Stream message ---
            if read_fut not in done:
                continue
            msg = read_fut.result()
            if msg == grpc_aio.EOF:
                break

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

                    # control_request: pause for confirmation
                    if mapped_type in ("agent.tool_use", "agent.mcp_tool_use") and is_control_request(mapped_payload):
                        call_id = mapped_payload.get("request_id") or mapped_payload.get("id") or mapped_payload.get("call_id") or ""
                        event_id = last_tool_use_event_id or f"evt_{uuid.uuid4()}"
                        if call_id:
                            bridge.pending_control_request_ids[event_id] = call_id
                        requires_action_pending = True
                        bridge._requires_action_pending = True
                        if session_id:
                            stop_reason = {"type": "requires_action", "event_ids": [event_id]}
                            async with AsyncSessionLocal() as db:
                                svc = SessionService(db)
                                await svc.update_session_status(
                                    session_id, SessionStatus.IDLE.value, stop_reason=stop_reason
                                )
                            broadcaster = get_session_broadcaster()
                            if broadcaster:
                                await broadcaster.broadcast(
                                    session_id,
                                    {"type": "session.status_idle", "payload": {"stop_reason": stop_reason}},
                                )
                        continue

                    # custom_tool_use: also requires confirmation
                    is_custom_tool = mapped_type == "agent.custom_tool_use"
                    if is_custom_tool and not requires_action_pending:
                        call_id = mapped_payload.get("request_id") or mapped_payload.get("id") or mapped_payload.get("call_id") or ""
                        event_id = last_tool_use_event_id or f"evt_{uuid.uuid4()}"
                        if call_id:
                            bridge.pending_control_request_ids[event_id] = call_id
                        requires_action_pending = True
                        bridge._requires_action_pending = True
                        if session_id:
                            stop_reason = {"type": "requires_action", "event_ids": [event_id]}
                            async with AsyncSessionLocal() as db:
                                svc = SessionService(db)
                                await svc.update_session_status(
                                    session_id, SessionStatus.IDLE.value, stop_reason=stop_reason
                                )
                            broadcaster = get_session_broadcaster()
                            if broadcaster:
                                await broadcaster.broadcast(
                                    session_id,
                                    {"type": "session.status_idle", "payload": {"stop_reason": stop_reason}},
                                )

                    # Broadcast event
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

                    # Persist to session events
                    if session_id:
                        buffered = BufferedEvent(
                            session_id=session_id,
                            event_type=mapped_type,
                            payload=mapped_payload,
                            seq=event.seq,
                        )
                        await self._event_buffer.send(buffered)

                        broadcaster = get_session_broadcaster()
                        if broadcaster:
                            await broadcaster.broadcast(
                                session_id,
                                {"type": mapped_type, "payload": mapped_payload, "seq": event.seq},
                            )

                        # Track last tool_use event for control_request mapping
                        if mapped_type in ("agent.tool_use", "agent.mcp_tool_use", "agent.custom_tool_use"):
                            last_tool_use_event_id = f"evt_{uuid.uuid4()}"

            elif payload_type == "result":
                result = msg.result
                await self._handle_result(bridge, sandbox_id, task_id, session_id, result)
                task_done = True

            elif payload_type == "idle":
                idle = msg.idle
                bridge.status = SandboxBridgeStatus.IDLE
                bridge.current_task_id = None
                logger.info("Runner idle: sandbox=%s", sandbox_id)

                # Update session resume info
                if session_id:
                    harness_session_id = idle.session_id if idle.HasField("session_id") else None
                    work_dir = idle.work_dir if idle.HasField("work_dir") else None
                    async with AsyncSessionLocal() as db:
                        svc = SessionService(db)
                        await svc.update_session_sandbox(
                            session_id, sandbox_id,
                            harness_session_id=harness_session_id,
                            work_dir=work_dir,
                        )

                from app.conductor.lifespan import get_redis_coordinator as _get_rc
                coord = _get_rc()
                if coord:
                    await coord.refresh_sandbox_owner(sandbox_id)

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
        if not task_done:
            # Stream broke before task completed
            from app.conductor.kernel.task_controller import TaskController
            await TaskController.failover_or_fail_task(
                task_id, "Sandbox disconnected unexpectedly"
            )
            bridge.current_task_id = None
            bridge.status = SandboxBridgeStatus.IDLE
            return False

        if task_done and not got_idle:
            # Got result but no idle — still OK, proceed
            bridge.current_task_id = None
            bridge.status = SandboxBridgeStatus.IDLE

        # Check cancel event
        if bridge._cancel_event.is_set():
            bridge._cancel_event.clear()

        await self._event_buffer.flush()
        return True

    async def _handle_result(
        self,
        bridge: SandboxBridge,
        sandbox_id: uuid.UUID,
        task_id: uuid.UUID,
        session_id: Optional[uuid.UUID],
        result: conductor_pb2.RunnerHarnessResult,
    ) -> None:
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.task import TaskStatus
        from app.conductor.models.session import SessionStatus
        from app.conductor.services.task_service import TaskService
        from app.conductor.services.session_service import SessionService
        from app.conductor.services.sandbox_service import SandboxService

        usage = None
        if result.usage:
            usage = {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "cache_read_tokens": result.usage.cache_read_tokens,
                "cache_write_tokens": result.usage.cache_write_tokens,
            }

            # Parse per-model breakdown from repeated ModelUsageEntry
            if result.usage.by_model:
                by_model_list = []
                for entry in result.usage.by_model:
                    by_model_list.append({
                        "model": entry.model,
                        "input_tokens": entry.input_tokens,
                        "output_tokens": entry.output_tokens,
                        "cache_read_tokens": entry.cache_read_tokens,
                        "cache_write_tokens": entry.cache_write_tokens,
                    })
                usage["by_model"] = by_model_list

        error = result.error if result.HasField("error") else None
        final_status = TaskStatus.COMPLETED if not error else TaskStatus.FAILED

        async with AsyncSessionLocal() as db:
            task_svc = TaskService(db)
            await task_svc.update_task_status(
                task_id, final_status,
                output=result.output,
                error=error,
                usage=usage,
            )

            if session_id:
                session_svc = SessionService(db)
                if usage:
                    by_model = usage.get("by_model", [])
                    if by_model:
                        # Accumulate per-model entries individually. Each call
                        # to accumulate_usage adds to the session aggregate AND
                        # to the per-model map, so the aggregate is the natural
                        # sum of all model entries.
                        for model_entry in by_model:
                            await session_svc.accumulate_usage(session_id, {
                                "input_tokens": model_entry["input_tokens"],
                                "output_tokens": model_entry["output_tokens"],
                                "cache_creation_input_tokens": model_entry.get("cache_read_tokens", 0),
                                "cache_read_input_tokens": model_entry.get("cache_write_tokens", 0),
                                "model": model_entry["model"],
                            })
                    else:
                        # No per-model breakdown; accumulate aggregate only
                        await session_svc.accumulate_usage(session_id, usage)

                if not bridge._requires_action_pending:
                    stop_reason = (
                        {"type": "end_turn"}
                        if not error
                        else {"type": "retries_exhausted", "error": error}
                    )
                    await session_svc.update_session_status(
                        session_id, SessionStatus.IDLE.value, stop_reason=stop_reason
                    )

            sandbox_svc = SandboxService(db)
            await sandbox_svc.update_status_cas(sandbox_id, "running", "idle")

        from app.conductor.lifespan import get_redis_coordinator, get_session_broadcaster
        coordinator = get_redis_coordinator()
        if coordinator:
            await coordinator.remove_task_sandbox(task_id)

        # Flush event buffer before broadcasting idle
        await self._event_buffer.flush()

        if session_id and not bridge._requires_action_pending:
            broadcaster = get_session_broadcaster()
            if broadcaster:
                stop_reason = (
                    {"type": "end_turn"}
                    if not error
                    else {"type": "retries_exhausted", "error": error}
                )
                await broadcaster.broadcast(
                    session_id,
                    {"type": "session.status_idle", "payload": {"stop_reason": stop_reason}},
                )

        result_payload = {
            "output": result.output,
            "error": error,
            "usage": usage,
            "session_id": result.session_id if result.HasField("session_id") else None,
            "work_dir": result.work_dir if result.HasField("work_dir") else None,
            "status": result.status,
            "duration_ms": result.duration_ms,
        }
        await bridge.broadcast_to_task(
            task_id, WsOutMessage(type="complete", payload=result_payload)
        )

        logger.info("Task %s completed: status=%s", task_id, result.status)

    async def _send_setup(self, bridge: SandboxBridge, sandbox_id: uuid.UUID) -> None:
        if bridge.setup_done:
            return

        from app.core.database import AsyncSessionLocal
        from app.conductor.services.sandbox_service import SandboxService
        from app.conductor.services.session_service import SessionService
        from app.conductor.services.agent_service import AgentService

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

                from app.conductor.kernel.harness_input_builder import build_harness_input

                class _FakeTask:
                    prompt = ""
                    system_prompt = agent.system_prompt

                harness_input = await build_harness_input(
                    _FakeTask(), agent, sandbox.chat_session_id,
                    bridge.external_id, sandbox_id,
                )

                # Load environment for setup_commands
                environment = None
                env_ref = getattr(agent, "environment_ref", None)
                if env_ref:
                    from app.conductor.services.environment_service import EnvironmentService
                    env_svc = EnvironmentService(db)
                    environment = await env_svc.get_environment_by_ref(env_ref)

            setup_msg = _build_setup_sandbox(harness_input, agent, environment)
            orch_msg = conductor_pb2.OrchestratorMessage(setup=setup_msg)
            await bridge.runner_stream.write(orch_msg)
            bridge.setup_done = True
            logger.info("SetupSandbox sent for sandbox %s", sandbox_id)

        except Exception as e:
            logger.warning("Failed to send SetupSandbox for %s: %s", sandbox_id, e)
            bridge.setup_done = True

    async def _cleanup_sandbox(self, sandbox_id: uuid.UUID) -> None:
        await self._queue.drain_and_requeue_sandbox(sandbox_id)


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
        from app.conductor.services.session_service import SessionService
        from app.conductor.services.memory_service import MemoryService

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
                return
    except Exception as e:
        logger.warning("Memory sync failed: %s", e)


def _extract_setup_commands(agent=None, environment=None) -> list[str]:
    """Extract setup_commands from environment config (packages.install_commands)
    and agent metadata.  Returns a combined list."""
    commands: list[str] = []

    # From environment config packages
    if environment and getattr(environment, "config", None):
        env_config = environment.config
        if isinstance(env_config, dict):
            packages = env_config.get("packages", {})
            if isinstance(packages, dict):
                from app.conductor.schemas.environment import Packages
                try:
                    pkg = Packages(**packages)
                    commands.extend(pkg.install_commands())
                except Exception:
                    pass

    # From agent metadata setup_commands
    if agent and getattr(agent, "metadata_", None):
        agent_cmds = agent.metadata_.get("setup_commands")
        if isinstance(agent_cmds, list):
            for cmd in agent_cmds:
                if isinstance(cmd, str) and cmd.strip():
                    commands.append(cmd.strip())

    return commands


def _build_setup_sandbox(
    harness_input, agent, environment=None,
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

    setup_commands = _extract_setup_commands(agent, environment)

    return conductor_pb2.SetupSandbox(
        skills=skills,
        mcp_servers=mcp_servers,
        custom_tools=custom_tools,
        setup_commands=setup_commands,
        env=harness_input.env,
        secrets=harness_input.secrets,
        permission_mode=harness_input.permission_mode,
        provider="claude",
        model=harness_input.model or "",
        memory_system_prompt=harness_input.memory_system_prompt or "",
        memory_mounts=memory_mounts,
    )


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

    kwargs: dict[str, Any] = dict(
        task_id=str(task_id),
        provider="claude",
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

    # max_turns: from agent metadata or default
    max_turns = 100
    if agent and getattr(agent, "metadata_", None):
        mt = agent.metadata_.get("max_turns")
        if mt is not None:
            try:
                max_turns = int(mt)
            except (ValueError, TypeError):
                pass
    kwargs["max_turns"] = max_turns

    # work_dir: from session's last_work_dir (for continuation)
    if session and getattr(session, "last_work_dir", None):
        kwargs["work_dir"] = session.last_work_dir

    # repos: from agent metadata (if applicable)
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

    # setup_commands: from environment config packages
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
) -> tuple[grpc_aio.Server, "AgentBridgeServicer"]:
    server = grpc_aio.server()
    servicer = AgentBridgeServicer(bridge_registry, event_buffer, queue, vault_provider=vault_provider)
    conductor_pb2_grpc.add_AgentBridgeServicer_to_server(servicer, server)
    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    logger.info("gRPC server started on %s:%d", host, port)
    return server, servicer
