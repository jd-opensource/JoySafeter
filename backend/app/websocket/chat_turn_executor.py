"""Executor for a single chat turn (standard or resume)."""

from __future__ import annotations

import asyncio
import importlib
import time
import uuid as uuid_lib
from dataclasses import dataclass
from typing import Any

from loguru import logger as _logger

from app.common.exceptions import ModelConfigError
from app.models.agent_run import AgentRunStatus
from app.schemas.chat import ChatRequest
from app.utils.stream_event_handler import StreamState
from app.websocket.chat_commands import ChatRunTurnCommand, ChatTurnCommand, CopilotTurnCommand, SkillCreatorTurnCommand
from app.websocket.chat_task_supervisor import ChatTaskEntry


async def _release_graph_sandbox(built_graph: Any) -> None:
    """Release sandbox handle attached to a compiled graph, if any."""
    if built_graph is None:
        return
    handle = getattr(built_graph, "_sandbox_handle", None)
    if handle is not None:
        try:
            await handle.release()
        except Exception as exc:
            _logger.warning(f"Failed to release sandbox handle: {exc}")


@dataclass(frozen=True)
class PreparedStandardTurn:
    """Immutable bundle of validated parameters ready for turn execution."""

    request_id: str
    payload: ChatRequest
    run_id: uuid_lib.UUID | None
    persist_on_disconnect: bool


