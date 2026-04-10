"""
Module: Chat API (Production Ready)

Overview:
- Streaming helper module reused by the chat WebSocket handler
- Provide LangGraph event dispatch, state queries, message persistence, and result archival
- No longer exposes a `/v1/chat` HTTP endpoint

Dependencies:
- Database: async SQLAlchemy session
- LangGraph: v2 event stream processing
- WebSocket chat handler: `app.websocket.chat_ws_handler`
"""

import asyncio
import uuid
from typing import Any, AsyncGenerator, Dict

from langchain.messages import AIMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.settings import settings
from app.models import Conversation, Message
from app.utils.datetime import utc_now
from app.utils.file_event_emitter import FileEventEmitter
from app.utils.stream_event_handler import StreamEventHandler, StreamState

# LangGraph control-flow exception: do not mark trace as FAILED
try:
    from langgraph.errors import GraphBubbleUp
except ImportError:
    GraphBubbleUp = None  # type: ignore[misc, assignment]


async def safe_get_state(
    graph: Any, config: RunnableConfig, max_retries: int = 3, initial_delay: float = 0.1, log: Any = None
) -> Any:
    """
    Safely retrieve graph state with retry logic to avoid connection conflicts.

    Args:
        graph: LangGraph graph instance
        config: RunnableConfig configuration
        max_retries: maximum number of retries
        initial_delay: initial delay in seconds, doubled on each retry
        log: optional logger

    Returns:
        Graph state snapshot

    Raises:
        Exception: if all retries are exhausted
    """
    if log is None:
        log = logger

    last_error = None
    delay = initial_delay

    for attempt in range(max_retries):
        try:
            snap = await graph.aget_state(config)
            return snap
        except Exception as e:
            last_error = e
            error_msg = str(e)

            # check for connection conflict error
            is_connection_error = (
                "another command is already in progress" in error_msg.lower() or "connection" in error_msg.lower()
            )

            # last attempt — stop retrying
            if attempt >= max_retries - 1:
                break

            # connection error — wait and retry
            if is_connection_error:
                log.debug(
                    f"Connection conflict detected (attempt {attempt + 1}/{max_retries}), "
                    f"retrying after {delay:.2f}s delay"
                )
                await asyncio.sleep(delay)
                delay *= 2  # exponential backoff
            else:
                # non-connection error — log warning but still retry (may be transient)
                log.warning(f"Failed to get state (attempt {attempt + 1}/{max_retries}): {e}")
                await asyncio.sleep(delay)
                delay *= 2

    # all retries exhausted
    log.error(f"Failed to get state after {max_retries} attempts: {last_error}")
    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to get state after all retries")


# ==================== Persistence Logic ====================


async def save_run_result(
    thread_id: str,
    state: StreamState,
    log,
    *,
    graph_id: str | None = None,
    workspace_id: str | None = None,
    user_id: str | None = None,
    graph_name: str | None = None,
) -> None:
    """
    Persist run results.

    Use a fresh DB session to ensure the connection is available even when
    called from a finally block. Also batch-persist Trace + Observations.
    """
    # --- 1. persist messages ---
    if state.assistant_content or state.all_messages:
        if not state.all_messages and state.assistant_content:
            log.warning(f"Using fallback content accumulation for thread {thread_id}")
            state.all_messages = [AIMessage(content=state.assistant_content)]

        if state.all_messages:
            try:
                async with AsyncSessionLocal() as session:
                    await save_assistant_message(thread_id, state.all_messages, session, update_conversation=True)
                    log.info(f"Persisted messages for thread {thread_id}")
            except asyncio.CancelledError:
                log.warning(f"Save run result cancelled for thread {thread_id}")
            except Exception as e:
                log.error(f"Failed to persist messages for thread {thread_id}: {e}")

    # --- 2. persist Trace + Observations (transaction-safe) ---
    all_observations = state.get_all_observations()
    if all_observations:
        try:
            await _persist_trace_data(
                state,
                log,
                observations=all_observations,
                graph_id=graph_id,
                workspace_id=workspace_id,
                user_id=user_id,
                graph_name=graph_name,
            )
        except asyncio.CancelledError:
            log.debug(f"Trace persistence cancelled for thread {thread_id}")
        except Exception as e:
            log.warning(f"Failed to persist trace data for thread {thread_id}: {e}")


