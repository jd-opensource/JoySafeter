"""
Module: Chat API (Production Ready)

Overview:
- 基于 LangGraph 构建的生产级对话接口
- 支持流式 (SSE) 和非流式调用
- 实现了完整的生命周期管理：启动、停止、断连保护、数据持久化
- 标准化的前端通信协议

Dependencies:
- Task Manager: 用于管理异步任务的取消和停止
- Database: 异步 SQLAlchemy 会话
- LangGraph: v2 事件流处理

Protocol (SSE):
All events follow this JSON structure in the `data` field:
{
  "type": "content" | "tool_start" | "tool_end" | "status" | "error" | "done",
  "thread_id": string,
  "run_id": string,          // 用于前端关联消息块
  "node_name": string,       // 当前节点 (e.g., "agent", "tools")
  "timestamp": number,       // 毫秒级时间戳
  "tags": string[],          // 标签
  "data": any                // 具体载荷 (delta, tool_input, etc.)
}
"""

import asyncio
import uuid
from typing import Any, AsyncGenerator, Dict

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import StreamingResponse
from langchain.messages import AIMessage, HumanMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser
from app.common.exceptions import (
    raise_client_closed_error,
    raise_internal_error,
    raise_not_found_error,
)
from app.core.agent.checkpointer.checkpointer import get_checkpointer
from app.core.agent.sample_agent import get_agent
from app.core.database import AsyncSessionLocal, get_db
from app.core.settings import settings
from app.models import Conversation, Message
from app.schemas import BaseResponse, ChatRequest, ChatResponse
from app.services.graph_service import GraphService
from app.utils.datetime import utc_now
from app.utils.stream_event_handler import StreamEventHandler, StreamState
from app.utils.task_manager import task_manager

# Note: graph_cache is no longer used - we use Checkpointer for state persistence

router = APIRouter(prefix="/v1/chat", tags=["Chat"])


# ==================== Data Models & Helpers ====================


class StopRequest(BaseModel):
    thread_id: str = Body(..., description="Conversation thread ID")


class ResumeRequest(BaseModel):
    thread_id: str = Body(..., description="Conversation thread ID")
    command: Dict[str, Any] = Body(..., description="Command object with update and/or goto")


def _bind_log(request: Request, **kwargs):
    """绑定上下文日志"""
    trace_id = getattr(request.state, "trace_id", "-")
    return logger.bind(trace_id=trace_id, **kwargs)


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


async def save_run_result(thread_id: str, state: StreamState, log) -> None:
    """
    保存运行结果的通用逻辑。
    即使是在 finally 块中调用，也使用新的 DB Session 确保连接可用。
    """
    if not state.assistant_content and not state.all_messages:
        return

    # 如果没有从 Graph 拿到完整的 messages 对象（例如被中断），
    # 则使用累积的文本构建兜底消息
    if not state.all_messages and state.assistant_content:
        log.warning(f"Using fallback content accumulation for thread {thread_id}")
        state.all_messages = [AIMessage(content=state.assistant_content)]

    if not state.all_messages:
        return

    try:
        async with AsyncSessionLocal() as session:
            # 复用已有的保存逻辑 (代码在下方定义)
            await save_assistant_message(thread_id, state.all_messages, session, update_conversation=True)
            log.info(f"Persisted messages for thread {thread_id}")
    except Exception as e:
        log.error(f"Failed to persist messages for thread {thread_id}: {e}")


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


