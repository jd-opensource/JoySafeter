"""Persistent WebSocket chat handler for Chat page streaming."""

import asyncio
import json
import sys
import time
import uuid as uuid_lib
from typing import Any, cast

from fastapi import WebSocket, WebSocketDisconnect
from langchain.messages import HumanMessage as HumanMessage
from loguru import logger
from sqlalchemy import select as select

# Re-exported names below are part of ChatTurnExecutor's module dependency contract.
from app.api.v1.chat import (
    GraphBubbleUp as GraphBubbleUp,
)
from app.api.v1.chat import (
    _clear_interrupt_marker,
    save_run_result,
)
from app.api.v1.chat import (
    _dispatch_stream_event as _dispatch_stream_event,
)
from app.api.v1.chat import (
    _enrich_message as _enrich_message,
)
from app.api.v1.chat import (
    get_or_create_conversation as get_or_create_conversation,
)
from app.api.v1.chat import (
    get_user_config as get_user_config,
)
from app.api.v1.chat import (
    safe_get_state as safe_get_state,
)
from app.api.v1.chat import (
    save_user_message as save_user_message,
)
from app.core.agent.artifacts import ArtifactCollector
from app.core.database import AsyncSessionLocal as AsyncSessionLocal
from app.core.database import async_session_factory
from app.core.settings import settings
from app.models import Conversation as Conversation
from app.models.agent_run import AgentRunStatus
from app.schemas.chat import ChatRequest
from app.services.graph_service import GraphService as GraphService
from app.services.run_service import RunService
from app.utils.file_event_emitter import FileEventEmitter as FileEventEmitter
from app.utils.stream_event_handler import StreamEventHandler as StreamEventHandler
from app.utils.stream_event_handler import StreamState
from app.utils.task_manager import task_manager
from app.websocket.chat_commands import (
    ChatTurnCommand,
    CopilotTurnCommand,
    build_command_from_parsed_frame,
)
from app.websocket.chat_protocol import ChatProtocolError, ParsedChatStartFrame, parse_client_frame
from app.websocket.chat_task_supervisor import ChatTaskEntry as ChatTaskEntry
from app.websocket.chat_task_supervisor import ChatTaskSupervisor
from app.websocket.chat_turn_executor import ChatTurnExecutor


