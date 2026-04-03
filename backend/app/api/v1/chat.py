"""
Module: Chat API (Production Ready)

Overview:
- Chat WebSocket handler 复用的流式辅助模块
- 提供 LangGraph 事件分发、状态查询、消息持久化与结果归档能力
- 不再对外暴露 `/v1/chat` HTTP 接口

Dependencies:
- Database: 异步 SQLAlchemy 会话
- LangGraph: v2 事件流处理
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

# LangGraph 控制流异常：不将 trace 标为 FAILED
try:
    from langgraph.errors import GraphBubbleUp
except ImportError:
    GraphBubbleUp = None  # type: ignore[misc, assignment]


async def safe_get_state(
    graph: Any, config: RunnableConfig, max_retries: int = 3, initial_delay: float = 0.1, log: Any = None
) -> Any:
    """
    安全地获取图状态，带重试机制以避免连接冲突。

    Args:
        graph: LangGraph 图实例
        config: RunnableConfig 配置
        max_retries: 最大重试次数
        initial_delay: 初始延迟（秒），每次重试会翻倍
        log: 日志记录器（可选）

    Returns:
        图状态快照

    Raises:
        Exception: 如果所有重试都失败
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

            # 检查是否是连接冲突错误
            is_connection_error = (
                "another command is already in progress" in error_msg.lower() or "connection" in error_msg.lower()
            )

            # 如果是最后一次尝试，不再重试
            if attempt >= max_retries - 1:
                break

            # 如果是连接错误，等待后重试
            if is_connection_error:
                log.debug(
                    f"Connection conflict detected (attempt {attempt + 1}/{max_retries}), "
                    f"retrying after {delay:.2f}s delay"
                )
                await asyncio.sleep(delay)
                delay *= 2  # 指数退避
            else:
                # 如果不是连接错误，记录警告但继续重试（可能只是临时问题）
                log.warning(f"Failed to get state (attempt {attempt + 1}/{max_retries}): {e}")
                await asyncio.sleep(delay)
                delay *= 2

    # 所有重试都失败
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
    保存运行结果的通用逻辑。
    即使是在 finally 块中调用，也使用新的 DB Session 确保连接可用。
    同时将 Trace + Observations 批量持久化到数据库。
    """
    # --- 1. 保存消息 ---
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

    # --- 2. 持久化 Trace + Observations (事务安全) ---
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
    将 StreamState 中积累的 Observation 数据批量写入数据库。

    事务安全：使用 session.begin() 确保原子性。
    未完成的 observations 由 state.get_all_observations() 标记为 INTERRUPTED。
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

    # 确定 trace 状态
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

    # 聚合 token 统计
    total_tokens = 0
    for obs_rec in all_obs:
        if obs_rec.type == ObsType.GENERATION and obs_rec.total_tokens:
            total_tokens += obs_rec.total_tokens

    # 构造 ExecutionTrace ORM 对象
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

    # Enum 映射
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

    # 构造 ExecutionObservation ORM 对象
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

    # 事务安全批量写入
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(trace)
            session.add_all(db_observations)
        # commit 在 begin() 退出时自动执行
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


async def get_user_config(user_id: str, thread_id: str, db: AsyncSession, llm_model: str | None = None):
    """获取用户配置和 LLM 参数"""
    from loguru import logger

    from app.common.exceptions import ModelConfigError, NotFoundException
    from app.core.agent.langfuse_callback import get_langfuse_callbacks
    from app.core.model.utils.credential_resolver import LLMCredentialResolver

    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id, "user_id": str(user_id)},
        "recursion_limit": 300,
        "callbacks": get_langfuse_callbacks(enabled=settings.langfuse_enabled),
    }

    # 使用统一的 LLMCredentialResolver 获取凭据
    try:
        llm_params = await LLMCredentialResolver.get_llm_params(
            db=db,
            api_key=None,
            base_url=None,
            llm_model=llm_model,
            max_tokens=4096,
            user_id=str(user_id),
        )

        # 验证是否获取到有效的凭据
        if not llm_params.get("api_key") or not llm_params.get("llm_model"):
            raise ModelConfigError(
                ModelConfigError.MODEL_NO_CREDENTIALS,
                "No model configured. Please add an API key in Settings → Model Providers.",
            )
    except (NotFoundException, ModelConfigError):
        raise
    except Exception as e:
        logger.error(f"[get_user_config] Failed to get model from database: {e}")
        raise NotFoundException(f"Failed to load model configuration: {str(e)}")

    return config, {}, llm_params


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
    """保存助手消息，支持提取 Tool Calls"""
    # 找到最后一条 AI 消息
    ai_msg = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if not ai_msg:
        return

    meta_data = dict(ai_msg.additional_kwargs) if ai_msg.additional_kwargs else {}

    # 提取 Tool Calls (简化逻辑)
    if hasattr(ai_msg, "tool_calls") and ai_msg.tool_calls:
        tool_calls_data = []
        for tc in ai_msg.tool_calls:
            # 尝试找到对应的 ToolOutput
            # 注意：这里简化处理，严谨实现应遍历后续的 ToolMessage 匹配 ID
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
        log.info(f"[{endpoint}] 🔧 编辑技能模式: edit_skill_id={edit_skill_id}")
        enriched += (
            f"\n\n[Editing Mode] The user wants to modify an existing skill (ID: {edit_skill_id}). "
            f"The skill files have been pre-loaded into the sandbox. "
            f"Read the existing files first, then apply the user's requested changes."
        )

    files = metadata.get("files", [])
    if files:
        log.info(f"[{endpoint}] 📎 发现 {len(files)} 个文件: {files}")
        file_info = "\n\nAttached files:\n" + "\n".join([f"- {f['filename']}: {f['path']}" for f in files])
        enriched += file_info
        log.info(f"[{endpoint}] ✅ 消息已包含文件路径，长度: {len(enriched)}")

    return enriched


# ==================== Event Dispatch Helpers ====================


def _extract_run_ids(event_dict: dict) -> tuple[str, str | None]:
    """
    从 LangGraph v2 事件中提取 run_id 和 parent_run_id。

    LangGraph v2 astream_events 的每个事件包含:
    - run_id: 当前事件的唯一标识（可能为 UUID 或 str）
    - parent_ids: list, 从 root 到 immediate parent 排列

    统一转为 str，避免 UUID 作为 dict key 的兼容性问题。
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