async def get_user_config(user_id: str, thread_id: str, db: AsyncSession):
    """获取用户配置和 LLM 参数"""
    from loguru import logger

    from app.common.exceptions import NotFoundException
    from app.core.agent.langfuse_callback import get_langfuse_callbacks
    from app.core.model.utils.credential_resolver import LLMCredentialResolver

    get_langfuse_callbacks(enabled=settings.langfuse_enabled)

    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id, "user_id": str(user_id)},
        "recursion_limit": 100,
        "callbacks": get_langfuse_callbacks(enabled=settings.langfuse_enabled),
    }

    # 使用统一的 LLMCredentialResolver 获取凭据
    try:
        llm_params = await LLMCredentialResolver.get_llm_params(
            db=db,
            api_key=None,
            base_url=None,
            llm_model=None,
            max_tokens=4096,
        )

        # 验证是否获取到有效的凭据
        if not llm_params.get("api_key") or not llm_params.get("llm_model"):
            raise NotFoundException("未找到默认模型配置，请在前端配置模型")
    except NotFoundException:
        raise
    except Exception as e:
        logger.error(f"[get_user_config] Failed to get default model from database: {e}")
        raise NotFoundException(f"获取默认模型配置失败: {str(e)}")

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


# ==================== Event Handlers ====================
# 事件处理逻辑已抽取到 app.utils.stream_event_handler.StreamEventHandler


# ==================== Endpoints ====================