async def _persist_trace_data(
    state: StreamState,
    log,
    *,
    observations: list | None = None,
    graph_id: str | None = None,
    workspace_id: str | None = None,
    user_id: str | None = None,
    graph_name: str | None = None,
) -> None:
    """
    Batch-write accumulated Observation data from StreamState to the database.

    Transaction-safe: uses session.begin() for atomicity.
    Incomplete observations are marked INTERRUPTED by state.get_all_observations().
    """
    from datetime import datetime, timezone

    from app.models.execution_trace import (
        ExecutionObservation,
        ExecutionTrace,
        ObservationLevel,
        ObservationStatus,
        ObservationType,
        TraceStatus,
    )
    from app.utils.stream_event_handler import ObsLevel, ObsStatus, ObsType

    all_obs = observations if observations is not None else state.get_all_observations()
    if not all_obs:
        return

    # determine trace status
    if state.has_error:
        trace_status = TraceStatus.FAILED
    elif state.interrupted:
        trace_status = TraceStatus.INTERRUPTED
    elif state.stopped:
        trace_status = TraceStatus.FAILED
    else:
        trace_status = TraceStatus.COMPLETED

    now = datetime.now(timezone.utc)
    trace_start = datetime.fromtimestamp(state.trace_start_time / 1000, tz=timezone.utc)
    duration_ms = int(now.timestamp() * 1000 - state.trace_start_time)

    # aggregate token statistics
    total_tokens = 0
    for obs_rec in all_obs:
        if obs_rec.type == ObsType.GENERATION and obs_rec.total_tokens:
            total_tokens += obs_rec.total_tokens

    # build ExecutionTrace ORM object
    trace_uuid = uuid.UUID(state.trace_id)
    trace = ExecutionTrace(
        id=trace_uuid,
        workspace_id=uuid.UUID(workspace_id) if workspace_id else None,
        graph_id=uuid.UUID(graph_id) if graph_id else None,
        thread_id=state.thread_id,
        user_id=user_id,
        name=graph_name or "graph_execution",
        status=trace_status,
        start_time=trace_start,
        end_time=now,
        duration_ms=duration_ms,
        total_tokens=total_tokens or None,
    )

    # enum mapping
    type_map = {
        ObsType.SPAN: ObservationType.SPAN,
        ObsType.GENERATION: ObservationType.GENERATION,
        ObsType.TOOL: ObservationType.TOOL,
        ObsType.EVENT: ObservationType.EVENT,
    }
    level_map = {
        ObsLevel.DEBUG: ObservationLevel.DEBUG,
        ObsLevel.DEFAULT: ObservationLevel.DEFAULT,
        ObsLevel.WARNING: ObservationLevel.WARNING,
        ObsLevel.ERROR: ObservationLevel.ERROR,
    }
    status_map = {
        ObsStatus.RUNNING: ObservationStatus.RUNNING,
        ObsStatus.COMPLETED: ObservationStatus.COMPLETED,
        ObsStatus.FAILED: ObservationStatus.FAILED,
        ObsStatus.INTERRUPTED: ObservationStatus.INTERRUPTED,
    }

    # build ExecutionObservation ORM objects
    db_observations = []
    for rec in all_obs:
        obs = ExecutionObservation(
            id=uuid.UUID(rec.id),
            trace_id=trace_uuid,
            parent_observation_id=uuid.UUID(rec.parent_observation_id) if rec.parent_observation_id else None,
            type=type_map.get(rec.type, ObservationType.EVENT),
            name=rec.name,
            level=level_map.get(rec.level, ObservationLevel.DEFAULT),
            status=status_map.get(rec.status, ObservationStatus.COMPLETED),
            status_message=rec.status_message,
            start_time=datetime.fromtimestamp(rec.start_time / 1000, tz=timezone.utc),
            end_time=datetime.fromtimestamp(rec.end_time / 1000, tz=timezone.utc) if rec.end_time else None,
            duration_ms=rec.duration_ms,
            completion_start_time=(
                datetime.fromtimestamp(rec.completion_start_time / 1000, tz=timezone.utc)
                if rec.completion_start_time
                else None
            ),
            input=rec.input_data,
            output=rec.output_data,
            model_name=rec.model_name,
            model_provider=rec.model_provider,
            model_parameters=rec.model_parameters,
            prompt_tokens=rec.prompt_tokens,
            completion_tokens=rec.completion_tokens,
            total_tokens=rec.total_tokens,
            metadata_=rec.metadata,
            version=rec.version,
        )
        db_observations.append(obs)

    # transaction-safe batch insert
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(trace)
            session.add_all(db_observations)
        # commit is automatic when begin() context exits
    log.info(f"Persisted trace {state.trace_id} with {len(db_observations)} observations | thread={state.thread_id}")


