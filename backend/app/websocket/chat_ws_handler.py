"""Persistent WebSocket chat handler for Chat page streaming."""

import asyncio
import json
import time
import uuid as uuid_lib
from typing import Any, cast

from fastapi import WebSocket, WebSocketDisconnect
from langchain.messages import HumanMessage
from loguru import logger
from sqlalchemy import select

from app.api.v1.chat import (
    GraphBubbleUp,
    _clear_interrupt_marker,
    _dispatch_stream_event,
    _enrich_message,
    get_or_create_conversation,
    get_user_config,
    safe_get_state,
    save_run_result,
    save_user_message,
)
from app.core.agent.artifacts import ArtifactCollector
from app.core.database import AsyncSessionLocal
from app.models import Conversation
from app.schemas.chat import ChatRequest
from app.services.graph_service import GraphService
from app.utils.file_event_emitter import FileEventEmitter
from app.utils.stream_event_handler import StreamEventHandler, StreamState
from app.utils.task_manager import task_manager


class ChatWsHandler:
    """Handle a persistent `/ws/chat` connection for a single user."""

    def __init__(self, user_id: str, websocket: WebSocket):
        self.user_id = user_id
        self.websocket = websocket
        self._tasks: dict[str, tuple[str | None, asyncio.Task[Any]]] = {}
        self._send_lock = asyncio.Lock()

    async def run(self) -> None:
        try:
            while True:
                raw = await self.websocket.receive_text()
                await self._handle_frame(raw)
        except WebSocketDisconnect:
            logger.info(f"Chat WebSocket disconnected | user_id={self.user_id}")
        finally:
            await self._cancel_all_tasks()

    async def _handle_frame(self, raw: str) -> None:
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            await self._send({"type": "ws_error", "message": "invalid json frame"})
            return

        frame_type = frame.get("type")
        if frame_type == "chat":
            await self._handle_chat(frame)
            return
        if frame_type == "resume":
            await self._handle_resume(frame)
            return
        if frame_type == "stop":
            await self._handle_stop(frame)
            return
        if frame_type == "ping":
            await self._send({"type": "pong"})
            return

        await self._send({"type": "ws_error", "message": f"unknown frame type: {frame_type}"})

    async def _handle_chat(self, frame: dict[str, Any]) -> None:
        request_id = str(frame.get("request_id") or "")
        message = str(frame.get("message") or "")
        thread_id = frame.get("thread_id")
        graph_id = frame.get("graph_id")
        raw_metadata = frame.get("metadata")
        metadata: dict[str, Any] = cast(dict[str, Any], raw_metadata) if isinstance(raw_metadata, dict) else {}

        if not request_id or not message.strip():
            await self._send({"type": "ws_error", "message": "request_id and message are required"})
            return
        if request_id in self._tasks:
            await self._send({"type": "ws_error", "message": "duplicate request_id"})
            return
        if thread_id and self._is_thread_active(str(thread_id)):
            await self._send(
                {
                    "type": "ws_error",
                    "request_id": request_id,
                    "message": "turn already in progress for thread_id",
                }
            )
            return

        async def runner() -> None:
            await self._run_chat_turn(
                request_id=request_id,
                payload=ChatRequest(
                    message=message,
                    thread_id=str(thread_id) if thread_id else None,
                    graph_id=graph_id,
                    metadata=metadata,
                ),
            )

        task = asyncio.create_task(runner(), name=f"chat-ws:{request_id}")
        self._tasks[request_id] = (str(thread_id) if thread_id else None, task)

    async def _handle_resume(self, frame: dict[str, Any]) -> None:
        request_id = str(frame.get("request_id") or "")
        thread_id = str(frame.get("thread_id") or "")
        raw_command = frame.get("command")
        command: dict[str, Any] = cast(dict[str, Any], raw_command) if isinstance(raw_command, dict) else {}

        if not request_id or not thread_id:
            await self._send({"type": "ws_error", "message": "request_id and thread_id are required"})
            return
        if request_id in self._tasks:
            await self._send({"type": "ws_error", "message": "duplicate request_id"})
            return
        if self._is_thread_active(thread_id):
            await self._send(
                {
                    "type": "ws_error",
                    "request_id": request_id,
                    "message": "turn already in progress for thread_id",
                }
            )
            return

        async def runner() -> None:
            await self._run_resume_turn(request_id=request_id, thread_id=thread_id, command=command)

        task = asyncio.create_task(runner(), name=f"chat-ws-resume:{request_id}")
        self._tasks[request_id] = (thread_id, task)

    async def _handle_stop(self, frame: dict[str, Any]) -> None:
        request_id = str(frame.get("request_id") or "")
        if not request_id:
            return

        entry = self._tasks.get(request_id)
        if entry is None:
            return

        thread_id, task = entry
        if thread_id:
            try:
                await task_manager.stop_task(thread_id)
            except Exception:
                pass
        task.cancel()

    async def _run_chat_turn(self, request_id: str, payload: ChatRequest) -> None:
        state: StreamState | None = None
        thread_id: str | None = None
        built_graph = None
        graph_workspace_id: str | None = None
        graph_display_name: str | None = None
        artifact_collector = ArtifactCollector()

        try:
            file_emitter = FileEventEmitter()
            async with AsyncSessionLocal() as db:
                thread_id, _ = await get_or_create_conversation(
                    payload.thread_id,
                    payload.message,
                    self.user_id,
                    payload.metadata,
                    db,
                )
                await save_user_message(thread_id, payload.message, payload.metadata, db)
                config, base_context, llm_params = await get_user_config(self.user_id, thread_id, db)

                initial_context = base_context.copy()
                if payload.graph_id:
                    from app.repositories.graph import GraphRepository

                    graph_repo = GraphRepository(db)
                    graph_model = await graph_repo.get(payload.graph_id)
                    if graph_model:
                        ws_id = getattr(graph_model, "workspace_id", None)
                        graph_workspace_id = str(ws_id) if ws_id else None
                        graph_display_name = getattr(graph_model, "name", None) or getattr(graph_model, "title", None)
                    if graph_model and graph_model.variables:
                        context_vars = graph_model.variables.get("context", {})
                        if context_vars:
                            for key, value in context_vars.items():
                                if isinstance(value, dict) and "value" in value:
                                    initial_context[key] = value["value"]
                                else:
                                    initial_context[key] = value

                graph_service = GraphService(db)
                if payload.graph_id is None:
                    built_graph = await graph_service.create_default_deep_agents_graph(
                        llm_model=llm_params["llm_model"],
                        api_key=llm_params["api_key"],
                        base_url=llm_params["base_url"],
                        max_tokens=llm_params["max_tokens"],
                        user_id=self.user_id,
                        file_emitter=file_emitter,
                    )
                else:
                    from app.repositories.user import UserRepository

                    user_repo = UserRepository(db)
                    current_user = await user_repo.get_by_id(self.user_id)
                    built_graph = await graph_service.create_graph_by_graph_id(
                        graph_id=payload.graph_id,
                        llm_model=llm_params["llm_model"],
                        api_key=llm_params["api_key"],
                        base_url=llm_params["base_url"],
                        max_tokens=llm_params["max_tokens"],
                        user_id=self.user_id,
                        current_user=current_user,
                        file_emitter=file_emitter,
                    )
            # Phase 2: streaming — DB session is closed, no connection held

            state = StreamState(thread_id)
            current_task = asyncio.current_task()
            if current_task is None:
                raise RuntimeError("missing current asyncio task")
            self._tasks[request_id] = (thread_id, current_task)
            await task_manager.register_task(thread_id, current_task)

            handler = StreamEventHandler()
            artifact_collector.ensure_run_dir(self.user_id, thread_id, state.artifact_run_id)

            await self._send_event_from_sse(
                handler.format_sse("status", {"status": "connected", "_meta": {"node_name": "system"}}, thread_id),
                request_id,
            )

            enriched_message = _enrich_message(
                payload.message,
                payload.metadata,
                is_new_thread=(payload.thread_id is None),
                log=logger.bind(user_id=self.user_id, thread_id=thread_id),
                endpoint="Chat WS",
            )

            interrupted = False
            async for event in built_graph.astream_events(
                {"messages": [HumanMessage(content=enriched_message)], "context": initial_context},
                config=config,
                version="v2",
            ):
                if await task_manager.is_stopped(thread_id):
                    state.stopped = True
                    break

                async for sse_str in _dispatch_stream_event(event, handler, state, file_emitter):
                    await self._send_event_from_sse(sse_str, request_id)

            try:
                snap = await safe_get_state(built_graph, config, max_retries=3, initial_delay=0.1, log=logger)
                if snap.tasks:
                    next_node = snap.tasks[0].target if snap.tasks else None
                    current_state = snap.values or {}
                    if payload.graph_id is None:
                        logger.warning(f"Default agent interrupted, resume not supported | thread_id={thread_id}")
                    else:
                        await self._send(
                            {
                                "type": "interrupt",
                                "request_id": request_id,
                                "thread_id": thread_id,
                                "node_name": next_node or "unknown",
                                "node_label": next_node.replace("_", " ").title() if next_node else "Unknown Node",
                                "data": {
                                    "node_name": next_node or "unknown",
                                    "node_label": next_node.replace("_", " ").title() if next_node else "Unknown Node",
                                    "state": current_state,
                                    "thread_id": thread_id,
                                },
                            }
                        )
                        async with AsyncSessionLocal() as session:
                            result_query = await session.execute(
                                select(Conversation).where(Conversation.thread_id == thread_id)
                            )
                            if conv := result_query.scalar_one_or_none():
                                if not conv.meta_data:
                                    conv.meta_data = {}
                                conv.meta_data["interrupted_graph_id"] = str(payload.graph_id)
                                await session.commit()
                        state.interrupted = True
                        state.interrupt_node = next_node
                        state.interrupt_state = current_state
                        interrupted = True
            except Exception as exc:
                logger.warning(f"Failed to inspect interrupt state | thread_id={thread_id} | error={exc}")

            if state and not state.all_messages and not state.stopped and not interrupted:
                try:
                    snap = await safe_get_state(built_graph, config, max_retries=2, initial_delay=0.05, log=logger)
                    if snap.values and "messages" in snap.values:
                        msgs = snap.values["messages"]
                        from langgraph.types import Overwrite

                        state.all_messages = msgs.value if isinstance(msgs, Overwrite) else msgs
                except Exception as exc:
                    logger.warning(f"Failed to fetch final state | thread_id={thread_id} | error={exc}")

            if state.interrupted:
                return

            if state.stopped:
                await self._send(
                    {
                        "type": "error",
                        "request_id": request_id,
                        "thread_id": thread_id,
                        "node_name": "system",
                        "run_id": "",
                        "timestamp": int(time.time() * 1000),
                        "data": {"message": "Stopped by user", "code": "stopped"},
                    }
                )

            await self._send(
                {
                    "type": "done",
                    "request_id": request_id,
                    "thread_id": thread_id,
                    "node_name": "system",
                    "run_id": "",
                    "timestamp": int(time.time() * 1000),
                    "data": {},
                }
            )

        except asyncio.CancelledError:
            if state is not None:
                state.stopped = True
            try:
                await self._send(
                    {
                        "type": "done",
                        "request_id": request_id,
                        "thread_id": thread_id or payload.thread_id or "",
                        "node_name": "system",
                        "run_id": "",
                        "timestamp": int(time.time() * 1000),
                        "data": {},
                    }
                )
            except Exception:
                pass
            raise
        except Exception as exc:
            if state is not None and not (GraphBubbleUp is not None and type(exc) is GraphBubbleUp):
                state.has_error = True
            await self._send(
                {
                    "type": "error",
                    "request_id": request_id,
                    "thread_id": thread_id or payload.thread_id or "",
                    "node_name": "system",
                    "run_id": "",
                    "timestamp": int(time.time() * 1000),
                    "data": {"message": str(exc)},
                }
            )
            await self._send(
                {
                    "type": "done",
                    "request_id": request_id,
                    "thread_id": thread_id or payload.thread_id or "",
                    "node_name": "system",
                    "run_id": "",
                    "timestamp": int(time.time() * 1000),
                    "data": {},
                }
            )
        finally:
            await self._finalize_task(
                request_id=request_id,
                thread_id=thread_id,
                state=state,
                built_graph=built_graph,
                artifact_collector=artifact_collector,
                graph_id=str(payload.graph_id) if payload.graph_id else None,
                workspace_id=graph_workspace_id,
                graph_name=graph_display_name,
            )

    async def _run_resume_turn(self, request_id: str, thread_id: str, command: dict[str, Any]) -> None:
        state: StreamState | None = None
        built_graph = None
        graph_workspace_id: str | None = None
        graph_display_name: str | None = None
        graph_id = None
        config = None
        handler = None
        ws_command = None

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Conversation).where(
                        Conversation.thread_id == thread_id, Conversation.user_id == self.user_id
                    )
                )
                conversation = result.scalar_one_or_none()
                if not conversation:
                    await self._send(
                        {"type": "ws_error", "request_id": request_id, "message": "conversation not found"}
                    )
                    return

                if (
                    conversation.meta_data
                    and isinstance(conversation.meta_data, dict)
                    and "interrupted_graph_id" in conversation.meta_data
                ):
                    try:
                        graph_id = uuid_lib.UUID(str(conversation.meta_data["interrupted_graph_id"]))
                    except (ValueError, TypeError):
                        graph_id = None

                if graph_id is None:
                    await self._send({"type": "ws_error", "request_id": request_id, "message": "graph id not found"})
                    return

                config, _, llm_params = await get_user_config(self.user_id, thread_id, db)

                from langgraph.types import Command

                from app.repositories.graph import GraphRepository
                from app.repositories.user import UserRepository

                graph_repo = GraphRepository(db)
                graph_model = await graph_repo.get(graph_id)
                if graph_model:
                    ws_id = getattr(graph_model, "workspace_id", None)
                    graph_workspace_id = str(ws_id) if ws_id else None
                    graph_display_name = getattr(graph_model, "name", None) or getattr(graph_model, "title", None)

                user_repo = UserRepository(db)
                current_user = await user_repo.get_by_id(self.user_id)

                graph_service = GraphService(db)
                built_graph = await graph_service.create_graph_by_graph_id(
                    graph_id=graph_id,
                    llm_model=llm_params["llm_model"],
                    api_key=llm_params["api_key"],
                    base_url=llm_params["base_url"],
                    max_tokens=llm_params["max_tokens"],
                    user_id=self.user_id,
                    current_user=current_user,
                )

                snap = await safe_get_state(built_graph, config, max_retries=3, initial_delay=0.1, log=logger)
                if not snap.tasks:
                    await self._send(
                        {"type": "ws_error", "request_id": request_id, "message": "no interrupt state found"}
                    )
                    return

                state = StreamState(thread_id)
                current_task = asyncio.current_task()
                if current_task is None:
                    raise RuntimeError("missing current asyncio task")
                self._tasks[request_id] = (thread_id, current_task)
                await task_manager.register_task(thread_id, current_task)
            # Phase 2: streaming — DB session is closed, no connection held

            handler = StreamEventHandler()
            ws_command = Command(
                update=command.get("update") or {},
                goto=command.get("goto") or None,
            )

            await self._send_event_from_sse(
                handler.format_sse("status", {"status": "resumed", "_meta": {"node_name": "system"}}, thread_id),
                request_id,
            )

            interrupted = False
            async for event in built_graph.astream_events(ws_command, config=config, version="v2"):
                if await task_manager.is_stopped(thread_id):
                    state.stopped = True
                    break
                async for sse_str in _dispatch_stream_event(event, handler, state):
                    await self._send_event_from_sse(sse_str, request_id)

            try:
                snap = await safe_get_state(built_graph, config, max_retries=3, initial_delay=0.1, log=logger)
                if snap.tasks:
                    next_node = snap.tasks[0].target if snap.tasks else None
                    current_state = snap.values or {}
                    await self._send(
                        {
                            "type": "interrupt",
                            "request_id": request_id,
                            "thread_id": thread_id,
                            "node_name": next_node or "unknown",
                            "node_label": next_node.replace("_", " ").title() if next_node else "Unknown Node",
                            "data": {
                                "node_name": next_node or "unknown",
                                "node_label": next_node.replace("_", " ").title() if next_node else "Unknown Node",
                                "state": current_state,
                                "thread_id": thread_id,
                            },
                        }
                    )
                    state.interrupted = True
                    state.interrupt_node = next_node
                    state.interrupt_state = current_state
                    interrupted = True
            except Exception as exc:
                logger.warning(f"Failed to inspect resume interrupt state | thread_id={thread_id} | error={exc}")

            if not state.all_messages and not state.stopped and not interrupted:
                try:
                    snap = await safe_get_state(built_graph, config, max_retries=2, initial_delay=0.05, log=logger)
                    if snap.values and "messages" in snap.values:
                        msgs = snap.values["messages"]
                        from langgraph.types import Overwrite

                        state.all_messages = msgs.value if isinstance(msgs, Overwrite) else msgs
                except Exception as exc:
                    logger.warning(f"Failed to fetch final resume state | thread_id={thread_id} | error={exc}")

            if state.interrupted:
                return

            if state.stopped:
                await self._send(
                    {
                        "type": "error",
                        "request_id": request_id,
                        "thread_id": thread_id,
                        "node_name": "system",
                        "run_id": "",
                        "timestamp": int(time.time() * 1000),
                        "data": {"message": "Stopped by user", "code": "stopped"},
                    }
                )

            await self._send(
                {
                    "type": "done",
                    "request_id": request_id,
                    "thread_id": thread_id,
                    "node_name": "system",
                    "run_id": "",
                    "timestamp": int(time.time() * 1000),
                    "data": {},
                }
            )

        except asyncio.CancelledError:
            if state is not None:
                state.stopped = True
            try:
                await self._send(
                    {
                        "type": "done",
                        "request_id": request_id,
                        "thread_id": thread_id,
                        "node_name": "system",
                        "run_id": "",
                        "timestamp": int(time.time() * 1000),
                        "data": {},
                    }
                )
            except Exception:
                pass
            raise
        except Exception as exc:
            if state is not None and not (GraphBubbleUp is not None and type(exc) is GraphBubbleUp):
                state.has_error = True
            await self._send(
                {
                    "type": "error",
                    "request_id": request_id,
                    "thread_id": thread_id,
                    "node_name": "system",
                    "run_id": "",
                    "timestamp": int(time.time() * 1000),
                    "data": {"message": str(exc)},
                }
            )
            await self._send(
                {
                    "type": "done",
                    "request_id": request_id,
                    "thread_id": thread_id,
                    "node_name": "system",
                    "run_id": "",
                    "timestamp": int(time.time() * 1000),
                    "data": {},
                }
            )
        finally:
            await self._finalize_task(
                request_id=request_id,
                thread_id=thread_id,
                state=state,
                built_graph=built_graph,
                artifact_collector=None,
                graph_id=str(graph_id) if graph_id else None,
                workspace_id=graph_workspace_id,
                graph_name=graph_display_name,
            )

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
        self._tasks.pop(request_id, None)

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

    async def _send_event_from_sse(self, sse_str: str | None, request_id: str) -> None:
        event = self._parse_sse_event(sse_str)
        if not event:
            return
        event["request_id"] = request_id
        await self._send(event)

    def _parse_sse_event(self, sse_str: str | None) -> dict[str, Any] | None:
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

    async def _send(self, event: dict[str, Any]) -> None:
        try:
            async with self._send_lock:
                await self.websocket.send_text(json.dumps(event))
        except WebSocketDisconnect:
            raise
        except RuntimeError:
            raise WebSocketDisconnect()

    def _is_thread_active(self, thread_id: str) -> bool:
        return any(active_thread_id == thread_id for active_thread_id, _ in self._tasks.values())

    async def _cancel_all_tasks(self) -> None:
        tasks = list(self._tasks.items())
        self._tasks.clear()
        for _, (thread_id, task) in tasks:
            if thread_id:
                try:
                    await task_manager.stop_task(thread_id)
                except Exception:
                    pass
            task.cancel()
        for _, (_, task) in tasks:
            try:
                await task
            except BaseException:
                pass