class ChatTurnExecutor:
    """Runs a single chat turn against the LangGraph agent.

    Handles both new-message (standard) turns and resume turns for
    interrupted graph executions.
    """

    def __init__(
        self,
        *,
        handler: Any,
        dependencies: Any | None = None,
    ) -> None:
        """Initialize the executor.

        Args:
            handler: The owning ChatWsHandler instance.
            dependencies: Optional module providing helper functions; defaults
                to the handler's own module.
        """
        self._handler = handler
        self._module = dependencies or importlib.import_module(handler.__class__.__module__)

    def prepare_standard_turn(self, command: ChatTurnCommand) -> PreparedStandardTurn:
        """Build a PreparedStandardTurn from a client command."""
        metadata = dict(command.metadata or {})
        if command.files:
            metadata["files"] = command.files

        run_id: uuid_lib.UUID | None = None
        persist_on_disconnect = False
        if isinstance(command, SkillCreatorTurnCommand):
            run_id = self._parse_uuid(command.run_id)
            persist_on_disconnect = run_id is not None
            if command.edit_skill_id and "edit_skill_id" not in metadata:
                metadata["edit_skill_id"] = command.edit_skill_id
        elif isinstance(command, ChatRunTurnCommand):
            run_id = self._parse_uuid(command.run_id)
            persist_on_disconnect = run_id is not None
        elif isinstance(command, CopilotTurnCommand):
            run_id = self._parse_uuid(command.run_id)
            persist_on_disconnect = run_id is not None

        return PreparedStandardTurn(
            request_id=str(command.request_id or ""),
            payload=ChatRequest(
                message=str(command.message or ""),
                thread_id=str(command.thread_id) if command.thread_id else None,
                graph_id=command.graph_id,
                model=command.model,
                metadata=metadata,
            ),
            run_id=run_id,
            persist_on_disconnect=persist_on_disconnect,
        )

    async def run_standard_turn(self, prepared: PreparedStandardTurn) -> None:
        """Dispatch a prepared standard turn to the handler or fallback executor."""
        run_chat_turn = getattr(self._handler, "_run_chat_turn", None)
        if not callable(run_chat_turn):
            run_chat_turn = self.execute_standard_turn
        await run_chat_turn(request_id=prepared.request_id, payload=prepared.payload)

    async def run_resume_turn(self, request_id: str, thread_id: str, command: dict[str, object]) -> None:
        """Dispatch a resume turn to the handler or fallback executor."""
        run_resume_turn = getattr(self._handler, "_run_resume_turn", None)
        if not callable(run_resume_turn):
            run_resume_turn = self.execute_resume_turn
        await run_resume_turn(request_id=request_id, thread_id=thread_id, command=command)

    async def execute_standard_turn(self, request_id: str, payload: ChatRequest) -> None:
        """Stream a new user message through the graph and emit events to the client."""
        from app.core.trace_context import set_trace_id

        set_trace_id(request_id)
        handler = self._handler
        module = self._module
        state: StreamState | None = None
        thread_id: str | None = None
        built_graph = None
        graph_workspace_id: str | None = None
        graph_display_name: str | None = None
        artifact_collector = module.ArtifactCollector()
        task_entry = handler._task_supervisor.get(request_id)
        agent_run_id = task_entry.run_id if task_entry else None
        tolerate_disconnect = bool(task_entry and task_entry.persist_on_disconnect)
        assistant_message_id = f"msg-assistant-{uuid_lib.uuid4()}"

        try:
            file_emitter = module.FileEventEmitter()
            async with module.AsyncSessionLocal() as db:
                thread_id, _ = await module.get_or_create_conversation(
                    payload.thread_id,
                    payload.message,
                    handler.user_id,
                    payload.metadata,
                    db,
                )
                await module.save_user_message(thread_id, payload.message, payload.metadata, db)
                config, base_context, llm_params = await module.get_user_config(
                    handler.user_id, thread_id, db, llm_model=payload.model
                )

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

                graph_service = module.GraphService(db)
                if payload.graph_id is None:
                    built_graph = await graph_service.create_default_deep_agents_graph(
                        llm_model=llm_params["llm_model"],
                        api_key=llm_params["api_key"],
                        base_url=llm_params["base_url"],
                        max_tokens=llm_params["max_tokens"],
                        user_id=handler.user_id,
                        file_emitter=file_emitter,
                    )
                else:
                    from app.repositories.user import UserRepository

                    user_repo = UserRepository(db)
                    current_user = await user_repo.get_by_id(handler.user_id)
                    built_graph = await graph_service.create_graph_by_graph_id(
                        graph_id=payload.graph_id,
                        llm_model=llm_params["llm_model"],
                        api_key=llm_params["api_key"],
                        base_url=llm_params["base_url"],
                        max_tokens=llm_params["max_tokens"],
                        user_id=handler.user_id,
                        current_user=current_user,
                        file_emitter=file_emitter,
                        thread_id=thread_id,
                    )

            state = module.StreamState(thread_id)
            current_task = asyncio.current_task()
            if current_task is None:
                raise RuntimeError("missing current asyncio task")
            if handler._task_supervisor.get(request_id) is None:
                handler._task_supervisor.register(
                    request_id,
                    ChatTaskEntry(
                        request_id=request_id,
                        thread_id=thread_id,
                        task=current_task,
                        run_id=agent_run_id,
                        persist_on_disconnect=tolerate_disconnect,
                    ),
                )
            else:
                handler._task_supervisor.update(
                    request_id,
                    thread_id=thread_id,
                    task=current_task,
                    run_id=agent_run_id,
                    persist_on_disconnect=tolerate_disconnect,
                )
            await module.task_manager.register_task(thread_id, current_task)

            if agent_run_id is not None:
                await handler._mark_run_status(
                    run_id=agent_run_id,
                    status=AgentRunStatus.RUNNING,
                    runtime_owner_id=handler._runtime_owner_id,
                )
                heartbeat_task = asyncio.create_task(
                    handler._run_persisted_run_heartbeat(agent_run_id),
                    name=f"run-heartbeat:{agent_run_id}",
                )
                handler._task_supervisor.update(request_id, heartbeat_task=heartbeat_task)
                await handler._append_run_event(
                    run_id=agent_run_id,
                    event_type="assistant_message_started",
                    payload={
                        "message": {
                            "id": assistant_message_id,
                            "role": "assistant",
                            "content": "",
                            "timestamp": int(time.time() * 1000),
                            "tool_calls": [],
                        }
                    },
                )

            await handler._send(
                {
                    "type": "accepted",
                    "request_id": request_id,
                    "thread_id": thread_id,
                    "run_id": str(agent_run_id) if agent_run_id is not None else None,
                    "timestamp": int(time.time() * 1000),
                    "data": {"status": "accepted"},
                },
                tolerate_disconnect=tolerate_disconnect,
            )

            stream_handler = module.StreamEventHandler()
            artifact_collector.ensure_run_dir(handler.user_id, thread_id, state.artifact_run_id)

            await handler._send_stream_event(
                stream_handler.format_sse(
                    "status",
                    {"status": "connected", "_meta": {"node_name": "system"}},
                    thread_id,
                ),
                request_id,
                tolerate_disconnect=tolerate_disconnect,
                agent_run_id=agent_run_id,
                assistant_message_id=assistant_message_id,
            )

            enriched_message = module._enrich_message(
                payload.message,
                payload.metadata,
                is_new_thread=(payload.thread_id is None),
                log=module.logger.bind(user_id=handler.user_id, thread_id=thread_id),
                endpoint="Chat WS",
            )

            interrupted = False
            async for event in built_graph.astream_events(
                {"messages": [module.HumanMessage(content=enriched_message)], "context": initial_context},
                config=config,
                version="v2",
            ):
                if await module.task_manager.is_stopped(thread_id):
                    state.stopped = True
                    break

                async for sse_str in module._dispatch_stream_event(event, stream_handler, state, file_emitter):
                    await handler._send_stream_event(
                        sse_str,
                        request_id,
                        tolerate_disconnect=tolerate_disconnect,
                        agent_run_id=agent_run_id,
                        assistant_message_id=assistant_message_id,
                    )

            try:
                snap = await module.safe_get_state(
                    built_graph,
                    config,
                    max_retries=3,
                    initial_delay=0.1,
                    log=module.logger,
                )
                if snap.tasks:
                    next_node = snap.tasks[0].target if snap.tasks else None
                    current_state = snap.values or {}
                    if payload.graph_id is None:
                        module.logger.warning(
                            f"Default agent interrupted, resume not supported | thread_id={thread_id}"
                        )
                    else:
                        await handler._emit_event(
                            {
                                "type": "interrupt",
                                "thread_id": thread_id,
                                "node_name": next_node or "unknown",
                                "node_label": next_node.replace("_", " ").title() if next_node else "Unknown Node",
                                "data": {
                                    "node_name": next_node or "unknown",
                                    "node_label": next_node.replace("_", " ").title() if next_node else "Unknown Node",
                                    "state": current_state,
                                    "thread_id": thread_id,
                                },
                            },
                            request_id=request_id,
                            tolerate_disconnect=tolerate_disconnect,
                            agent_run_id=agent_run_id,
                            assistant_message_id=assistant_message_id,
                        )
                        async with module.AsyncSessionLocal() as session:
                            result_query = await session.execute(
                                module.select(module.Conversation).where(module.Conversation.thread_id == thread_id)
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
                module.logger.warning(f"Failed to inspect interrupt state | thread_id={thread_id} | error={exc}")

            if state and not state.all_messages and not state.stopped and not interrupted:
                try:
                    snap = await module.safe_get_state(
                        built_graph,
                        config,
                        max_retries=2,
                        initial_delay=0.05,
                        log=module.logger,
                    )
                    if snap.values and "messages" in snap.values:
                        msgs = snap.values["messages"]
                        from langgraph.types import Overwrite

                        state.all_messages = msgs.value if isinstance(msgs, Overwrite) else msgs
                except Exception as exc:
                    module.logger.warning(f"Failed to fetch final state | thread_id={thread_id} | error={exc}")

            if state.interrupted:
                return

            if state.stopped:
                await handler._emit_event(
                    {
                        "type": "error",
                        "thread_id": thread_id,
                        "node_name": "system",
                        "run_id": "",
                        "timestamp": int(time.time() * 1000),
                        "data": {"message": "Stopped by user", "code": "stopped"},
                    },
                    request_id=request_id,
                    tolerate_disconnect=tolerate_disconnect,
                    agent_run_id=agent_run_id,
                    assistant_message_id=assistant_message_id,
                )

            await handler._emit_event(
                {
                    "type": "done",
                    "thread_id": thread_id,
                    "node_name": "system",
                    "run_id": "",
                    "timestamp": int(time.time() * 1000),
                    "data": {},
                },
                request_id=request_id,
                tolerate_disconnect=tolerate_disconnect,
                agent_run_id=agent_run_id,
                assistant_message_id=assistant_message_id,
            )

        except asyncio.CancelledError:
            if state is not None:
                state.stopped = True
            try:
                await handler._emit_event(
                    {
                        "type": "done",
                        "thread_id": thread_id or payload.thread_id or "",
                        "node_name": "system",
                        "run_id": "",
                        "timestamp": int(time.time() * 1000),
                        "data": {},
                    },
                    request_id=request_id,
                    tolerate_disconnect=tolerate_disconnect,
                    agent_run_id=agent_run_id,
                    assistant_message_id=assistant_message_id,
                )
            except Exception:
                _logger.debug("error sending stream event", exc_info=True)
            raise
        except Exception as exc:
            if state is not None and not (module.GraphBubbleUp is not None and type(exc) is module.GraphBubbleUp):
                state.has_error = True
            error_data: dict[str, object] = {"message": str(exc)}
            if isinstance(exc, ModelConfigError):
                error_data["error_code"] = exc.error_code
                error_data["params"] = exc.params
            await handler._emit_event(
                {
                    "type": "error",
                    "thread_id": thread_id or payload.thread_id or "",
                    "node_name": "system",
                    "run_id": "",
                    "timestamp": int(time.time() * 1000),
                    "data": error_data,
                },
                request_id=request_id,
                tolerate_disconnect=tolerate_disconnect,
                agent_run_id=agent_run_id,
                assistant_message_id=assistant_message_id,
            )
            await handler._emit_event(
                {
                    "type": "done",
                    "thread_id": thread_id or payload.thread_id or "",
                    "node_name": "system",
                    "run_id": "",
                    "timestamp": int(time.time() * 1000),
                    "data": {},
                },
                request_id=request_id,
                tolerate_disconnect=tolerate_disconnect,
                agent_run_id=agent_run_id,
                assistant_message_id=assistant_message_id,
            )
        finally:
            await _release_graph_sandbox(built_graph)

            await handler._finalize_task(
                request_id=request_id,
                thread_id=thread_id,
                state=state,
                built_graph=built_graph,
                artifact_collector=artifact_collector,
                graph_id=str(payload.graph_id) if payload.graph_id else None,
                workspace_id=graph_workspace_id,
                graph_name=graph_display_name,
            )

    async def execute_resume_turn(self, request_id: str, thread_id: str, command: dict[str, object]) -> None:
        """Resume an interrupted graph execution and stream the remaining events."""
        from app.core.trace_context import set_trace_id

        set_trace_id(request_id)
        handler = self._handler
        module = self._module
        state: StreamState | None = None
        built_graph = None
        graph_workspace_id: str | None = None
        graph_display_name: str | None = None
        graph_id = None
        config = None
        stream_handler = None
        ws_command = None
        agent_run_id: uuid_lib.UUID | None = None
        tolerate_disconnect = False
        assistant_message_id = f"msg-assistant-{uuid_lib.uuid4()}"

        try:
            async with module.AsyncSessionLocal() as db:
                result = await db.execute(
                    module.select(module.Conversation).where(
                        module.Conversation.thread_id == thread_id,
                        module.Conversation.user_id == handler.user_id,
                    )
                )
                conversation = result.scalar_one_or_none()
                if not conversation:
                    await handler._send(
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
                    await handler._send({"type": "ws_error", "request_id": request_id, "message": "graph id not found"})
                    return

                config, _, llm_params = await module.get_user_config(handler.user_id, thread_id, db)

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
                current_user = await user_repo.get_by_id(handler.user_id)

                graph_service = module.GraphService(db)
                built_graph = await graph_service.create_graph_by_graph_id(
                    graph_id=graph_id,
                    llm_model=llm_params["llm_model"],
                    api_key=llm_params["api_key"],
                    base_url=llm_params["base_url"],
                    max_tokens=llm_params["max_tokens"],
                    user_id=handler.user_id,
                    current_user=current_user,
                )

                snap = await module.safe_get_state(
                    built_graph,
                    config,
                    max_retries=3,
                    initial_delay=0.1,
                    log=module.logger,
                )
                if not snap.tasks:
                    await handler._send(
                        {"type": "ws_error", "request_id": request_id, "message": "no interrupt state found"}
                    )
                    return

                state = module.StreamState(thread_id)
                current_task = asyncio.current_task()
                if current_task is None:
                    raise RuntimeError("missing current asyncio task")
                if handler._task_supervisor.get(request_id) is None:
                    handler._task_supervisor.register(
                        request_id,
                        ChatTaskEntry(request_id=request_id, thread_id=thread_id, task=current_task),
                    )
                else:
                    handler._task_supervisor.update(request_id, thread_id=thread_id, task=current_task)
                await module.task_manager.register_task(thread_id, current_task)

                task_entry = handler._task_supervisor.get(request_id)
                agent_run_id = task_entry.run_id if task_entry else None
                tolerate_disconnect = bool(task_entry and task_entry.persist_on_disconnect)

            if agent_run_id is not None:
                await handler._mark_run_status(
                    run_id=agent_run_id,
                    status=AgentRunStatus.RUNNING,
                    runtime_owner_id=handler._runtime_owner_id,
                )
                heartbeat_task = asyncio.create_task(
                    handler._run_persisted_run_heartbeat(agent_run_id),
                    name=f"run-heartbeat:{agent_run_id}",
                )
                handler._task_supervisor.update(request_id, heartbeat_task=heartbeat_task)
                await handler._append_run_event(
                    run_id=agent_run_id,
                    event_type="assistant_message_started",
                    payload={
                        "message": {
                            "id": assistant_message_id,
                            "role": "assistant",
                            "content": "",
                            "timestamp": int(time.time() * 1000),
                            "tool_calls": [],
                        }
                    },
                )

            await handler._send(
                {
                    "type": "accepted",
                    "request_id": request_id,
                    "thread_id": thread_id,
                    "run_id": str(agent_run_id) if agent_run_id is not None else None,
                    "timestamp": int(time.time() * 1000),
                    "data": {"status": "accepted"},
                },
                tolerate_disconnect=tolerate_disconnect,
            )

            stream_handler = module.StreamEventHandler()
            ws_command = Command(update=command.get("update") or {}, goto=command.get("goto") or None)

            await handler._send_stream_event(
                stream_handler.format_sse("status", {"status": "resumed", "_meta": {"node_name": "system"}}, thread_id),
                request_id,
                tolerate_disconnect=tolerate_disconnect,
                agent_run_id=agent_run_id,
                assistant_message_id=assistant_message_id,
            )

            interrupted = False
            async for event in built_graph.astream_events(ws_command, config=config, version="v2"):
                if await module.task_manager.is_stopped(thread_id):
                    state.stopped = True
                    break
                async for sse_str in module._dispatch_stream_event(event, stream_handler, state):
                    await handler._send_stream_event(
                        sse_str,
                        request_id,
                        tolerate_disconnect=tolerate_disconnect,
                        agent_run_id=agent_run_id,
                        assistant_message_id=assistant_message_id,
                    )

            try:
                snap = await module.safe_get_state(
                    built_graph,
                    config,
                    max_retries=3,
                    initial_delay=0.1,
                    log=module.logger,
                )
                if snap.tasks:
                    next_node = snap.tasks[0].target if snap.tasks else None
                    current_state = snap.values or {}
                    await handler._emit_event(
                        {
                            "type": "interrupt",
                            "thread_id": thread_id,
                            "node_name": next_node or "unknown",
                            "node_label": next_node.replace("_", " ").title() if next_node else "Unknown Node",
                            "data": {
                                "node_name": next_node or "unknown",
                                "node_label": next_node.replace("_", " ").title() if next_node else "Unknown Node",
                                "state": current_state,
                                "thread_id": thread_id,
                            },
                        },
                        request_id=request_id,
                        tolerate_disconnect=tolerate_disconnect,
                        agent_run_id=agent_run_id,
                        assistant_message_id=assistant_message_id,
                    )
                    state.interrupted = True
                    state.interrupt_node = next_node
                    state.interrupt_state = current_state
                    interrupted = True
            except Exception as exc:
                module.logger.warning(f"Failed to inspect resume interrupt state | thread_id={thread_id} | error={exc}")

            if not state.all_messages and not state.stopped and not interrupted:
                try:
                    snap = await module.safe_get_state(
                        built_graph,
                        config,
                        max_retries=2,
                        initial_delay=0.05,
                        log=module.logger,
                    )
                    if snap.values and "messages" in snap.values:
                        msgs = snap.values["messages"]
                        from langgraph.types import Overwrite

                        state.all_messages = msgs.value if isinstance(msgs, Overwrite) else msgs
                except Exception as exc:
                    module.logger.warning(f"Failed to fetch final resume state | thread_id={thread_id} | error={exc}")

            if state.interrupted:
                return

            if state.stopped:
                await handler._emit_event(
                    {
                        "type": "error",
                        "thread_id": thread_id,
                        "node_name": "system",
                        "run_id": "",
                        "timestamp": int(time.time() * 1000),
                        "data": {"message": "Stopped by user", "code": "stopped"},
                    },
                    request_id=request_id,
                    tolerate_disconnect=tolerate_disconnect,
                    agent_run_id=agent_run_id,
                    assistant_message_id=assistant_message_id,
                )

            await handler._emit_event(
                {
                    "type": "done",
                    "thread_id": thread_id,
                    "node_name": "system",
                    "run_id": "",
                    "timestamp": int(time.time() * 1000),
                    "data": {},
                },
                request_id=request_id,
                tolerate_disconnect=tolerate_disconnect,
                agent_run_id=agent_run_id,
                assistant_message_id=assistant_message_id,
            )

        except asyncio.CancelledError:
            if state is not None:
                state.stopped = True
            try:
                await handler._emit_event(
                    {
                        "type": "done",
                        "thread_id": thread_id,
                        "node_name": "system",
                        "run_id": "",
                        "timestamp": int(time.time() * 1000),
                        "data": {},
                    },
                    request_id=request_id,
                    tolerate_disconnect=tolerate_disconnect,
                    agent_run_id=agent_run_id,
                    assistant_message_id=assistant_message_id,
                )
            except Exception:
                _logger.debug("error during turn cleanup", exc_info=True)
            raise
        except Exception as exc:
            if state is not None and not (module.GraphBubbleUp is not None and type(exc) is module.GraphBubbleUp):
                state.has_error = True
            await handler._emit_event(
                {
                    "type": "error",
                    "thread_id": thread_id,
                    "node_name": "system",
                    "run_id": "",
                    "timestamp": int(time.time() * 1000),
                    "data": {"message": str(exc)},
                },
                request_id=request_id,
                tolerate_disconnect=tolerate_disconnect,
                agent_run_id=agent_run_id,
                assistant_message_id=assistant_message_id,
            )
            await handler._emit_event(
                {
                    "type": "done",
                    "thread_id": thread_id,
                    "node_name": "system",
                    "run_id": "",
                    "timestamp": int(time.time() * 1000),
                    "data": {},
                },
                request_id=request_id,
                tolerate_disconnect=tolerate_disconnect,
                agent_run_id=agent_run_id,
                assistant_message_id=assistant_message_id,
            )
        finally:
            await _release_graph_sandbox(built_graph)

            await handler._finalize_task(
                request_id=request_id,
                thread_id=thread_id,
                state=state,
                built_graph=built_graph,
                artifact_collector=None,
                graph_id=str(graph_id) if graph_id else None,
                workspace_id=graph_workspace_id,
                graph_name=graph_display_name,
            )

    async def execute_copilot_turn(
        self,
        request_id: str,
        payload: ChatRequest,
        graph_context: dict[str, Any],
        conversation_history: list[dict[str, Any]],
        mode: str,
    ) -> None:
        """Execute a copilot turn: consume CopilotService stream and emit events."""
        from app.core.trace_context import set_trace_id

        set_trace_id(request_id)
        handler = self._handler
        module = self._module
        state: StreamState | None = None
        thread_id: str | None = None
        task_entry = handler._task_supervisor.get(request_id)
        agent_run_id = task_entry.run_id if task_entry else None
        tolerate_disconnect = bool(task_entry and task_entry.persist_on_disconnect)
        assistant_message_id = f"msg-assistant-{uuid_lib.uuid4()}"

        # Collection vars for graph persistence
        final_actions: list[dict[str, Any]] = []

        try:
            async with module.AsyncSessionLocal() as db:
                # Get or create thread for this copilot turn
                thread_id, _ = await module.get_or_create_conversation(
                    payload.thread_id,
                    payload.message,
                    handler.user_id,
                    payload.metadata,
                    db,
                )
                await module.save_user_message(thread_id, payload.message, payload.metadata, db)

            state = module.StreamState(thread_id)
            current_task = asyncio.current_task()
            if current_task is None:
                raise RuntimeError("missing current asyncio task")
            if handler._task_supervisor.get(request_id) is None:
                handler._task_supervisor.register(
                    request_id,
                    ChatTaskEntry(
                        request_id=request_id,
                        thread_id=thread_id,
                        task=current_task,
                        run_id=agent_run_id,
                        persist_on_disconnect=tolerate_disconnect,
                    ),
                )
            else:
                handler._task_supervisor.update(
                    request_id,
                    thread_id=thread_id,
                    task=current_task,
                    run_id=agent_run_id,
                    persist_on_disconnect=tolerate_disconnect,
                )
            await module.task_manager.register_task(thread_id, current_task)

            # Start heartbeat if persisted run
            if agent_run_id is not None:
                await handler._mark_run_status(
                    run_id=agent_run_id,
                    status=AgentRunStatus.RUNNING,
                    runtime_owner_id=handler._runtime_owner_id,
                )
                heartbeat_task = asyncio.create_task(
                    handler._run_persisted_run_heartbeat(agent_run_id),
                    name=f"run-heartbeat:{agent_run_id}",
                )
                handler._task_supervisor.update(request_id, heartbeat_task=heartbeat_task)

            # Emit accepted
            await handler._send(
                {
                    "type": "accepted",
                    "request_id": request_id,
                    "thread_id": thread_id,
                    "run_id": str(agent_run_id) if agent_run_id is not None else None,
                    "timestamp": int(time.time() * 1000),
                    "data": {"status": "accepted"},
                },
                tolerate_disconnect=tolerate_disconnect,
            )

            # Create CopilotService and get stream
            from app.services.copilot_service import CopilotService

            async with module.AsyncSessionLocal() as db:
                # payload.model carries the frontend-selected model (e.g. "anthropic:claude-3-7-sonnet")
                service = CopilotService(
                    user_id=handler.user_id,
                    llm_model=payload.model,
                    db=db,
                )
                stream = service._get_copilot_stream(
                    prompt=payload.message,
                    graph_context=graph_context,
                    conversation_history=conversation_history,
                    mode=mode,
                    graph_id=str(payload.graph_id) if payload.graph_id else None,
                )

                async for event in stream:
                    if await module.task_manager.is_stopped(thread_id):
                        state.stopped = True
                        break

                    event_type = event.get("type", "")

                    # Collect for persistence
                    if event_type == "result":
                        final_actions = event.get("actions", [])

                    # Emit to WS + run events
                    await handler._emit_event(
                        {
                            "type": event_type,
                            "thread_id": thread_id,
                            "node_name": "copilot",
                            "timestamp": int(time.time() * 1000),
                            "data": event,
                        },
                        request_id=request_id,
                        tolerate_disconnect=tolerate_disconnect,
                        agent_run_id=agent_run_id,
                        assistant_message_id=assistant_message_id,
                    )

            # Persist graph changes
            # _persist_graph_from_actions creates its own DB session internally,
            # so we only need user_id set on the service.
            if payload.graph_id and final_actions:
                persist_service = CopilotService(user_id=handler.user_id)
                await persist_service._persist_graph_from_actions(
                    graph_id=str(payload.graph_id),
                    final_actions=final_actions,
                )

            # Emit done
            await handler._emit_event(
                {
                    "type": "done",
                    "thread_id": thread_id,
                    "node_name": "copilot",
                    "timestamp": int(time.time() * 1000),
                    "data": {},
                },
                request_id=request_id,
                tolerate_disconnect=tolerate_disconnect,
                agent_run_id=agent_run_id,
                assistant_message_id=assistant_message_id,
            )

        except asyncio.CancelledError:
            if state is not None:
                state.stopped = True
            try:
                await handler._emit_event(
                    {
                        "type": "done",
                        "thread_id": thread_id or "",
                        "node_name": "copilot",
                        "timestamp": int(time.time() * 1000),
                        "data": {},
                    },
                    request_id=request_id,
                    tolerate_disconnect=tolerate_disconnect,
                    agent_run_id=agent_run_id,
                    assistant_message_id=assistant_message_id,
                )
            except Exception:
                _logger.debug("error during copilot turn cleanup", exc_info=True)
            raise
        except Exception as exc:
            if state is not None:
                state.has_error = True
            error_data: dict[str, object] = {"message": str(exc)}
            if isinstance(exc, ModelConfigError):
                error_data["error_code"] = exc.error_code
                error_data["params"] = exc.params
            await handler._emit_event(
                {
                    "type": "error",
                    "thread_id": thread_id or "",
                    "node_name": "copilot",
                    "timestamp": int(time.time() * 1000),
                    "data": error_data,
                },
                request_id=request_id,
                tolerate_disconnect=tolerate_disconnect,
                agent_run_id=agent_run_id,
                assistant_message_id=assistant_message_id,
            )
            await handler._emit_event(
                {
                    "type": "done",
                    "thread_id": thread_id or "",
                    "node_name": "copilot",
                    "timestamp": int(time.time() * 1000),
                    "data": {},
                },
                request_id=request_id,
                tolerate_disconnect=tolerate_disconnect,
                agent_run_id=agent_run_id,
                assistant_message_id=assistant_message_id,
            )
        finally:
            await handler._finalize_task(
                request_id=request_id,
                thread_id=thread_id,
                state=state,
                built_graph=None,
                artifact_collector=None,
                graph_id=str(payload.graph_id) if payload.graph_id else None,
                workspace_id=None,
                graph_name=None,
            )

    @staticmethod
    def _parse_uuid(value: object) -> uuid_lib.UUID | None:
        """Parse a value into a UUID, returning None on failure."""
        if not value:
            return None
        try:
            return uuid_lib.UUID(str(value))
        except (ValueError, TypeError):
            return None