# ==================== Database Operations ====================


async def get_or_create_conversation(
    thread_id: str | None,
    message: str,
    user_id: str,
    metadata: dict | None,
    db: AsyncSession,
) -> tuple[str, Conversation]:
    if not thread_id:
        # No thread_id provided, create new conversation
        thread_id = str(uuid.uuid4())
        conversation = Conversation(
            thread_id=thread_id,
            user_id=user_id,
            title=message[:50] if len(message) > 50 else message,
            meta_data=metadata or {},
        )
        db.add(conversation)
        await db.commit()
        return thread_id, conversation
    else:
        # Thread_id provided, try to find existing conversation
        result = await db.execute(
            select(Conversation).where(Conversation.thread_id == thread_id, Conversation.user_id == user_id)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            # Conversation not found - create new one with the provided thread_id
            # This allows frontend to generate thread_id and let backend create conversation on first message
            conversation = Conversation(
                thread_id=thread_id,
                user_id=user_id,
                title=message[:50] if len(message) > 50 else message,
                meta_data=metadata or {},
            )
            db.add(conversation)
            await db.commit()
            await db.refresh(conversation)
            return thread_id, conversation
        return thread_id, conv


async def get_user_config(user_id: str, thread_id: str):
    """Retrieve user configuration (RunnableConfig for LangGraph)."""
    from app.core.agent.langfuse_callback import get_langfuse_callbacks
    from app.core.trace_context import get_trace_id

    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id, "user_id": str(user_id), "trace_id": get_trace_id()},
        "recursion_limit": 300,
        "callbacks": get_langfuse_callbacks(enabled=settings.langfuse_enabled),
    }

    return config, {}


async def save_user_message(thread_id: str, message: str, metadata: dict | None, db: AsyncSession):
    user_message = Message(
        thread_id=thread_id,
        role="user",
        content=message,
        meta_data=metadata or {},
    )
    db.add(user_message)
    await db.commit()


async def save_assistant_message(
    thread_id: str, messages: list[BaseMessage], db: AsyncSession, update_conversation: bool = True
):
    """Save assistant message, extracting tool calls if present."""
    # find the last AI message
    ai_msg = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if not ai_msg:
        return

    meta_data = dict(ai_msg.additional_kwargs) if ai_msg.additional_kwargs else {}

    # extract tool calls (simplified — a strict implementation would match subsequent ToolMessages by ID)
    if hasattr(ai_msg, "tool_calls") and ai_msg.tool_calls:
        tool_calls_data = []
        for tc in ai_msg.tool_calls:
            tool_calls_data.append({"name": tc.get("name"), "arguments": tc.get("args"), "id": tc.get("id")})
        meta_data["tool_calls"] = tool_calls_data

    message = Message(
        thread_id=thread_id,
        role="assistant",
        content=str(ai_msg.content) if ai_msg.content else "",
        meta_data=meta_data,
    )
    db.add(message)

    if update_conversation:
        result = await db.execute(select(Conversation).where(Conversation.thread_id == thread_id))
        if conv := result.scalar_one_or_none():
            conv.updated_at = utc_now()
    await db.commit()


async def _clear_interrupt_marker(thread_id: str, log: Any) -> None:
    """Clear the interrupted_graph_id marker from Conversation metadata."""
    try:
        async with AsyncSessionLocal() as session:
            result_query = await session.execute(select(Conversation).where(Conversation.thread_id == thread_id))
            if conv := result_query.scalar_one_or_none():
                if conv.meta_data and "interrupted_graph_id" in conv.meta_data:
                    del conv.meta_data["interrupted_graph_id"]
                    await session.commit()
                    log.debug(f"Cleared interrupt marker from conversation | thread_id={thread_id}")
    except asyncio.CancelledError:
        log.debug(f"Clear interrupt marker cancelled for thread {thread_id} (connection closing)")
    except Exception as e:
        log.warning(f"Failed to clear interrupt marker for conversation | thread_id={thread_id} | error={e}")


# ==================== Message Enrichment ====================