@router.post("/stop", response_model=BaseResponse[dict])
async def stop_chat(
    request: Request,
    payload: StopRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """停止任务"""
    thread_id = payload.thread_id
    log = _bind_log(request, user_id=str(current_user.id), thread_id=thread_id)

    # 验证权限
    res = await db.execute(
        select(Conversation).where(Conversation.thread_id == thread_id, Conversation.user_id == current_user.id)
    )
    if not res.scalar_one_or_none():
        # 即使找不到对话，只要任务存在也应该停止
        log.warning("Stop request for unknown conversation")

    stopped = await task_manager.stop_task(thread_id)
    cancelled = False
    if stopped:
        cancelled = await task_manager.cancel_task(thread_id)

    status = "stopped" if stopped else "not_running"
    return BaseResponse(success=True, code=200, msg="Task status retrieved", data={"status": status, "cancelled": cancelled})


@router.post("", response_model=BaseResponse[ChatResponse])
async def chat(
    request: Request,
    payload: ChatRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """非流式对话 (简化版，复用逻辑)

    注意: 如果图配置了中断点，graph.ainvoke() 会阻塞等待 Command。
    建议需要中断功能的场景使用流式端点 (/v1/chat/stream)。
    """
    thread_id, _ = await get_or_create_conversation(
        payload.thread_id, payload.message, current_user.id, payload.metadata, db
    )
    log = _bind_log(request, user_id=str(current_user.id), thread_id=thread_id)
    config, base_context, llm_params = await get_user_config(current_user.id, thread_id, db)

    try:
        await save_user_message(thread_id, payload.message, payload.metadata, db)

        # Get initial context from graph.variables.context if graph_id is provided
        initial_context = base_context.copy()
        if payload.graph_id:
            from app.repositories.graph import GraphRepository

            graph_repo = GraphRepository(db)
            graph_model = await graph_repo.get(payload.graph_id)
            if graph_model and graph_model.variables:
                context_vars = graph_model.variables.get("context", {})
                if context_vars:
                    # Convert ContextVariable objects to simple values
                    for key, value in context_vars.items():
                        if isinstance(value, dict) and "value" in value:
                            initial_context[key] = value["value"]
                        else:
                            initial_context[key] = value

        # Create graph: use default agent if graph_id is None, otherwise use graph from database
        if payload.graph_id is None:
            log.info("[Chat API] Using default agent (graph_id is None)")
            graph = await get_agent(
                checkpointer=get_checkpointer(),
                llm_model=llm_params["llm_model"],
                api_key=llm_params["api_key"],
                base_url=llm_params["base_url"],
                max_tokens=llm_params["max_tokens"],
                user_id=str(current_user.id),
            )
        else:
            graph_service = GraphService(db)
            graph = await graph_service.create_graph_by_graph_id(
                graph_id=payload.graph_id,
                llm_model=llm_params["llm_model"],
                api_key=llm_params["api_key"],
                base_url=llm_params["base_url"],
                max_tokens=llm_params["max_tokens"],
                user_id=current_user.id,
                current_user=current_user,
            )

        # 从 metadata 中提取文件信息并添加到消息中
        files = payload.metadata.get("files", [])
        if files:
            log.info(f"[Chat API] 📎 发现 {len(files)} 个文件: {files}")
            file_info = "\n\nAttached files:\n" + "\n".join([f"- {f['filename']}: {f['path']}" for f in files])
            enriched_message = payload.message + file_info
            log.info(f"[Chat API] ✅ 消息已包含文件路径，长度: {len(enriched_message)}")
        else:
            log.debug("[Chat API] ℹ️  没有发现文件附件")
            enriched_message = payload.message

        # 注册任务以支持非流式取消
        invoke_task = asyncio.create_task(
            graph.ainvoke(
                {"messages": [HumanMessage(content=enriched_message)], "context": initial_context}, config=config
            )
        )
        await task_manager.register_task(thread_id, invoke_task)

        try:
            result = await invoke_task
        except asyncio.CancelledError:
            raise_client_closed_error("Cancelled")
        finally:
            await task_manager.unregister_task(thread_id)
            # Cleanup shared backend if exists
            if hasattr(graph, "_cleanup_backend"):
                try:
                    await graph._cleanup_backend()
                except Exception as e:
                    log.warning(f"[Chat API] Failed to cleanup backend: {e}")

        messages = result["messages"]
        await save_assistant_message(thread_id, messages, db)

        return BaseResponse(
            success=True,
            code=200,
            msg="Chat completed successfully",
            data=ChatResponse(
                thread_id=thread_id,
                response=messages[-1].content if messages else "",
                duration_ms=0,  # 需自行添加计时逻辑
            ),
        )
    except Exception as e:
        log.error(f"Chat failed: {e}")
        # Ensure backend cleanup even if error occurs before finally block
        # (though finally should always execute, this is extra safety)
        if "graph" in locals() and hasattr(graph, "_cleanup_backend"):
            try:
                await graph._cleanup_backend()
            except Exception as cleanup_err:
                log.warning(f"[Chat API] Failed to cleanup backend in error handler: {cleanup_err}")
        raise_internal_error(str(e))


@router.post("/stream", response_class=StreamingResponse)
async def chat_stream(
    request: Request,
    payload: ChatRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """流式对话 (SSE) - 生产级实现"""
    log = _bind_log(request, user_id=str(current_user.id))

    # 1. 准备环境
    thread_id, _ = await get_or_create_conversation(
        payload.thread_id, payload.message, current_user.id, payload.metadata, db
    )
    await save_user_message(thread_id, payload.message, payload.metadata, db)

    config, base_context, llm_params = await get_user_config(current_user.id, thread_id, db)

    # Get initial context from graph.variables.context if graph_id is provided
    initial_context = base_context.copy()
    if payload.graph_id:
        from app.repositories.graph import GraphRepository

        graph_repo = GraphRepository(db)
        graph_model = await graph_repo.get(payload.graph_id)
        if graph_model and graph_model.variables:
            context_vars = graph_model.variables.get("context", {})
            if context_vars:
                # Convert ContextVariable objects to simple values
                for key, value in context_vars.items():
                    if isinstance(value, dict) and "value" in value:
                        initial_context[key] = value["value"]
                    else:
                        initial_context[key] = value

    # 2. 提前注册任务，确保停止请求能找到目标
    current_task = asyncio.current_task()
    if current_task:
        await task_manager.register_task(thread_id, current_task)

    async def event_generator() -> AsyncGenerator[str, None]:
        state = StreamState(thread_id)
        handler = StreamEventHandler()

        # 发送初始状态
        yield handler.format_sse("status", {"status": "connected", "_meta": {"node_name": "system"}}, thread_id)

        try:
            # 3. 创建图: 如果 graph_id 为 None，使用默认 Agent，否则从数据库加载图
            if payload.graph_id is None:
                log.info("[Chat API Stream] Using default agent (graph_id is None)")
                graph = await get_agent(
                    checkpointer=get_checkpointer(),
                    llm_model=llm_params["llm_model"],
                    api_key=llm_params["api_key"],
                    base_url=llm_params["base_url"],
                    max_tokens=llm_params["max_tokens"],
                    user_id=str(current_user.id),
                )
            else:
                graph_service = GraphService(db)
                graph = await graph_service.create_graph_by_graph_id(
                    graph_id=payload.graph_id,
                    llm_model=llm_params["llm_model"],
                    api_key=llm_params["api_key"],
                    base_url=llm_params["base_url"],
                    max_tokens=llm_params["max_tokens"],
                    user_id=current_user.id,
                    current_user=current_user,
                )

            # 5. 从 metadata 中提取文件信息并添加到消息中
            files = payload.metadata.get("files", [])
            if files:
                log.info(f"[Chat API Stream] 📎 发现 {len(files)} 个文件: {files}")
                file_info = "\n\nAttached files:\n" + "\n".join([f"- {f['filename']}: {f['path']}" for f in files])
                enriched_message = payload.message + file_info
                log.info(f"[Chat API Stream] ✅ 消息已包含文件路径，长度: {len(enriched_message)}")
            else:
                log.debug("[Chat API Stream] ℹ️  没有发现文件附件")
                enriched_message = payload.message

            # 6. 事件循环
            async for event in graph.astream_events(
                {"messages": [HumanMessage(content=enriched_message)], "context": initial_context},
                config=config,
                version="v2",
            ):
                # log.info(f"Event: {event}")
                # A. 停止检测
                if await task_manager.is_stopped(thread_id):
                    state.stopped = True
                    log.info(f"Task stopped by user: {thread_id}")
                    break

                # B. 事件分发
                if isinstance(event, dict):
                    event_dict = event
                else:
                    # Convert event to dict if needed
                    event_dict = {"event": str(type(event).__name__), "data": event} if event else {}
                event_type = event_dict.get("event")
                event_name = event_dict.get("name", "")
                metadata = event_dict.get("metadata", {}) if isinstance(event_dict.get("metadata"), dict) else {}
                langgraph_node = metadata.get("langgraph_node")

                # 判断是否是节点事件（不是工具或LLM的内部事件）
                is_node_event = langgraph_node is not None or (
                    event_name
                    and "node" in event_name.lower()
                    and "tool" not in event_name.lower()
                    and "model" not in event_name.lower()
                    and "llm" not in event_name.lower()
                    and "chat" not in event_name.lower()
                )

                if event_type == "on_chat_model_start":
                    yield await handler.handle_chat_model_start(event_dict, state)  # type: ignore[arg-type]

                elif event_type == "on_chat_model_stream":
                    if sse := await handler.handle_chat_model_stream(event_dict, state):  # type: ignore[arg-type]
                        yield sse

                elif event_type == "on_chat_model_end":
                    yield await handler.handle_chat_model_end(event_dict, state)  # type: ignore[arg-type]

                elif event_type == "on_tool_start":
                    yield await handler.handle_tool_start(event_dict, state)  # type: ignore[arg-type]

                elif event_type == "on_tool_end":
                    yield await handler.handle_tool_end(event_dict, state)  # type: ignore[arg-type]

                # 节点生命周期事件
                elif event_type == "on_chain_start" and is_node_event:
                    yield await handler.handle_node_start(event_dict, state)  # type: ignore[arg-type]

                elif event_type == "on_chain_end":
                    # 如果是节点结束事件，发送节点结束事件（可能返回多个事件）
                    if is_node_event:
                        result = await handler.handle_node_end(event_dict, state)  # type: ignore[arg-type]
                        # handle_node_end 现在返回多个事件（用换行分隔）或单个事件
                        if isinstance(result, str):
                            # 如果是单个字符串，可能包含多个事件（用 \n\n 分隔）
                            for event_str in result.split("\n\n"):
                                if event_str.strip():
                                    yield event_str.strip() + "\n\n"
                        elif isinstance(result, list):
                            # 如果是列表，逐个发送
                            for event_str in result:
                                if event_str.strip():
                                    yield event_str.strip() + "\n\n"
                        else:
                            # 单个事件字符串
                            yield result

                    # C. 收集完整消息 (但不发送 SSE，仅用于最终状态确认)
                    # LangGraph 有时会在 on_chain_end 的 output 中包含最终消息列表
                    # 我们可以尝试提取以确保 all_messages 最完整
                    data_raw: Any = event_dict.get("data", {})
                    data: Dict[str, Any] = data_raw if isinstance(data_raw, dict) else {}  # type: ignore[assignment]
                    output = data.get("output") if isinstance(data, dict) else None
                    if output and isinstance(output, dict) and "messages" in output:
                        state.all_messages = output["messages"]

            # 5. 检查是否有中断
            interrupted = False
            try:
                snap = await safe_get_state(graph, config, max_retries=3, initial_delay=0.1, log=log)
                # 检查是否有待处理的任务（中断状态）
                if snap.tasks:
                    # 图处于中断状态，发送 interrupt 事件
                    next_node = snap.tasks[0].target if snap.tasks else None
                    current_state = snap.values or {}

                    # 提取节点信息
                    node_info = {}
                    if next_node:
                        node_info["node_name"] = next_node
                        node_info["node_label"] = next_node.replace("_", " ").title()

                    interrupt_data = {
                        "node_name": node_info.get("node_name", "unknown"),
                        "node_label": node_info.get("node_label", "Unknown Node"),
                        "state": current_state,
                        "thread_id": thread_id,
                    }

                    log.info(f"Graph interrupted at node '{next_node}' | thread_id={thread_id}")
                    yield handler.format_sse("interrupt", interrupt_data, thread_id)
                    if payload.graph_id:
                        async with AsyncSessionLocal() as session:
                            result_query = await session.execute(
                                select(Conversation).where(Conversation.thread_id == thread_id)
                            )
                            if conv := result_query.scalar_one_or_none():
                                if not conv.meta_data:
                                    conv.meta_data = {}
                                conv.meta_data["interrupted_graph_id"] = str(payload.graph_id)
                                await session.commit()
                                log.debug(f"Stored graph_id in conversation metadata | thread_id={thread_id}")

                    state.interrupted = True
                    state.interrupt_node = next_node
                    state.interrupt_state = current_state
                    interrupted = True

            except Exception as e:
                # 如果查询失败（可能是连接冲突），记录警告但不影响流程
                # 中断状态会在 resume 时重新检查
                log.warning(f"Failed to check interrupt state (may be due to connection conflict): {e}")

            # 6. 循环结束处理
            # 尝试最后一次获取完整状态 (防止 on_chain_end 没触发或被跳过)
            if not state.all_messages and not state.stopped and not interrupted:
                try:
                    snap = await safe_get_state(graph, config, max_retries=2, initial_delay=0.05, log=log)
                    if snap.values and "messages" in snap.values:
                        state.all_messages = snap.values["messages"]
                except Exception as e:
                    log.warning(f"Failed to fetch final state: {e}")

            # 7. 发送结束信号（如果未中断）
            if interrupted:
                # 中断状态，不发送 done 事件，等待用户操作
                # 事件流会在这里暂停，等待 /v1/chat/resume 端点被调用
                pass
            elif state.stopped:
                yield handler.format_sse(
                    "error",
                    {"message": "Stopped by user", "code": "stopped", "_meta": {"node_name": "system"}},
                    thread_id,
                )
            else:
                yield handler.format_sse("done", {"_meta": {"node_name": "system"}}, thread_id)

        except asyncio.CancelledError:
            log.warning(f"Client disconnected: {thread_id}")
            state.stopped = True  # 标记为停止以便后续保存逻辑知道状态
            # 无需 yield，因为客户端已断开
        except Exception as e:
            import traceback

            log.error(f"Stream error: {e}, traceback: {traceback.format_exc()}")
            state.has_error = True
            yield handler.format_sse("error", {"message": str(e), "_meta": {"node_name": "system"}}, thread_id)
        finally:
            # 7. 清理与持久化 (关键：使用 finally 确保即使报错/断连也执行)
            await task_manager.unregister_task(thread_id)
            await save_run_result(thread_id, state, log)
            # Cleanup shared backend if exists
            if "graph" in locals() and hasattr(graph, "_cleanup_backend"):
                try:
                    await graph._cleanup_backend()
                except Exception as e:
                    log.warning(f"[Chat API Stream] Failed to cleanup backend: {e}")
            # 如果执行完成（非中断），清理 conversation 中的中断标记
            if not state.interrupted:
                async with AsyncSessionLocal() as session:
                    result_query = await session.execute(select(Conversation).where(Conversation.thread_id == thread_id))
                    if conv := result_query.scalar_one_or_none():
                        if conv.meta_data and "interrupted_graph_id" in conv.meta_data:
                            del conv.meta_data["interrupted_graph_id"]
                            await session.commit()
                            log.debug(f"Cleared interrupt marker from conversation | thread_id={thread_id}")

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/resume", response_class=StreamingResponse)
async def chat_resume(
    request: Request,
    payload: ResumeRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """恢复中断的图执行 (SSE) - 使用 Command 机制和 Checkpointer"""
    log = _bind_log(request, user_id=str(current_user.id))
    thread_id = payload.thread_id

    # 1. 从 conversation 获取 graph_id 和用户配置
    result = await db.execute(
        select(Conversation).where(Conversation.thread_id == thread_id, Conversation.user_id == str(current_user.id))
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        log.error(f"Conversation not found | thread_id={thread_id}")
        raise_not_found_error("Conversation not found.")

    # 获取 graph_id（从 conversation.meta_data 或从 checkpointer 状态推断）
    graph_id = None
    if conversation and conversation.meta_data and isinstance(conversation.meta_data, dict) and "interrupted_graph_id" in conversation.meta_data:
        import uuid as uuid_lib

        try:
            graph_id = uuid_lib.UUID(str(conversation.meta_data["interrupted_graph_id"]))
        except (ValueError, TypeError):
            log.warning(f"Invalid graph_id in conversation metadata | thread_id={thread_id}")

    # 如果无法从 conversation 获取，尝试从 checkpointer 状态推断
    if not graph_id:
        # 从 checkpointer 获取最新状态，尝试推断 graph_id
        # 注意：这需要 graph_id 存储在状态中，或者通过其他方式获取
        log.warning(
            f"Graph ID not found in conversation metadata, attempting to infer from state | thread_id={thread_id}"
        )
        # 可以尝试从其他来源获取 graph_id，例如从最近的执行记录

    # 2. 获取用户配置和 LLM 参数
    config, base_context, llm_params = await get_user_config(current_user.id, thread_id, db)

    # 3. 重新构建图
    # Checkpointer 会自动恢复之前的状态
    if graph_id is None:
        raise_not_found_error("Graph ID not found in conversation metadata or state")
    
    # Type narrowing: graph_id is guaranteed to be UUID after check
    assert graph_id is not None
    
    try:
        graph_service = GraphService(db)
        graph = await graph_service.create_graph_by_graph_id(
            graph_id=graph_id,
            llm_model=llm_params["llm_model"],
            api_key=llm_params["api_key"],
            base_url=llm_params["base_url"],
            max_tokens=llm_params["max_tokens"],
            user_id=current_user.id,
            current_user=current_user,
        )
        log.info(f"Graph rebuilt for resume | thread_id={thread_id} | graph_id={graph_id}")
    except Exception as e:
        log.error(f"Failed to rebuild graph | thread_id={thread_id} | error={e}")
        raise_internal_error(f"Failed to rebuild graph: {str(e)}")

    # 4. 验证 checkpointer 中是否有中断状态
    try:
        snap = await safe_get_state(graph, config, max_retries=3, initial_delay=0.1, log=log)
        if not snap.tasks:
            log.warning(f"No interrupt state found in checkpointer | thread_id={thread_id}")
            raise_not_found_error("No interrupt state found. Execution may have completed or expired.")
    except Exception as e:
        log.error(f"Failed to verify interrupt state | thread_id={thread_id} | error={e}")
        raise_not_found_error("Failed to verify interrupt state. Execution may have expired.")

    log.info(f"Resuming graph execution | thread_id={thread_id} | graph_id={graph_id}")

    # 5. 构造 LangGraph Command 对象
    from langgraph.types import Command

    command_update = payload.command.get("update")
    command_goto = payload.command.get("goto")

    command = Command(
        update=command_update if command_update else {},
        goto=command_goto if command_goto else None,
    )

    log.info(f"Command constructed | thread_id={thread_id} | has_update={bool(command_update)} | goto={command_goto}")

    # 6. 注册任务以支持取消
    current_task = asyncio.current_task()
    if current_task:
        await task_manager.register_task(thread_id, current_task)

    async def event_generator() -> AsyncGenerator[str, None]:
        state = StreamState(thread_id)
        handler = StreamEventHandler()

        # 发送恢复状态
        yield handler.format_sse("status", {"status": "resumed", "_meta": {"node_name": "system"}}, thread_id)

        try:
            # 4. 使用 Command 继续执行
            async for event in graph.astream_events(command, config=config, version="v2"):
                # A. 停止检测
                if await task_manager.is_stopped(thread_id):
                    state.stopped = True
                    log.info(f"Task stopped by user: {thread_id}")
                    break

                # B. 事件分发（复用 chat_stream 的逻辑）
                if isinstance(event, dict):
                    event_dict = event
                else:
                    # Convert event to dict if needed
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

                if event_type == "on_chat_model_start":
                    yield await handler.handle_chat_model_start(event_dict, state)  # type: ignore[arg-type]

                elif event_type == "on_chat_model_stream":
                    if sse := await handler.handle_chat_model_stream(event_dict, state):  # type: ignore[arg-type]
                        yield sse

                elif event_type == "on_chat_model_end":
                    yield await handler.handle_chat_model_end(event_dict, state)  # type: ignore[arg-type]

                elif event_type == "on_tool_start":
                    yield await handler.handle_tool_start(event_dict, state)  # type: ignore[arg-type]

                elif event_type == "on_tool_end":
                    yield await handler.handle_tool_end(event_dict, state)  # type: ignore[arg-type]

                elif event_type == "on_chain_start" and is_node_event:
                    yield await handler.handle_node_start(event_dict, state)  # type: ignore[arg-type]

                elif event_type == "on_chain_end":
                    if is_node_event:
                        result = await handler.handle_node_end(event_dict, state)  # type: ignore[arg-type]
                        # handle_node_end 现在返回多个事件（用换行分隔）或单个事件
                        if result and isinstance(result, str):
                            # 如果包含多个事件（用 \n\n 分隔），逐个发送
                            for event_str in result.split("\n\n"):
                                if event_str.strip():
                                    yield event_str.strip() + "\n\n"

                    data_raw: Any = event_dict.get("data", {})
                    data: Dict[str, Any] = data_raw if isinstance(data_raw, dict) else {}  # type: ignore[assignment]
                    output = data.get("output") if isinstance(data, dict) else None
                    if output and isinstance(output, dict) and "messages" in output:
                        state.all_messages = output["messages"]

            # 5. 检查是否有新的中断
            interrupted = False
            try:
                snap = await safe_get_state(graph, config, max_retries=3, initial_delay=0.1, log=log)
                if snap.tasks:
                    next_node = snap.tasks[0].target if snap.tasks else None
                    current_state = snap.values or {}

                    node_info = {}
                    if next_node:
                        node_info["node_name"] = next_node
                        node_info["node_label"] = next_node.replace("_", " ").title()

                    interrupt_data = {
                        "node_name": node_info.get("node_name", "unknown"),
                        "node_label": node_info.get("node_label", "Unknown Node"),
                        "state": current_state,
                        "thread_id": thread_id,
                    }

                    log.info(f"Graph interrupted again at node '{next_node}' | thread_id={thread_id}")
                    yield handler.format_sse("interrupt", interrupt_data, thread_id)

                    state.interrupted = True
                    state.interrupt_node = next_node
                    state.interrupt_state = current_state
                    interrupted = True

            except Exception as e:
                # 如果查询失败（可能是连接冲突），记录警告但不影响流程
                # 中断状态会在 resume 时重新检查
                log.warning(f"Failed to check interrupt state (may be due to connection conflict): {e}")

            # 6. 获取最终状态
            if not state.all_messages and not state.stopped and not interrupted:
                try:
                    snap = await safe_get_state(graph, config, max_retries=2, initial_delay=0.05, log=log)
                    if snap.values and "messages" in snap.values:
                        state.all_messages = snap.values["messages"]
                except Exception as e:
                    log.warning(f"Failed to fetch final state: {e}")

            # 7. 发送结束信号
            if interrupted:
                pass  # 等待下一次恢复
            elif state.stopped:
                yield handler.format_sse(
                    "error",
                    {"message": "Stopped by user", "code": "stopped", "_meta": {"node_name": "system"}},
                    thread_id,
                )
            else:
                # 执行完成，清理 conversation 中的中断标记
                async with AsyncSessionLocal() as session:
                    result_query = await session.execute(select(Conversation).where(Conversation.thread_id == thread_id))
                    if conv := result_query.scalar_one_or_none():
                        if conv.meta_data and "interrupted_graph_id" in conv.meta_data:
                            del conv.meta_data["interrupted_graph_id"]
                            await session.commit()
                            log.debug(f"Cleared interrupt marker from conversation | thread_id={thread_id}")
                yield handler.format_sse("done", {"_meta": {"node_name": "system"}}, thread_id)

        except asyncio.CancelledError:
            log.warning(f"Client disconnected: {thread_id}")
            state.stopped = True
        except Exception as e:
            log.error(f"Resume stream error: {e}")
            state.has_error = True
            yield handler.format_sse("error", {"message": str(e), "_meta": {"node_name": "system"}}, thread_id)
        finally:
            await task_manager.unregister_task(thread_id)
            await save_run_result(thread_id, state, log)
            # Cleanup shared backend if exists
            if "graph" in locals() and hasattr(graph, "_cleanup_backend"):
                try:
                    await graph._cleanup_backend()
                except Exception as e:
                    log.warning(f"[Chat API Resume] Failed to cleanup backend: {e}")
            # 如果执行完成（非中断），清理 conversation 中的中断标记
            if not state.interrupted:
                async with AsyncSessionLocal() as session:
                    result_query = await session.execute(select(Conversation).where(Conversation.thread_id == thread_id))
                    if conv := result_query.scalar_one_or_none():
                        if conv.meta_data and "interrupted_graph_id" in conv.meta_data:
                            del conv.meta_data["interrupted_graph_id"]
                            await session.commit()
                            log.debug(f"Cleared interrupt marker from conversation | thread_id={thread_id}")

    return StreamingResponse(event_generator(), media_type="text/event-stream")