class ChatWsHandler:
    """Handle a persistent `/ws/chat` connection for a single user."""

    def __init__(self, user_id: str, websocket: WebSocket):
        """Initialize the handler for a single authenticated user connection."""
        self.user_id = user_id
        self.websocket = websocket
        self._task_supervisor = ChatTaskSupervisor(
            stop_task=self._stop_managed_task,
        )
        self._tasks = self._task_supervisor.tasks
        self._turn_executor = ChatTurnExecutor(handler=self, dependencies=cast(Any, sys.modules[__name__]))
        self._send_lock = asyncio.Lock()
        self._socket_connected = True
        self._runtime_owner_id = settings.run_runtime_instance_id

    async def _stop_managed_task(self, thread_id: str) -> None:
        """Delegate task cancellation to the global task manager."""
        await task_manager.stop_task(thread_id)

    async def run(self) -> None:
        """Read frames in a loop until the client disconnects."""
        try:
            while True:
                raw = await self.websocket.receive_text()
                await self._handle_frame(raw)
        except WebSocketDisconnect:
            self._socket_connected = False
            logger.info(f"Chat WebSocket disconnected | user_id={self.user_id}")
        finally:
            await self._cancel_all_tasks()

    async def _handle_frame(self, raw: str) -> None:
        """Parse and dispatch a single client frame."""
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            await self._send({"type": "ws_error", "message": "invalid json frame"})
            return

        if not isinstance(frame, dict):
            await self._send({"type": "ws_error", "message": "frame must be a JSON object"})
            return

        try:
            parsed_frame = parse_client_frame(frame)
        except ChatProtocolError as exc:
            await self._send(
                {
                    "type": "ws_error",
                    "message": exc.message,
                    "request_id": exc.request_id,
                }
            )
            return

        if isinstance(parsed_frame, ParsedChatStartFrame):
            await self._handle_chat_start_frame(parsed_frame)
            return

        frame_type = str(parsed_frame.get("type") or "")
        if frame_type in {"chat.resume", "resume"}:
            await self._handle_resume(parsed_frame)
            return
        if frame_type in {"chat.stop", "stop"}:
            await self._handle_stop(parsed_frame)
            return
        if frame_type == "ping":
            await self._send({"type": "pong"})
            return

        await self._send({"type": "ws_error", "message": f"unknown frame type: {frame_type}"})

    async def _handle_chat_start_frame(self, frame: ParsedChatStartFrame) -> None:
        """Convert a parsed chat.start frame into a turn command and launch it."""
        command = build_command_from_parsed_frame(frame)
        await self._start_turn_from_command(command)

    async def _start_turn_from_command(self, command: ChatTurnCommand) -> None:
        """Validate and schedule a new chat turn as a supervised async task."""
        prepared = self._turn_executor.prepare_standard_turn(command)
        request_id = prepared.request_id
        message = prepared.payload.message
        thread_key = prepared.payload.thread_id

        if not request_id or not message.strip():
            await self._send({"type": "ws_error", "message": "request_id and message are required"})
            return
        if self._task_supervisor.has_request(request_id):
            await self._send({"type": "ws_error", "message": "duplicate request_id"})
            return
        if thread_key and self._task_supervisor.is_thread_active(thread_key):
            await self._send(
                {
                    "type": "ws_error",
                    "request_id": request_id,
                    "message": "turn already in progress for thread_id",
                }
            )
            return

        from app.core.trace_context import set_trace_id

        set_trace_id(prepared.request_id)

        async def runner() -> None:
            if isinstance(command, CopilotTurnCommand):
                await self._turn_executor.execute_copilot_turn(
                    request_id=prepared.request_id,
                    payload=prepared.payload,
                    graph_context=command.graph_context,
                    conversation_history=command.conversation_history,
                    mode=command.mode,
                )
            else:
                await self._turn_executor.run_standard_turn(prepared)

        self._task_supervisor.create_task(
            request_id,
            runner(),
            name=f"chat-ws:{request_id}",
            thread_id=thread_key,
            run_id=prepared.run_id,
            persist_on_disconnect=prepared.persist_on_disconnect,
        )

    async def _handle_resume(self, frame: dict[str, Any]) -> None:
        """Resume an interrupted graph turn for the given thread."""
        request_id = str(frame.get("request_id") or "")
        thread_id = str(frame.get("thread_id") or "")
        raw_command = frame.get("command")
        command: dict[str, Any] = cast(dict[str, Any], raw_command) if isinstance(raw_command, dict) else {}

        if not request_id or not thread_id:
            await self._send({"type": "ws_error", "message": "request_id and thread_id are required"})
            return
        if self._task_supervisor.has_request(request_id):
            await self._send({"type": "ws_error", "message": "duplicate request_id"})
            return
        if self._task_supervisor.is_thread_active(thread_id):
            await self._send(
                {
                    "type": "ws_error",
                    "request_id": request_id,
                    "message": "turn already in progress for thread_id",
                }
            )
            return

        from app.core.trace_context import set_trace_id

        set_trace_id(request_id)

        async def runner() -> None:
            await self._turn_executor.run_resume_turn(request_id=request_id, thread_id=thread_id, command=command)

        # Inherit run_id from the previous task entry for this thread (if persisted)
        existing_entry = self._task_supervisor.get_by_thread(thread_id)
        resume_run_id = existing_entry.run_id if existing_entry else None
        resume_persist = existing_entry.persist_on_disconnect if existing_entry else False

        self._task_supervisor.create_task(
            request_id,
            runner(),
            name=f"chat-ws-resume:{request_id}",
            thread_id=thread_id,
            run_id=resume_run_id,
            persist_on_disconnect=resume_persist,
        )

    async def _handle_stop(self, frame: dict[str, Any]) -> None:
        """Cancel the running turn identified by request_id."""
        request_id = str(frame.get("request_id") or "")
        if not request_id:
            return

        await self._task_supervisor.stop_by_request_id(request_id)

    @staticmethod
    def _parse_uuid(value: Any) -> uuid_lib.UUID | None:
        """Parse a value into a UUID, returning None on failure."""
        if not value:
            return None
        try:
            return uuid_lib.UUID(str(value))
        except (ValueError, TypeError):
            return None

    async def _append_run_event(
        self,
        *,
        run_id: uuid_lib.UUID,
        event_type: str,
        payload: dict[str, Any],
        trace_id: uuid_lib.UUID | None = None,
        observation_id: uuid_lib.UUID | None = None,
        parent_observation_id: uuid_lib.UUID | None = None,
    ) -> None:
        """Persist a stream event to the durable run event log."""
        async with async_session_factory() as db:
            service = RunService(db)
            await service.append_event(
                run_id=run_id,
                event_type=event_type,
                payload=payload,
                trace_id=trace_id,
                observation_id=observation_id,
                parent_observation_id=parent_observation_id,
            )

    async def _mark_run_status(
        self,
        *,
        run_id: uuid_lib.UUID,
        status: AgentRunStatus,
        runtime_owner_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        result_summary: dict[str, Any] | None = None,
    ) -> None:
        """Update the persisted status of a durable agent run."""
        async with async_session_factory() as db:
            service = RunService(db)
            await service.mark_status(
                run_id=run_id,
                user_id=self.user_id,
                status=status,
                runtime_owner_id=runtime_owner_id,
                error_code=error_code,
                error_message=error_message,
                result_summary=result_summary,
            )

    async def _touch_run_heartbeat(self, *, run_id: uuid_lib.UUID) -> None:
        """Send a single heartbeat for a durable run to indicate liveness."""
        async with async_session_factory() as db:
            service = RunService(db)
            await service.touch_run_heartbeat(
                run_id=run_id,
                runtime_owner_id=self._runtime_owner_id,
            )

    async def _run_persisted_run_heartbeat(self, run_id: uuid_lib.UUID) -> None:
        """Periodically touch the heartbeat for a persisted run until cancelled."""
        while True:
            try:
                await asyncio.sleep(settings.run_heartbeat_interval_seconds)
                await self._touch_run_heartbeat(run_id=run_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"Persisted run heartbeat failed, will retry | run_id={run_id} | error={exc}")
                await asyncio.sleep(5)  # brief backoff before retry

    async def _mirror_run_stream_event(
        self,
        *,
        run_id: uuid_lib.UUID,
        event: dict[str, Any],
        assistant_message_id: str | None,
    ) -> None:
        """Translate a WS stream event and persist it to the durable run log."""
        event_type = str(event.get("type") or "")
        raw_data = event.get("data")
        data = raw_data if isinstance(raw_data, dict) else {}
        timestamp = int(event.get("timestamp") or int(time.time() * 1000))
        observation_id = self._parse_uuid(event.get("observation_id"))

        payload: dict[str, Any] | None = None
        if event_type == "status":
            # Chat events: {"status": "..."}, copilot events: {"stage": "...", "message": "..."}
            stage = data.get("stage")
            if stage is not None:
                payload = {"stage": stage, "message": data.get("message", "")}
            else:
                message = str(data.get("status") or "")
                payload = {"message": message, "status": message}
        elif event_type == "content" and assistant_message_id:
            # Chat events: {"delta": "..."}, copilot events: {"content": "..."}
            delta = data.get("delta") or data.get("content")
            if delta:
                payload = {"message_id": assistant_message_id, "delta": str(delta)}
        elif event_type in ("thought_step", "tool_call", "tool_result", "result"):
            # Copilot-specific events — store data as-is for the copilot reducer
            payload = dict(data)
        elif event_type == "tool_start" and assistant_message_id:
            tool_input = data.get("tool_input")
            payload = {
                "message_id": assistant_message_id,
                "tool": {
                    "id": str(observation_id or uuid_lib.uuid4()),
                    "name": str(data.get("tool_name") or "tool"),
                    "args": tool_input if isinstance(tool_input, dict) else {},
                    "status": "running",
                    "startTime": timestamp,
                },
            }
        elif event_type == "tool_end" and assistant_message_id:
            payload = {
                "message_id": assistant_message_id,
                "tool_id": str(observation_id) if observation_id else None,
                "tool_name": data.get("tool_name"),
                "tool_output": data.get("tool_output"),
                "end_time": timestamp,
            }
        elif event_type == "file_event":
            payload = {
                "action": data.get("action"),
                "path": data.get("path"),
                "size": data.get("size"),
                "timestamp": data.get("timestamp"),
            }
        elif event_type == "interrupt":
            payload = {"interrupt": data}
        elif event_type == "error":
            payload = {"message": data.get("message"), "code": data.get("code")}
        elif event_type == "done":
            payload = {}

        if payload is None:
            return

        await self._append_run_event(
            run_id=run_id,
            event_type="content_delta" if event_type == "content" else event_type,
            payload=payload,
            trace_id=self._parse_uuid(event.get("trace_id")),
            observation_id=observation_id,
            parent_observation_id=self._parse_uuid(event.get("parent_observation_id")),
        )

    async def _emit_event(
        self,
        event: dict[str, Any],
        *,
        request_id: str | None = None,
        tolerate_disconnect: bool = False,
        agent_run_id: uuid_lib.UUID | None = None,
        assistant_message_id: str | None = None,
    ) -> None:
        """Send an event to the client and optionally mirror it to durable storage."""
        outbound = dict(event)
        if request_id is not None:
            outbound["request_id"] = request_id
        if agent_run_id is not None:
            asyncio.create_task(
                self._mirror_run_stream_event(
                    run_id=agent_run_id,
                    event=outbound,
                    assistant_message_id=assistant_message_id,
                ),
                name=f"mirror-event:{agent_run_id}",
            )
        await self._send(outbound, tolerate_disconnect=tolerate_disconnect)

    async def _run_chat_turn(self, request_id: str, payload: ChatRequest) -> None:
        """Execute a standard (new-message) chat turn."""
        await self._turn_executor.execute_standard_turn(request_id=request_id, payload=payload)

    async def _run_resume_turn(self, request_id: str, thread_id: str, command: dict[str, Any]) -> None:
        """Execute a resume turn to continue an interrupted graph."""
        await self._turn_executor.execute_resume_turn(request_id=request_id, thread_id=thread_id, command=command)

    async def _finalize_task(
        self,
        *,
        request_id: str,
        thread_id: str | None,
        state: StreamState | None,
        built_graph: Any,
        artifact_collector: ArtifactCollector | None,
        graph_id: str | None,
        workspace_id: str | None,
        graph_name: str | None,
    ) -> None:
        """Clean up after a turn: save results, write artifacts, and update run status."""
        task_entry = await self._task_supervisor.finalize(request_id)
        agent_run_id = task_entry.run_id if task_entry else None

        if thread_id:
            try:
                await task_manager.unregister_task(thread_id)
            except Exception as exc:
                logger.warning(f"Failed to unregister task | thread_id={thread_id} | error={exc}")

        if thread_id and state is not None:
            try:
                await save_run_result(
                    thread_id,
                    state,
                    logger.bind(user_id=self.user_id, thread_id=thread_id),
                    graph_id=graph_id,
                    workspace_id=workspace_id,
                    user_id=self.user_id,
                    graph_name=graph_name,
                )
            except Exception as exc:
                logger.warning(f"Failed to save run result | thread_id={thread_id} | error={exc}")

        if built_graph is not None and hasattr(built_graph, "_cleanup_backend"):
            try:
                await built_graph._cleanup_backend()
            except Exception as exc:
                logger.warning(f"Failed to cleanup backend | thread_id={thread_id} | error={exc}")

        if thread_id and artifact_collector is not None and state is not None:
            try:
                run_dir = artifact_collector.ensure_run_dir(self.user_id, thread_id, state.artifact_run_id)
                if built_graph is not None and hasattr(built_graph, "_export_artifacts_to"):
                    try:
                        built_graph._export_artifacts_to(run_dir)
                    except Exception as exc:
                        logger.warning(f"Sandbox export failed | thread_id={thread_id} | error={exc}")
                status = "completed"
                if state.stopped:
                    status = "stopped"
                elif state.has_error:
                    status = "failed"
                elif state.interrupted:
                    status = "interrupted"
                artifact_collector.write_manifest(
                    run_dir,
                    {
                        "run_id": state.artifact_run_id,
                        "thread_id": thread_id,
                        "user_id": self.user_id,
                        "agent_type": "langgraph",
                        "graph_id": graph_id,
                        "status": status,
                    },
                )
            except Exception as exc:
                logger.warning(f"Failed to write artifact manifest | thread_id={thread_id} | error={exc}")

        if thread_id and state is not None and not state.interrupted:
            await _clear_interrupt_marker(thread_id, logger.bind(user_id=self.user_id, thread_id=thread_id))

        if agent_run_id is not None:
            result_summary = {
                "thread_id": thread_id,
                "graph_id": graph_id,
                "workspace_id": workspace_id,
                "graph_name": graph_name,
                "artifact_run_id": state.artifact_run_id if state is not None else None,
            }
            try:
                if state is None:
                    await self._mark_run_status(
                        run_id=agent_run_id,
                        status=AgentRunStatus.FAILED,
                        error_code="missing_state",
                        error_message="Run finalized without stream state",
                        result_summary=result_summary,
                    )
                elif state.interrupted:
                    await self._mark_run_status(
                        run_id=agent_run_id,
                        status=AgentRunStatus.INTERRUPT_WAIT,
                        result_summary=result_summary,
                    )
                elif state.stopped:
                    await self._mark_run_status(
                        run_id=agent_run_id,
                        status=AgentRunStatus.CANCELLED,
                        error_code="stopped",
                        error_message="Stopped by user",
                        result_summary=result_summary,
                    )
                elif state.has_error:
                    await self._mark_run_status(
                        run_id=agent_run_id,
                        status=AgentRunStatus.FAILED,
                        error_code="stream_error",
                        error_message="Agent run failed",
                        result_summary=result_summary,
                    )
                else:
                    await self._mark_run_status(
                        run_id=agent_run_id,
                        status=AgentRunStatus.COMPLETED,
                        result_summary=result_summary,
                    )
            except Exception as exc:
                logger.warning(f"Failed to update persisted run status | run_id={agent_run_id} | error={exc}")

    async def _send_event_from_sse(
        self,
        sse_str: str | None,
        request_id: str,
        *,
        tolerate_disconnect: bool = False,
        agent_run_id: uuid_lib.UUID | None = None,
        assistant_message_id: str | None = None,
    ) -> None:
        """Parse an SSE-formatted string and emit it as a WebSocket event."""
        event = self._parse_sse_event(sse_str)
        if not event:
            return
        await self._emit_event(
            event,
            request_id=request_id,
            tolerate_disconnect=tolerate_disconnect,
            agent_run_id=agent_run_id,
            assistant_message_id=assistant_message_id,
        )

    def _parse_sse_event(self, sse_str: str | None) -> dict[str, Any] | None:
        """Extract the JSON payload from an SSE data line."""
        if not sse_str:
            return None

        payload_str = ""
        for line in sse_str.splitlines():
            stripped = line.strip()
            if stripped.startswith("data:"):
                payload_str = stripped[len("data:") :].strip()
                break

        if not payload_str:
            return None

        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            logger.warning("Failed to decode SSE payload for WS bridge")
            return None

        if not isinstance(payload, dict):
            return None

        return cast(dict[str, Any], payload)

    async def _send(self, event: dict[str, Any], *, tolerate_disconnect: bool = False) -> bool:
        """Serialize and send a JSON event over the WebSocket.

        Returns:
            True if sent successfully, False if the socket is disconnected
            and tolerate_disconnect is True.

        Raises:
            WebSocketDisconnect: If the socket is disconnected and
                tolerate_disconnect is False.
        """
        if not self._socket_connected:
            if tolerate_disconnect:
                return False
            raise WebSocketDisconnect()
        try:
            async with self._send_lock:
                await self.websocket.send_text(json.dumps(event))
            return True
        except WebSocketDisconnect:
            self._socket_connected = False
            if tolerate_disconnect:
                return False
            raise
        except RuntimeError:
            self._socket_connected = False
            if tolerate_disconnect:
                return False
            raise WebSocketDisconnect()

    def _is_thread_active(self, thread_id: str) -> bool:
        """Check whether a turn is currently running for the given thread."""
        return self._task_supervisor.is_thread_active(thread_id)

    async def _cancel_all_tasks(self) -> None:
        """Cancel all non-persistent tasks on disconnect."""
        await self._task_supervisor.cancel_all()