def _enrich_message(message: str, metadata: dict, *, is_new_thread: bool, log, endpoint: str) -> str:
    """Append edit_skill_id context (first message only) and file info to user message."""
    enriched = message

    # Only inject editing context on the first message of a new thread
    edit_skill_id = metadata.get("edit_skill_id")
    if edit_skill_id and is_new_thread:
        log.info(f"[{endpoint}] edit-skill mode: edit_skill_id={edit_skill_id}")
        enriched += (
            f"\n\n[Editing Mode] The user wants to modify an existing skill (ID: {edit_skill_id}). "
            f"The skill files have been pre-loaded into the sandbox. "
            f"Read the existing files first, then apply the user's requested changes."
        )

    files = metadata.get("files", [])
    if files:
        log.info(f"[{endpoint}] found {len(files)} attached file(s): {files}")
        file_lines = "\n".join([f"- {f['filename']}: {f['path']}" for f in files])
        enriched += f"\n\nAttached files:\n{file_lines}\nUse the read_file tool to read the content of these files."
        log.info(f"[{endpoint}] message enriched with file paths, length={len(enriched)}")

    return enriched


# ==================== Event Dispatch Helpers ====================


def _extract_run_ids(event_dict: dict) -> tuple[str, str | None]:
    """
    Extract run_id and parent_run_id from a LangGraph v2 event.

    Each LangGraph v2 astream_events event contains:
    - run_id: unique identifier for the event (UUID or str)
    - parent_ids: list ordered from root to immediate parent

    All values are normalised to str to avoid UUID-as-dict-key issues.
    """
    raw_run_id = event_dict.get("run_id")
    run_id = str(raw_run_id) if raw_run_id else ""
    parent_ids = event_dict.get("parent_ids", [])
    parent_run_id = str(parent_ids[-1]) if parent_ids else None
    return run_id, parent_run_id


async def _dispatch_stream_event(
    event: Any,
    handler: StreamEventHandler,
    state: StreamState,
    file_emitter: FileEventEmitter | None = None,
) -> AsyncGenerator[str, None]:
    """
    Translate a single LangGraph v2 astream_events event into SSE strings.

    Yields zero or more SSE strings. Callers: ``async for sse in _dispatch_stream_event(...): yield sse``.
    file_emitter is only passed by chat_stream (not chat_resume).
    """
    event_dict: dict[str, Any]
    if isinstance(event, dict):
        event_dict = event  # type: ignore[assignment]
    else:
        event_dict = {"event": str(type(event).__name__), "data": event} if event else {}

    event_type = event_dict.get("event")
    event_name = event_dict.get("name", "")
    metadata = event_dict.get("metadata", {}) if isinstance(event_dict.get("metadata"), dict) else {}
    langgraph_node = metadata.get("langgraph_node")

    is_node_event = langgraph_node is not None or (
        event_name
        and "node" in event_name.lower()
        and "tool" not in event_name.lower()
        and "model" not in event_name.lower()
        and "llm" not in event_name.lower()
        and "chat" not in event_name.lower()
    )

    run_id, parent_run_id = _extract_run_ids(event_dict)

    if event_type == "on_chat_model_start":
        yield await handler.handle_chat_model_start(event_dict, state, run_id, parent_run_id)

    elif event_type == "on_chat_model_stream":
        if sse := await handler.handle_chat_model_stream(event_dict, state, run_id, parent_run_id):
            yield sse

    elif event_type == "on_chat_model_end":
        yield await handler.handle_chat_model_end(event_dict, state, run_id, parent_run_id)

    elif event_type == "on_tool_start":
        yield await handler.handle_tool_start(event_dict, state, run_id, parent_run_id)

    elif event_type == "on_tool_end":
        yield await handler.handle_tool_end(event_dict, state, run_id, parent_run_id)

    elif event_type == "on_chain_start" and is_node_event:
        yield await handler.handle_node_start(event_dict, state, run_id, parent_run_id)

    elif event_type == "on_chain_end":
        if is_node_event:
            result = await handler.handle_node_end(event_dict, state, run_id, parent_run_id)
            if isinstance(result, list):
                for event_str in result:
                    if event_str and event_str.strip():
                        yield event_str.strip() + "\n\n"
            elif isinstance(result, str) and result.strip():
                yield result

        data_raw: Any = event_dict.get("data", {})
        data: Dict[str, Any] = data_raw if isinstance(data_raw, dict) else {}  # type: ignore[assignment]
        output = data.get("output") if isinstance(data, dict) else None
        if output and isinstance(output, dict) and "messages" in output:
            msgs = output["messages"]
            from langgraph.types import Overwrite

            state.all_messages = msgs.value if isinstance(msgs, Overwrite) else msgs

    # Drain file events (chat_stream only)
    if file_emitter is not None:
        for file_evt in file_emitter.drain():
            yield handler.format_sse(
                "file_event",
                {
                    "action": file_evt.action,
                    "path": file_evt.path,
                    "size": file_evt.size,
                    "timestamp": file_evt.timestamp,
                },
                state.thread_id,
                state,
            )
